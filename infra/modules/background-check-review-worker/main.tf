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
          var.queue_arn
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
          "dynamodb:UpdateItem"
        ]
        Resource = [
          var.background_check_submissions_table_arn,
          var.background_check_reviews_table_arn,
          "${var.background_check_reviews_table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "s3" {
  name = "${var.lambda_function_name}-s3"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${var.background_check_files_bucket_arn}/*"
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

resource "aws_iam_role_policy" "bedrock" {
  name = "${var.lambda_function_name}-bedrock"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:Converse",
          "bedrock:ConverseStream",
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "textract" {
  name = "${var.lambda_function_name}-textract"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "textract:DetectDocumentText"
        ]
        Resource = "*"
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
  memory_size   = var.lambda_memory_size
  filename      = var.lambda_package_path

  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = {
      EVENTBRITE_SECRET_ID                    = var.eventbrite_secret_name
      BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME = var.background_check_submissions_table_name
      BACKGROUND_CHECK_REVIEWS_TABLE_NAME     = var.background_check_reviews_table_name
      BACKGROUND_CHECK_FILES_BUCKET_NAME      = var.background_check_files_bucket_name
      BACKGROUND_CHECK_MODEL_ID_SECRET_KEY    = "BEDROCK_MODEL_ID"
      BACKGROUND_CHECK_FORM_ID_SECRET_KEY     = "VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID"
      BACKGROUND_CHECK_REVIEW_MAX_PAGES       = "1"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda
  ]

  tags = var.common_tags
}

resource "aws_lambda_event_source_mapping" "sqs" {
  event_source_arn = var.queue_arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = 1
}
