output "table_arn" {
  description = "DynamoDB table ARN for minor authorization validation jobs."
  value       = aws_dynamodb_table.this.arn
}

output "table_name" {
  description = "DynamoDB table name for minor authorization validation jobs."
  value       = aws_dynamodb_table.this.name
}
