output "api_endpoint" {
  description = "Default invoke URL for the HTTP API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "lambda_function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.this.function_name
}

output "webhook_url" {
  description = "Full URL to configure in YouForm."
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}${var.route_path}"
}
