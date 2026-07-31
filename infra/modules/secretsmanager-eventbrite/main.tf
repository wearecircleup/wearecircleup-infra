resource "aws_secretsmanager_secret" "this" {
  name                    = var.secret_name
  description             = "Eventbrite secrets for the wearecircleup prod environment."
  recovery_window_in_days = 7

  tags = merge(var.common_tags, {
    Name    = var.secret_name
    Purpose = "eventbrite"
  })
}
