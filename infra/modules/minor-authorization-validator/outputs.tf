output "dlq_arn" {
  description = "Dead-letter queue ARN."
  value       = aws_sqs_queue.dlq.arn
}

output "dlq_name" {
  description = "Dead-letter queue name."
  value       = aws_sqs_queue.dlq.name
}

output "lambda_function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.this.function_name
}

output "queue_arn" {
  description = "Primary SQS queue ARN."
  value       = aws_sqs_queue.this.arn
}

output "queue_name" {
  description = "Primary SQS queue name."
  value       = aws_sqs_queue.this.name
}

output "queue_url" {
  description = "Primary SQS queue URL."
  value       = aws_sqs_queue.this.url
}
