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
          "dynamodb:UpdateItem"
        ]
        Resource = [
          var.submissions_table_arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ses" {
  name = "${var.lambda_function_name}-ses"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
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
  timeout       = 30
  memory_size   = 256
  filename      = var.lambda_package_path

  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = {
      VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME = var.submissions_table_name
      VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL         = var.notification_from_email
      VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL           = var.notification_to_email
      VOLUNTEER_INTENT_NOTIFICATION_REPLY_TO_EMAIL     = var.notification_reply_to_email
      VOLUNTEER_INTENT_NOTIFICATION_LOGO_URL           = var.notification_logo_url
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda
  ]

  tags = var.common_tags
}
