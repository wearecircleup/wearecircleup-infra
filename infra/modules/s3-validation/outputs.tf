output "bucket_name" {
  description = "Validation S3 bucket name."
  value       = aws_s3_bucket.this.bucket
}
