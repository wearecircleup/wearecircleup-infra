variable "bucket_name" {
  description = "Name of the validation S3 bucket."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}
