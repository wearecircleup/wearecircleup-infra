# Business rule ownership

| Domain | Rule owner in code | Supporting components | Risk if owner changes silently |
| --- | --- | --- | --- |
| API access | `eventbrite_api` middleware | Streamlit token config, Secrets Manager | Medium |
| Event deletion policy | Streamlit delete page | Attendance summary endpoint | High |
| Event instantiation completeness | `EventInstantiationManager` | Eventbrite API client | Medium |
| Minor authorization detection | `eventbrite_order_webhook` | Eventbrite attendee answer text | Medium |
| Minor authorization matching | `minor_authorization_validator` and `youform_webhook` | YouForm tables, shared form id secret | High |
| Reminder lifecycle | `minor_authorization_reminder` | Jobs table, order snapshots, SES | Medium |
| YouForm route ownership | `youform_webhook` route config | Shared secret, table/bucket env vars | High |
| Volunteer-proposal notification policy | `youform_webhook` | SES, email allowlist | Low |
| Background document review policy | `background_check_reviewer` | S3, Bedrock, Textract, review tables | High |
| Internal review attachment | `youform_webhook` partition-key parser | Background submission row | High |

## Why this matters

This table is useful when a future refactor moves logic between UI, API and async workers. Several business rules do not live where a new engineer would expect:

- delete policy lives in Streamlit, not the API;
- legal-form matching is split between validator and YouForm ingress;
- internal-review attachment lives in a hidden form field contract;
- final volunteer status lives in the review aggregator, not in the intake webhook.
