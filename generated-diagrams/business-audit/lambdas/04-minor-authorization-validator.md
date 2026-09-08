# Lambda audit: minor_authorization_validator

## Role

Consumes one SQS message per detected minor attendee, materializes a job row and performs first-pass validation against stored YouForm submissions. Main code: [minor_authorization_validator/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | SQS event source mapping, batch size 1 |
| Input | Job body with event, attendee, buyer, venue and timestamp context |
| Output | Job row stored and status set to `authorized` or `missing_form` |

## Processing stages

| Stage | What it does | Code anchor |
| --- | --- | --- |
| Deduplicate | Checks whether `pk/sk` already exists in jobs table | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:126) |
| Build job row | Creates pending state and GSIs by status and email | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:81) |
| Query form submissions | Looks up YouForm submissions by email on `gsi2` | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:131) |
| Match auth form | Requires exact configured authorized form id and same Eventbrite event id | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:143) |
| Update final status | Writes `authorized` or `missing_form` | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_validator/lambda_handler.py:156) |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
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
| Malformed SQS body | Unhandled JSON error would fail message |
| Duplicate job | Safe skip |

## Observations

- This lambda is fairly cohesive.
- The interesting detail is that it only performs first-pass validation; later reconciliation can still happen from `youform_webhook`.
