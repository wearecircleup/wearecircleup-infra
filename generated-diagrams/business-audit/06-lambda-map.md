# Lambda map

| Lambda | Trigger | Primary role | Writes | Outbound calls | Audit sheet |
| --- | --- | --- | --- | --- | --- |
| `eventbrite_api` | API Gateway HTTP API | Circle Up facade for Eventbrite CRUD and publishing workflows | None | Eventbrite API | [01-eventbrite-api.md](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/business-audit/lambdas/01-eventbrite-api.md:1) |
| `eventbrite_order_webhook` | API Gateway webhook | Normalize Eventbrite order events and detect minors | Order snapshot table | Eventbrite API, SQS | [02-eventbrite-order-webhook.md](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/business-audit/lambdas/02-eventbrite-order-webhook.md:1) |
| `youform_webhook` | API Gateway webhook | Route YouForm forms into storage, reconciliation, email and review fan-out | Three DynamoDB submission domains | S3, SES, SQS | [03-youform-webhook.md](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/business-audit/lambdas/03-youform-webhook.md:1) |
| `minor_authorization_validator` | SQS | Materialize and validate one job per minor | Jobs table | DynamoDB queries only | [04-minor-authorization-validator.md](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/business-audit/lambdas/04-minor-authorization-validator.md:1) |
| `minor_authorization_reminder` | EventBridge schedule | Revisit unresolved minor jobs and email reminders | Jobs table | DynamoDB lookups, SES | [05-minor-authorization-reminder.md](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/business-audit/lambdas/05-minor-authorization-reminder.md:1) |
| `background_check_reviewer` | SQS | Review uploaded PDFs, aggregate status and notify ops | Reviews table | S3, Bedrock, Textract, SES | [06-background-check-reviewer.md](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/business-audit/lambdas/06-background-check-reviewer.md:1) |
