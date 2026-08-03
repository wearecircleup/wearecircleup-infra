resource "aws_sqs_queue" "dlq" {
  name = var.dlq_name

  message_retention_seconds = 1209600

  tags = var.common_tags
}

resource "aws_sqs_queue" "this" {
  name = var.queue_name

  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  message_retention_seconds  = 1209600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.common_tags
}

resource "aws_iam_role" "lambda" {
  name = var.lambda_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "sqs" {
  name = "${var.lambda_function_name}-sqs"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [
          aws_sqs_queue.this.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "dynamodb" {
  name = "${var.lambda_function_name}-dynamodb"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = [
          var.jobs_table_arn,
          "${var.jobs_table_arn}/index/*",
          var.youform_submissions_table_arn,
          "${var.youform_submissions_table_arn}/index/*",
          var.eventbrite_order_submissions_table_arn,
          "${var.eventbrite_order_submissions_table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "secrets" {
  name = "${var.lambda_function_name}-secrets"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          var.eventbrite_secret_arn
        ]
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 14

  tags = var.common_tags
}

resource "aws_lambda_function" "this" {
  function_name = var.lambda_function_name
  role          = aws_iam_role.lambda.arn
  handler       = "lambda_handler.handler"
  runtime       = "python3.13"
  timeout       = var.lambda_timeout_seconds
  memory_size   = 256
  filename      = var.lambda_package_path

  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = {
      EVENTBRITE_SECRET_ID                    = var.eventbrite_secret_name
      EVENTBRITE_ORDER_SUBMISSIONS_TABLE_NAME = var.eventbrite_order_submissions_table_name
      YOUFORM_SUBMISSIONS_TABLE_NAME          = var.youform_submissions_table_name
      AUTHORIZATION_JOBS_TABLE_NAME           = var.jobs_table_name
      AUTHORIZATION_MAX_ATTEMPTS              = tostring(var.authorization_max_attempts)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda
  ]

  tags = var.common_tags
}

resource "aws_lambda_event_source_mapping" "sqs" {
  event_source_arn = aws_sqs_queue.this.arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = 1
}
