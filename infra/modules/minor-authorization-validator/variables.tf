variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "dlq_name" {
  description = "Dead-letter queue name."
  type        = string
}

variable "eventbrite_order_submissions_table_arn" {
  description = "DynamoDB table ARN storing normalized Eventbrite order submissions."
  type        = string
}

variable "eventbrite_order_submissions_table_name" {
  description = "DynamoDB table name storing normalized Eventbrite order submissions."
  type        = string
}

variable "eventbrite_secret_arn" {
  description = "Secrets Manager ARN containing Eventbrite values."
  type        = string
}

variable "eventbrite_secret_name" {
  description = "Secrets Manager name containing Eventbrite values."
  type        = string
}

variable "jobs_table_arn" {
  description = "DynamoDB table ARN storing minor authorization validation jobs."
  type        = string
}

variable "jobs_table_name" {
  description = "DynamoDB table name storing minor authorization validation jobs."
  type        = string
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

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 30
}

variable "authorization_max_attempts" {
  description = "Maximum number of validation attempts recorded by the worker."
  type        = number
  default     = 5
}

variable "max_receive_count" {
  description = "Maximum receives before the SQS message moves to the DLQ."
  type        = number
  default     = 5
}

variable "queue_name" {
  description = "Primary SQS queue name."
  type        = string
}

variable "queue_visibility_timeout_seconds" {
  description = "Primary SQS queue visibility timeout in seconds."
  type        = number
  default     = 180
}

variable "youform_submissions_table_arn" {
  description = "DynamoDB table ARN storing normalized YouForm submissions."
  type        = string
}

variable "youform_submissions_table_name" {
  description = "DynamoDB table name storing normalized YouForm submissions."
  type        = string
}
