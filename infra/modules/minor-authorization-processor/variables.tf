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

variable "jobs_table_arn" {
  description = "DynamoDB table ARN used to reconcile minor authorization jobs."
  type        = string
}

variable "jobs_table_name" {
  description = "DynamoDB table name used to reconcile minor authorization jobs."
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
