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

module "youform_submissions_dynamodb" {
  source = "../modules/youform-submissions-dynamodb"

  table_name  = local.youform_webhook_table
  common_tags = local.common_tags
}

module "youform_webhook" {
  source = "../modules/youform-webhook"

  api_name               = local.youform_webhook_api
  common_tags            = local.common_tags
  lambda_function_name   = local.youform_webhook_lambda
  lambda_package_path    = abspath("${path.root}/../artifacts/youform-webhook/youform_webhook_lambda.zip")
  lambda_role_name       = local.youform_webhook_role
  route_path             = local.youform_webhook_path
  submissions_table_arn  = module.youform_submissions_dynamodb.table_arn
  submissions_table_name = module.youform_submissions_dynamodb.table_name
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
