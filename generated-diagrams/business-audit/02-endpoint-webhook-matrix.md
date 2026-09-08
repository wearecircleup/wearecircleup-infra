# Endpoint and webhook matrix

| Entry point | Caller | Backend | Core behavior | Persistence | Side effects | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /venues` | Streamlit | `eventbrite_api` | List Eventbrite venues | None | None | Used for studio venue selector |
| `POST /venues` | Streamlit | `eventbrite_api` | Create venue in Eventbrite | None | None | No local venue DB |
| `PATCH /venues/{venue_id}` | Streamlit | `eventbrite_api` | Update venue in Eventbrite | None | None | No-op guarded if payload empty |
| `GET /events` | Streamlit | `eventbrite_api` | List events | None | None | Supports status filter |
| `POST /event-instantiations` | Streamlit | `eventbrite_api` | Create event, ticket buyer settings, ticket, questions and listing | None | Deletes partial draft on failure | This is a multi-step transaction without DB |
| `POST /event-instantiations/{id}/publish` | Streamlit | `eventbrite_api` | Publish event and rewrite listing links | None | Mutates structured content version | Adds personalized minor auth links |
| `GET /events/{id}/image/upload-request` | Streamlit | `eventbrite_api` | Request Eventbrite media upload instructions | None | None | Pre-step for binary upload |
| `POST /events/{id}/image/upload-binary` | Streamlit | `eventbrite_api` | Relay uploaded image to Eventbrite upload URL | None | Calls external signed upload URL | Validates file type and size |
| `POST /events/{id}/image/complete` | Streamlit | `eventbrite_api` | Complete upload and bind logo to event | None | Updates Eventbrite event | Associates `logo_id` explicitly |
| `GET /events/{id}/attendance` | Streamlit | `eventbrite_api` | Compute registered, checked-in, unpaid summary | None | 4 attendee count calls in parallel | Used as delete guardrail |
| `DELETE /events/{id}?confirm=true` | Streamlit or direct caller | `eventbrite_api` | Delete Eventbrite event | None | Hard delete in Eventbrite | API does not enforce "no registered attendees" rule |
| `POST /webhooks/eventbrite/order-place` | Eventbrite | `eventbrite_order_webhook` | Fetch order, event, venue, attendees and normalize snapshot | Order snapshot table | May enqueue minor auth jobs | Accepts any valid JSON body with supported `api_url` |
| `POST /webhooks/youform` for authorized minor form | YouForm | `youform_webhook` | Store submission, copy signature, maybe reconcile jobs | Minor form table | Reconcile matching jobs | Routing controlled by configured `form_id` |
| `POST /webhooks/youform` for volunteer proposal | YouForm | `youform_webhook` | Store proposal and extract contact fields | Proposal table | SES email to staff | Also stores WhatsApp-ready context |
| `POST /webhooks/youform` for background compliance | YouForm | `youform_webhook` | Store submission, copy PDFs and enqueue reviews | Background submissions table, S3 | One SQS message per supported PDF | Classification is by question/key text and file extension; files are operationally expected to stay below `50 KB` |
| `POST /webhooks/youform` for internal review form | YouForm | `youform_webhook` | Resolve hidden partition key and attach internal review | Background submissions table | None | Stored as sibling state on original submission |
| SQS `minor_authorization_validation` | Eventbrite order webhook | `minor_authorization_validator` | Deduplicate job, persist status and search matching form | Jobs table | None | Immediate validation plus future reconciliation path |
| EventBridge daily rule | AWS scheduler | `minor_authorization_reminder` | Query unresolved jobs and send reminders | Jobs table | SES email | Can close jobs if order is no longer placed |
| SQS `background_check_review` | YouForm webhook | `background_check_reviewer` | Review one PDF, persist result and maybe finalize summary | Reviews table | SES email to ops | Cedula uses Bedrock; certificates use Textract; the risk here is processing chain depth, not large file size |
