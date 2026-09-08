variable "api_name" {
  description = "API Gateway name."
  type        = string
}

variable "eventbrite_secret_arn" {
  description = "Secrets Manager ARN containing shared Eventbrite and authorization values."
  type        = string
}

variable "eventbrite_secret_name" {
  description = "Secrets Manager name containing shared Eventbrite and authorization values."
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
  description = "Private S3 bucket ARN used to store minor-authorization files."
  type        = string
}

variable "signatures_bucket_name" {
  description = "Private S3 bucket name used to store minor-authorization files."
  type        = string
}

variable "submissions_table_arn" {
  description = "DynamoDB table ARN used to store minor-authorization YouForm submissions."
  type        = string
}

variable "submissions_table_name" {
  description = "DynamoDB table name used to store minor-authorization YouForm submissions."
  type        = string
}

variable "volunteer_background_check_files_bucket_arn" {
  description = "Private S3 bucket ARN used to store copied YouForm background-check files."
  type        = string
}

variable "volunteer_background_check_files_bucket_name" {
  description = "Private S3 bucket name used to store copied YouForm background-check files."
  type        = string
}

variable "volunteer_background_check_submissions_table_arn" {
  description = "DynamoDB table ARN used to store volunteer background-check submissions."
  type        = string
}

variable "volunteer_background_check_submissions_table_name" {
  description = "DynamoDB table name used to store volunteer background-check submissions."
  type        = string
}

variable "volunteer_intent_proposal_submissions_table_arn" {
  description = "DynamoDB table ARN used to store volunteer intent proposal submissions."
  type        = string
}

variable "volunteer_intent_proposal_submissions_table_name" {
  description = "DynamoDB table name used to store volunteer intent proposal submissions."
  type        = string
}

variable "minor_authorization_processor_lambda_arn" {
  description = "Lambda ARN used to reconcile minor authorization submissions."
  type        = string
}

variable "minor_authorization_processor_lambda_name" {
  description = "Lambda name used to reconcile minor authorization submissions."
  type        = string
}

variable "volunteer_intent_notifier_lambda_arn" {
  description = "Lambda ARN used to process volunteer intent notifications."
  type        = string
}

variable "volunteer_intent_notifier_lambda_name" {
  description = "Lambda name used to process volunteer intent notifications."
  type        = string
}

variable "background_check_dispatcher_lambda_arn" {
  description = "Lambda ARN used to dispatch background check review jobs."
  type        = string
}

variable "background_check_dispatcher_lambda_name" {
  description = "Lambda name used to dispatch background check review jobs."
  type        = string
}
