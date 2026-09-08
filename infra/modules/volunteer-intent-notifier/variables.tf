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

variable "submissions_table_arn" {
  description = "DynamoDB table ARN used to store volunteer intent submissions."
  type        = string
}

variable "submissions_table_name" {
  description = "DynamoDB table name used to store volunteer intent submissions."
  type        = string
}

variable "notification_from_email" {
  description = "SES sender used for volunteer intent admin notifications."
  type        = string
}

variable "notification_to_email" {
  description = "SES destination used for volunteer intent admin notifications."
  type        = string
}

variable "notification_reply_to_email" {
  description = "Reply-to email used for volunteer intent admin notifications."
  type        = string
}

variable "notification_logo_url" {
  description = "Public logo URL rendered in volunteer intent admin notifications."
  type        = string
}
