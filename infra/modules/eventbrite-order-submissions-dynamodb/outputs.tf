output "table_arn" {
  description = "DynamoDB table ARN for normalized Eventbrite order submissions."
  value       = aws_dynamodb_table.this.arn
}

output "table_name" {
  description = "DynamoDB table name for normalized Eventbrite order submissions."
  value       = aws_dynamodb_table.this.name
}
