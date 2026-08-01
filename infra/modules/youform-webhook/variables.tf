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
