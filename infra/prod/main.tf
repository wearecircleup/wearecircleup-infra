data "aws_caller_identity" "current" {}

module "s3_validation" {
  source = "../modules/s3-validation"

  bucket_name = local.validation_bucket_name
  common_tags = local.common_tags
}

module "secretsmanager_eventbrite" {
  source = "../modules/secretsmanager-eventbrite"

  secret_name = local.eventbrite_secret_name
  common_tags = local.common_tags
}

module "ses_domain_identity" {
  source = "../modules/ses-domain-identity"

  domain      = local.ses_domain
  common_tags = local.common_tags
}

module "eventbrite_api" {
  source = "../modules/eventbrite-api"

  api_name               = local.eventbrite_api_name
  common_tags            = local.common_tags
  eventbrite_secret_arn  = module.secretsmanager_eventbrite.secret_arn
  eventbrite_secret_name = module.secretsmanager_eventbrite.secret_name
  lambda_function_name   = local.eventbrite_api_lambda
  lambda_package_path    = abspath("${path.root}/../artifacts/eventbrite-api/eventbrite_api_lambda.zip")
  lambda_role_name       = local.eventbrite_api_role
  service_name           = "eventbrite-api"
}

module "eventbrite_order_submissions_dynamodb" {
  source = "../modules/eventbrite-order-submissions-dynamodb"

  table_name  = local.eventbrite_order_webhook_table
  common_tags = local.common_tags
}

module "minor_authorization_jobs_dynamodb" {
  source = "../modules/minor-authorization-jobs-dynamodb"

  table_name  = local.minor_authorization_jobs_table
  common_tags = local.common_tags
}

module "eventbrite_order_webhook" {
  source = "../modules/eventbrite-order-webhook"

  api_name                = local.eventbrite_order_webhook_api
  common_tags             = local.common_tags
  eventbrite_secret_arn   = module.secretsmanager_eventbrite.secret_arn
  eventbrite_secret_name  = module.secretsmanager_eventbrite.secret_name
  lambda_function_name    = local.eventbrite_order_webhook_lambda
  lambda_package_path     = abspath("${path.root}/../artifacts/eventbrite-order-webhook/eventbrite_order_webhook_lambda.zip")
  lambda_role_name        = local.eventbrite_order_webhook_role
  route_path              = local.eventbrite_order_webhook_path
  authorization_queue_arn = module.minor_authorization_validator.queue_arn
  authorization_queue_url = module.minor_authorization_validator.queue_url
  submissions_table_arn   = module.eventbrite_order_submissions_dynamodb.table_arn
  submissions_table_name  = module.eventbrite_order_submissions_dynamodb.table_name
}

module "youform_submissions_dynamodb" {
  source = "../modules/youform-submissions-dynamodb"

  table_name  = local.youform_webhook_table
  common_tags = local.common_tags
}

module "youform_signatures_s3" {
  source = "../modules/youform-signatures-s3"

  bucket_name = local.youform_signatures_bucket
  common_tags = local.common_tags
}

module "youform_webhook" {
  source = "../modules/youform-webhook"

  api_name                            = local.youform_webhook_api
  common_tags                         = local.common_tags
  lambda_function_name                = local.youform_webhook_lambda
  lambda_package_path                 = abspath("${path.root}/../artifacts/youform-webhook/youform_webhook_lambda.zip")
  lambda_role_name                    = local.youform_webhook_role
  route_path                          = local.youform_webhook_path
  signatures_bucket_arn               = module.youform_signatures_s3.bucket_arn
  signatures_bucket_name              = module.youform_signatures_s3.bucket_name
  submissions_table_arn               = module.youform_submissions_dynamodb.table_arn
  submissions_table_name              = module.youform_submissions_dynamodb.table_name
  minor_authorization_jobs_table_arn  = module.minor_authorization_jobs_dynamodb.table_arn
  minor_authorization_jobs_table_name = module.minor_authorization_jobs_dynamodb.table_name
}

module "minor_authorization_validator" {
  source = "../modules/minor-authorization-validator"

  common_tags                             = local.common_tags
  dlq_name                                = local.minor_authorization_validation_dlq
  eventbrite_order_submissions_table_arn  = module.eventbrite_order_submissions_dynamodb.table_arn
  eventbrite_order_submissions_table_name = module.eventbrite_order_submissions_dynamodb.table_name
  eventbrite_secret_arn                   = module.secretsmanager_eventbrite.secret_arn
  eventbrite_secret_name                  = module.secretsmanager_eventbrite.secret_name
  jobs_table_arn                          = module.minor_authorization_jobs_dynamodb.table_arn
  jobs_table_name                         = module.minor_authorization_jobs_dynamodb.table_name
  lambda_function_name                    = local.minor_authorization_validator_lambda
  lambda_package_path                     = abspath("${path.root}/../artifacts/minor-authorization-validator/minor_authorization_validator_lambda.zip")
  lambda_role_name                        = local.minor_authorization_validator_role
  queue_name                              = local.minor_authorization_validation_queue
  youform_submissions_table_arn           = module.youform_submissions_dynamodb.table_arn
  youform_submissions_table_name          = module.youform_submissions_dynamodb.table_name
}

module "minor_authorization_reminder" {
  source = "../modules/minor-authorization-reminder"

  common_tags                  = local.common_tags
  jobs_table_arn               = module.minor_authorization_jobs_dynamodb.table_arn
  jobs_table_name              = module.minor_authorization_jobs_dynamodb.table_name
  lambda_function_name         = local.minor_authorization_reminder_lambda
  lambda_package_path          = abspath("${path.root}/../artifacts/minor-authorization-reminder/minor_authorization_reminder_lambda.zip")
  lambda_role_name             = local.minor_authorization_reminder_role
  minor_authorization_form_url = local.minor_authorization_reminder_form
  reminder_from_email          = local.minor_authorization_reminder_sender
  reminder_reply_to_email      = local.minor_authorization_reminder_sender
  schedule_expression          = "cron(0 17 * * ? *)"
  schedule_name                = local.minor_authorization_reminder_rule
}

moved {
  from = aws_s3_bucket.validation
  to   = module.s3_validation.aws_s3_bucket.this
}

moved {
  from = aws_s3_bucket_versioning.validation
  to   = module.s3_validation.aws_s3_bucket_versioning.this
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.validation
  to   = module.s3_validation.aws_s3_bucket_server_side_encryption_configuration.this
}

moved {
  from = aws_s3_bucket_public_access_block.validation
  to   = module.s3_validation.aws_s3_bucket_public_access_block.this
}

moved {
  from = aws_secretsmanager_secret.eventbrite
  to   = module.secretsmanager_eventbrite.aws_secretsmanager_secret.this
}
