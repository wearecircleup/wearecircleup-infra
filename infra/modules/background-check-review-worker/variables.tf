variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "lambda_function_name" {
  description = "Lambda function name."
  type        = string
}

variable "lambda_package_path" {
  description = "Path to the Lambda deployment package zip."
  type        = string
}

variable "lambda_role_name" {
  description = "IAM role name for the Lambda function."
  type        = string
}

variable "queue_arn" {
  description = "SQS queue ARN consumed by the worker."
  type        = string
}

variable "background_check_submissions_table_arn" {
  description = "DynamoDB table ARN that stores background-check submissions."
  type        = string
}

variable "background_check_submissions_table_name" {
  description = "DynamoDB table name that stores background-check submissions."
  type        = string
}

variable "background_check_reviews_table_arn" {
  description = "DynamoDB table ARN that stores extracted review results."
  type        = string
}

variable "background_check_reviews_table_name" {
  description = "DynamoDB table name that stores extracted review results."
  type        = string
}

variable "background_check_files_bucket_arn" {
  description = "Private S3 bucket ARN containing downloaded background-check files."
  type        = string
}

variable "background_check_files_bucket_name" {
  description = "Private S3 bucket name containing downloaded background-check files."
  type        = string
}

variable "eventbrite_secret_arn" {
  description = "Secrets Manager ARN containing shared runtime configuration."
  type        = string
}

variable "eventbrite_secret_name" {
  description = "Secrets Manager name containing shared runtime configuration."
  type        = string
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda memory size in MB."
  type        = number
  default     = 1024
}
