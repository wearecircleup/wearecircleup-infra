output "bucket_arn" {
  description = "ARN of the private bucket used to store copied YouForm signatures."
  value       = aws_s3_bucket.this.arn
}

output "bucket_name" {
  description = "Name of the private bucket used to store copied YouForm signatures."
  value       = aws_s3_bucket.this.bucket
}
