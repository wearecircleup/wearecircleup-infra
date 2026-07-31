variable "api_name" {
  description = "API Gateway name."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "eventbrite_secret_arn" {
  description = "Secrets Manager ARN containing Eventbrite and API auth values."
  type        = string
}

variable "eventbrite_secret_name" {
  description = "Secrets Manager name containing Eventbrite and API auth values."
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

variable "service_name" {
  description = "Logical service name."
  type        = string
}
