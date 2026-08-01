locals {
  aws_region             = "us-east-1"
  account_id             = "311923415472"
  repository             = "wearecircleup/wearecircleup-infra"
  github_actions_role    = "arn:aws:iam::311923415472:role/GitHubActionsDeployRole"
  state_bucket_name      = "wearecircleup-terraform-state-311923415472-us-east-1"
  validation_bucket_name = "wearecircleup-terraform-check-311923415472-us-east-1"
  eventbrite_secret_name = "wearecircleup/prod/eventbrite"
  eventbrite_api_name    = "wearecircleup-prod-eventbrite-api"
  eventbrite_api_lambda  = "wearecircleup-prod-eventbrite-api"
  eventbrite_api_role    = "wearecircleup-prod-eventbrite-api-role"
  youform_webhook_api    = "wearecircleup-prod-youform-webhook"
  youform_webhook_lambda = "wearecircleup-prod-youform-webhook"
  youform_webhook_role   = "wearecircleup-prod-youform-webhook-role"
  youform_webhook_path   = "/webhooks/youform"
  youform_webhook_table  = "wearecircleup-prod-youform-submissions"

  common_tags = {
    ManagedBy   = "terraform"
    Environment = "prod"
    Project     = "wearecircleup"
    Repository  = local.repository
  }
}
