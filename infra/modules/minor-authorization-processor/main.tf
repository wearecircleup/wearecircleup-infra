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
          "dynamodb:Query",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          var.jobs_table_arn,
          "${var.jobs_table_arn}/index/*"
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
  timeout       = 30
  memory_size   = 256
  filename      = var.lambda_package_path

  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = {
      EVENTBRITE_SECRET_ID          = var.eventbrite_secret_name
      AUTHORIZATION_JOBS_TABLE_NAME = var.jobs_table_name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda
  ]

  tags = var.common_tags
}
