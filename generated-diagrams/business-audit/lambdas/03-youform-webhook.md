# Lambda audit: youform_webhook

## Role

This is the densest lambda in the system. It is a config-driven router for multiple YouForm domains: minor authorization intake, volunteer proposal intake, volunteer background-check intake and internal review attachment. Main code: [youform_webhook/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | API Gateway HTTP API route `POST /webhooks/youform` |
| Input | YouForm submission payload |
| Auth | No visible signature verification in handler |
| Routing key | `form_id`, plus hidden `Partition key` answer for internal review |
| Operational file-size assumption | Attached files are expected to stay below `50 KB` and not reach `0.5 MB` |

## Routing modes

| Route | Storage target | Extra behavior |
| --- | --- | --- |
| Authorized minor form | Minor auth submissions table | Copies signature to S3 and reconciles minor jobs |
| Volunteer proposal form | Volunteer proposal submissions table | Sends admin email via SES |
| Background compliance form | Background submissions table | Copies PDFs to S3 and enqueues review jobs |
| Internal review form | Updates original background submission row | No new queue; attaches `internal_review` payload |

## Processing stages

| Stage | What it does | Code anchor |
| --- | --- | --- |
| Parse and decode | Handles base64 body and JSON parsing | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:1270) |
| Resolve route | Maps `form_id` to storage config from secret/env | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:148) |
| Internal review detection | Requires exact internal-review form id and a valid hidden partition key | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:243) |
| File detection | Detects `files.youform.com` URLs | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:323) |
| File copy to S3 | Downloads remote file and stores in configured bucket/prefix | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:369) |
| Build keyed item | Generates different PK/GSI patterns by route | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:732) |
| Persist submission | Writes normalized row or updates internal review | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:1250) |
| Reconcile minor jobs | Queries jobs by email and event, then marks authorized | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:1161) |
| Notify staff | Sends volunteer proposal email and records result | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:1108) |
| Enqueue background review | Classifies stored PDFs and sends one SQS message per supported document | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/youform_webhook/lambda_handler.py:476) |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Route known? | `form_id` exists in configured route table or valid internal-review payload | Otherwise skip persistence |
| Internal review? | Exact form id plus valid hidden partition key | Update original background submission row |
| File answer copy? | URL from `files.youform.com` and route has bucket | Copy file to S3; if copy fails, keep original URL |
| Reconcile minor auth? | Route says `reconcile_minor_authorization=True` | Query jobs table and mark matching jobs authorized |
| Volunteer admin notification? | Route says `admin_notification_type=volunteer_intent_proposal` | Send SES email and persist status |
| Background review processing? | Route says `background_check_processing=True` and document kind recognized | Enqueue review jobs |

## Data and side effects

| Item | Detail |
| --- | --- |
| Writes | Minor auth submissions table, volunteer proposal submissions table, background submissions table |
| Updates | Existing background submission row for internal review; jobs table for minor reconciliation |
| Reads | Shared secret, jobs table |
| Outbound | S3 `PutObject`, SES `SendEmail`, SQS `SendMessage`, HTTP GET to `files.youform.com` |

## Failure modes

| Failure mode | Current behavior |
| --- | --- |
| Unknown `form_id` | Returns 200 and skips persistence |
| File copy failure | Logs error and keeps original file URL |
| Volunteer email failure | Stores failure state but keeps submission |
| Background queue missing | Submission can persist without review fan-out |
| Missing event/email for minor reconciliation | Submission persists but job remains unresolved |

## Observations

- This lambda concentrates the most overlap in the system.
- It is still functional at your current scale, but from an audit perspective it needs the most documentation because one endpoint hosts four business capabilities.
- The file-handling concern here is not big binaries; it is that one submission can still trigger copy, storage, queue fan-out and notification work in a single request path.
