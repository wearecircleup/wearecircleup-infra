output "aws_account_id" {
  description = "AWS account used by Terraform."
  value       = data.aws_caller_identity.current.account_id
}

output "github_actions_role_arn" {
  description = "IAM role assumed by GitHub Actions."
  value       = local.github_actions_role
}

output "terraform_state_bucket_name" {
  description = "Remote backend bucket used for Terraform state."
  value       = local.state_bucket_name
}

output "validation_bucket_name" {
  description = "Validation bucket created by the main stack."
  value       = module.s3_validation.bucket_name
}

output "eventbrite_secret_arn" {
  description = "AWS Secrets Manager secret ARN for Eventbrite."
  value       = module.secretsmanager_eventbrite.secret_arn
}

output "eventbrite_secret_name" {
  description = "AWS Secrets Manager secret name for Eventbrite."
  value       = module.secretsmanager_eventbrite.secret_name
}

output "eventbrite_api_endpoint" {
  description = "HTTP API endpoint for the Eventbrite API."
  value       = module.eventbrite_api.api_endpoint
}

output "eventbrite_api_lambda_function_name" {
  description = "Lambda function name serving the Eventbrite API."
  value       = module.eventbrite_api.lambda_function_name
}

output "eventbrite_order_webhook_lambda_function_name" {
  description = "Lambda function name receiving Eventbrite order webhooks."
  value       = module.eventbrite_order_webhook.lambda_function_name
}

output "eventbrite_order_webhook_api_endpoint" {
  description = "Base HTTP API endpoint for the Eventbrite order webhook receiver."
  value       = module.eventbrite_order_webhook.api_endpoint
}

output "eventbrite_order_webhook_url" {
  description = "Full webhook URL to configure in Eventbrite for Order Place."
  value       = module.eventbrite_order_webhook.webhook_url
}

output "eventbrite_order_webhook_submissions_table_name" {
  description = "DynamoDB table name storing normalized Eventbrite order submissions."
  value       = module.eventbrite_order_submissions_dynamodb.table_name
}

output "youform_webhook_lambda_function_name" {
  description = "Lambda function name receiving YouForm submissions."
  value       = module.youform_webhook.lambda_function_name
}

output "youform_webhook_api_endpoint" {
  description = "Base HTTP API endpoint for the YouForm webhook receiver."
  value       = module.youform_webhook.api_endpoint
}

output "youform_webhook_url" {
  description = "Full webhook URL to configure in YouForm."
  value       = module.youform_webhook.webhook_url
}

output "youform_webhook_submissions_table_name" {
  description = "DynamoDB table name storing normalized YouForm submissions."
  value       = module.youform_submissions_dynamodb.table_name
}

output "youform_signatures_bucket_name" {
  description = "Private S3 bucket name storing copied YouForm signatures."
  value       = module.youform_signatures_s3.bucket_name
}
