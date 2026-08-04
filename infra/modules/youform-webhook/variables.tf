variable "api_name" {
  description = "API Gateway name."
  type        = string
}

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

variable "route_path" {
  description = "HTTP API route path for the webhook endpoint."
  type        = string
}

variable "signatures_bucket_arn" {
  description = "S3 bucket ARN used to store copied signature images."
  type        = string
}

variable "signatures_bucket_name" {
  description = "S3 bucket name used to store copied signature images."
  type        = string
}

variable "submissions_table_arn" {
  description = "DynamoDB table ARN used to store normalized YouForm submissions."
  type        = string
}

variable "submissions_table_name" {
  description = "DynamoDB table name used to store normalized YouForm submissions."
  type        = string
}

variable "minor_authorization_jobs_table_arn" {
  description = "DynamoDB table ARN used to reconcile minor authorization jobs."
  type        = string
}

variable "minor_authorization_jobs_table_name" {
  description = "DynamoDB table name used to reconcile minor authorization jobs."
  type        = string
}
