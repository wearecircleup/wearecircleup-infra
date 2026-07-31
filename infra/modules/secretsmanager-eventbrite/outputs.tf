output "secret_arn" {
  description = "Eventbrite secret ARN."
  value       = aws_secretsmanager_secret.this.arn
}

output "secret_name" {
  description = "Eventbrite secret name."
  value       = aws_secretsmanager_secret.this.name
}
