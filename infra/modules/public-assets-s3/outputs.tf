output "bucket_arn" {
  description = "ARN of the public assets bucket."
  value       = aws_s3_bucket.this.arn
}

output "bucket_name" {
  description = "Name of the public assets bucket."
  value       = aws_s3_bucket.this.bucket
}

output "base_url" {
  description = "Base URL for public objects stored in the bucket."
  value       = "https://${aws_s3_bucket.this.bucket}.s3.${data.aws_region.current.id}.amazonaws.com"
}
