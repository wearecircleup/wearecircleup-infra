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

output "public_assets_bucket_name" {
  description = "Public S3 bucket name for Circle Up assets."
  value       = module.public_assets_s3.bucket_name
}

output "public_assets_base_url" {
  description = "Base URL for public Circle Up assets."
  value       = module.public_assets_s3.base_url
}

output "eventbrite_secret_arn" {
  description = "AWS Secrets Manager secret ARN for Eventbrite."
  value       = module.secretsmanager_eventbrite.secret_arn
}

output "eventbrite_secret_name" {
  description = "AWS Secrets Manager secret name for Eventbrite."
  value       = module.secretsmanager_eventbrite.secret_name
}

output "ses_domain_identity_arn" {
  description = "SES domain identity ARN."
  value       = module.ses_domain_identity.identity_arn
}

output "ses_domain_verification_record" {
  description = "DNS TXT record to copy into Hostinger for SES domain verification."
  value       = module.ses_domain_identity.verification_record
}

output "ses_domain_dkim_records" {
  description = "DNS CNAME records to copy into Hostinger for SES DKIM."
  value       = module.ses_domain_identity.dkim_records
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

output "minor_authorization_jobs_table_name" {
  description = "DynamoDB table name storing minor authorization validation jobs."
  value       = module.minor_authorization_jobs_dynamodb.table_name
}

output "minor_authorization_validator_lambda_function_name" {
  description = "Lambda function name consuming minor authorization validation jobs."
  value       = module.minor_authorization_validator.lambda_function_name
}

output "minor_authorization_validation_queue_name" {
  description = "SQS queue name receiving minor authorization validation jobs."
  value       = module.minor_authorization_validator.queue_name
}

output "minor_authorization_validation_queue_url" {
  description = "SQS queue URL receiving minor authorization validation jobs."
  value       = module.minor_authorization_validator.queue_url
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
