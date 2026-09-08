# Component inventory

| Layer | Component | Type | Responsibility | Main dependencies | Main outputs |
| --- | --- | --- | --- | --- | --- |
| UI | Streamlit studio | User interface | Venue CRUD, event instantiation, image upload, publish, delete guardrail | `eventbrite_api` | Event creation requests, delete requests |
| API | `eventbrite_api` | API Gateway + Lambda + FastAPI | Circle Up facade over Eventbrite CRUD and publishing | Eventbrite API, Secrets Manager | Events, venues, attendance summaries, image upload orchestration |
| Ingress | `eventbrite_order_webhook` | API Gateway + Lambda | Normalize order webhooks and detect minors | Eventbrite API, DynamoDB, SQS | Order snapshots, minor auth jobs |
| Ingress | `youform_webhook` | API Gateway + Lambda | Route YouForm submissions by `form_id`, persist, reconcile and fan out | DynamoDB, S3, SES, SQS, Secrets Manager | Submission rows, copied files, emails, review jobs |
| Async | `minor_authorization_validator` | Lambda + SQS | Materialize one job per minor and validate if auth form already exists | Jobs table, YouForm table | Authorized or missing_form job state |
| Async | `minor_authorization_reminder` | EventBridge + Lambda | Daily follow-up for minors without form | Jobs table, order snapshot table, SES | Reminder emails and reminder history |
| Async | `background_check_reviewer` | Lambda + SQS | Review uploaded PDFs, build final status and notify ops | S3, reviews table, submissions table, Bedrock, Textract, SES | Review records, final summary, internal review email |
| Storage | Eventbrite order submissions | DynamoDB | Canonical order snapshot for webhook intake | `eventbrite_order_webhook` | Order, attendees, event and venue context |
| Storage | Minor authorization jobs | DynamoDB | Job ledger and status history for minors | `eventbrite_order_webhook`, `minor_authorization_validator`, `youform_webhook`, `minor_authorization_reminder` | Pending, authorized, missing_form, closed_order, event_passed |
| Storage | YouForm minor submissions | DynamoDB | Authorized minor form submissions | `youform_webhook` | Form answers, indexes by event and email |
| Storage | Volunteer proposal submissions | DynamoDB | Volunteer lead intake | `youform_webhook` | Proposal payload, admin notification status |
| Storage | Background check submissions | DynamoDB | Volunteer document intake plus embedded internal review | `youform_webhook`, `background_check_reviewer` | Submission metadata, copied file URIs, internal review |
| Storage | Background check reviews | DynamoDB | One row per reviewed document plus final summary on cedula row | `background_check_reviewer` | Validation results, summary, notification fingerprints |
| File store | YouForm signatures bucket | S3 | Preserve signature and legal minor files | `youform_webhook` | `s3://.../youform-signatures/...` |
| File store | Background check files bucket | S3 | Preserve volunteer PDFs copied from YouForm | `youform_webhook` | `s3://.../volunteer-background-checks/...`; files are expected to stay below `50 KB` |
| Messaging | Minor auth validation queue + DLQ | SQS | Buffer one validation job per minor | `eventbrite_order_webhook`, `minor_authorization_validator` | Async validation workload |
| Messaging | Background check review queue + DLQ | SQS | Buffer one review job per uploaded PDF | `youform_webhook`, `background_check_reviewer` | Async document review workload |
| Security/config | Shared Eventbrite secret | Secrets Manager | Eventbrite token plus form ids and shared config | Lambdas and API | Runtime secrets |
| Notifications | SES domain identity | SES | Outbound operational email | reminder, volunteer and background lambdas | Emails to participants and staff |
| AI/OCR | Bedrock and Textract | Managed services | Cedula extraction and certificate OCR | `background_check_reviewer` | Parsed document payloads |
