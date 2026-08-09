output "dlq_arn" {
  description = "Dead-letter queue ARN."
  value       = aws_sqs_queue.dlq.arn
}

output "queue_arn" {
  description = "Primary queue ARN."
  value       = aws_sqs_queue.this.arn
}

output "queue_name" {
  description = "Primary queue name."
  value       = aws_sqs_queue.this.name
}

output "queue_url" {
  description = "Primary queue URL."
  value       = aws_sqs_queue.this.url
}
