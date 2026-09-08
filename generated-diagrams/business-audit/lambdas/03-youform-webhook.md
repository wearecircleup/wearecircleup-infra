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

| Stage | What it does |
| --- | --- |
| Parse webhook | Handles base64 body and JSON parsing |
| Resolve route | Maps `form_id` into one configured storage and side-effect path |
| Detect internal review | Allows a special route only when the configured form id and hidden partition key both match |
| Detect file answers | Finds `files.youform.com` URLs before normalization |
| Normalize and copy files | Copies files to S3 when the route owns a bucket; if copy fails, preserves the original URL |
| Persist | Stores one submission row or updates the original background-check row for internal review |
| Dispatch follow-ups | Depending on route, reconciles minors, notifies staff, or dispatches background-review work |
| Log summary | Emits a compact structured summary instead of broad payload dumps |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Route known? | `form_id` exists in configured route table or valid internal-review payload | Otherwise skip persistence |
| Internal review? | Exact form id plus valid hidden partition key | Update original background submission row |
| File answer copy? | URL from `files.youform.com` and route has bucket | Copy file to S3; if copy fails, keep original URL |
| Reconcile minor auth? | Route says `reconcile_minor_authorization=True` | Sync invoke of minor processor |
| Volunteer admin notification? | Route says `admin_notification_type=volunteer_intent_proposal` | Async invoke of volunteer notifier |
| Background review processing? | Route says `background_check_processing=True` | Async invoke of background dispatcher |

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
| Invalid JSON | 400 as `invalid_payload` |
| Unknown `form_id` | Returns 200 with `stored=false` and `reason=unknown_form_route` |
| File copy failure | Logs error and keeps original file URL |
| Persistence failure | 500 as `storage_error` |
| Downstream invoke failure | 200 as `downstream_invoke_error`; the submission may already be stored |
| Missing event/email for minor reconciliation | Submission persists but the later match can still remain unresolved |

## Observations

- This lambda concentrates the most overlap in the system.
- It is still functional at your current scale, but one endpoint still hosts four business capabilities.
- The latest refactor reduced internal coupling without adding more infrastructure.
- The file-handling concern here is not big binaries; it is that one submission can still trigger copy, storage and multiple follow-up paths in one request.
