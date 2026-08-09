output "lambda_function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.this.function_name
}
