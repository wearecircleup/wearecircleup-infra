variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "jobs_table_arn" {
  description = "DynamoDB table ARN storing minor authorization jobs."
  type        = string
}

variable "jobs_table_name" {
  description = "DynamoDB table name storing minor authorization jobs."
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
  default     = 60
}

variable "minor_authorization_form_url" {
  description = "URL to the minor authorization form."
  type        = string
}

variable "reminder_from_email" {
  description = "SES sender email used for reminders."
  type        = string
}

variable "reminder_hero_image_url" {
  description = "Public image URL rendered at the top of reminder emails."
  type        = string
  default     = ""
}

variable "reminder_reply_to_email" {
  description = "Reply-to email used for reminders."
  type        = string
}

variable "reminder_subject_prefix" {
  description = "Subject prefix for reminder emails."
  type        = string
  default     = "Pendiente autorización para menor de edad"
}

variable "schedule_expression" {
  description = "Schedule expression for the reminder Lambda."
  type        = string
}

variable "schedule_name" {
  description = "Name of the EventBridge schedule rule."
  type        = string
}
