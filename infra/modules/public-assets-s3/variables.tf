variable "bucket_name" {
  description = "Name of the public assets S3 bucket."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "aws_region" {
  description = "AWS region where the bucket is created."
  type        = string
}
