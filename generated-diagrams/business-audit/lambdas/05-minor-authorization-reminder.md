# Lambda audit: minor_authorization_reminder

## Role

Runs daily, finds minor-authorization jobs still unresolved, refreshes order state and sends reminder emails when the order is still active and the event has not passed. Main code: [minor_authorization_reminder/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | EventBridge schedule rule |
| Input | No meaningful payload required |
| Selection logic | Query jobs table `gsi1` where status is `missing_form` |

## Processing stages

| Stage | What it does | Code anchor |
| --- | --- | --- |
| Query unresolved jobs | Reads all `STATUS#missing_form` rows | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:45) |
| Refresh order state | Gets latest normalized order snapshot | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:94) |
| Order gate | Stops reminders when order status is not `placed` | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:454) |
| Time gate | Stops reminders when event datetime has passed in event timezone | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:73) |
| Build email | Builds Eventbrite URL and prefilled YouForm URL | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:226) |
| Send email | Uses SES | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:355) |
| Record reminder state | Updates counters, history, last status and optional closure reason | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/minor_authorization_reminder/lambda_handler.py:388) |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Order still placed? | Refreshed order status equals `placed` | Otherwise marks `closed_order` |
| Event passed? | Localized current time >= event datetime | Marks `event_passed` |
| Recipient email available? | Buyer or attendee email present | Otherwise records `skipped_missing_email` |
| SES success? | `send_email` succeeds | Append reminder history; otherwise record failure |

## Data and side effects

| Item | Detail |
| --- | --- |
| Writes | Minor authorization jobs table |
| Reads | Minor authorization jobs table, Eventbrite order submissions table |
| Outbound | SES email |

## Failure modes

| Failure mode | Current behavior |
| --- | --- |
| SES failure | Job row updated with `failed` reminder status |
| Bad event datetime | Warning logged; flow continues without considering event passed |
| Missing sender config | Lambda error |

## Observations

- This lambda acts like the retention loop for unresolved minor jobs.
- It is operationally valuable because it also cleans stale jobs when orders are no longer active.
