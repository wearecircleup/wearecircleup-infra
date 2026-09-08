# Lambda audit: minor_authorization_validator

## Role

Consumes one SQS message per detected minor attendee, materializes a job row and performs first-pass validation against stored YouForm submissions. Main code: [minor_authorization_validator/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | SQS event source mapping, batch size 1 |
| Input | Job body with event, attendee, buyer, venue and timestamp context |
| Output | Job row stored and status set to `authorized` or `missing_form`, or non-retryable bad messages acknowledged as failed |

## Processing stages

| Stage | What it does |
| --- | --- |
| Parse record | Decodes the SQS body into one job object |
| Validate minimal identity | Requires at least `event_id` and `attendee_id` before any write |
| Deduplicate | Checks whether the `EVENT#{event_id}` and `ATTENDEE#{attendee_id}` pair already exists |
| Build pending row | Creates the pending job state and GSIs by status and email |
| Query submissions | Looks up candidate YouForm rows by normalized email |
| Match authorized form | Requires exact configured authorized form id plus same Eventbrite event id |
| Finalize first-pass status | Writes `authorized` or `missing_form` |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Record body valid? | SQS body parses to a JSON object | Otherwise record a non-retryable failed result |
| Required keys present? | `event_id` and `attendee_id` exist | Otherwise do not store an `UNKNOWN_*` job row |
| Duplicate message? | Same `EVENT#{event_id}` + `ATTENDEE#{attendee_id}` already exists | Skip second write |
| Email available? | Attendee email or buyer email present | Enables lookup; otherwise will end as no match |
| Matching authorized form exists? | Same email, same event, same configured form id | Mark job `authorized`; else `missing_form` |

## Data and side effects

| Item | Detail |
| --- | --- |
| Writes | Minor authorization jobs table |
| Reads | Jobs table, YouForm submissions table, shared secret for form id |
| Outbound | No external HTTP; only DynamoDB |

## Failure modes

| Failure mode | Current behavior |
| --- | --- |
| Missing table env vars | Lambda error |
| Secret missing authorized form id | Lambda error |
| Malformed SQS body | Logged as non-retryable failed result and acknowledged |
| Missing `event_id` or `attendee_id` | Logged as non-retryable failed result; no job row is created |
| Duplicate job | Safe skip |

## Observations

- This lambda is fairly cohesive.
- The recent refactor removed the path where bad messages could materialize placeholder `UNKNOWN_*` records.
- The interesting detail is that it only performs first-pass validation; later reconciliation can still happen from `youform_webhook`.
