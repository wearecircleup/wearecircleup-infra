output "lambda_function_arn" {
  description = "Reminder Lambda ARN."
  value       = aws_lambda_function.this.arn
}

output "lambda_function_name" {
  description = "Reminder Lambda name."
  value       = aws_lambda_function.this.function_name
}

output "schedule_rule_name" {
  description = "EventBridge schedule rule name."
  value       = aws_cloudwatch_event_rule.daily.name
}
