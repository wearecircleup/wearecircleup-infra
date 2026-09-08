# Decision matrix

| Flow | Decision | Condition in code | Yes branch | No branch | Effect |
| --- | --- | --- | --- | --- | --- |
| Eventbrite order webhook | `api_url present?` | webhook payload contains `api_url` | Continue fetch | Skip persistence | Webhook may return `ok` without storing |
| Eventbrite order webhook | `api_url supported?` | URL matches `eventbriteapi.com/v3/orders/{id}` | Continue | Skip persistence | Prevents arbitrary URL fetches outside expected path |
| Eventbrite order webhook | `Any minors?` | Attendee answer question equals age range `14 a 17 anos` | Build one job per minor | End | Only minors produce async work |
| Eventbrite order webhook | `Queue configured?` | `AUTHORIZATION_QUEUE_URL` exists | Send SQS messages | Log and continue | Snapshot can succeed while async path is disabled |
| Streamlit delete | `Registered > 0?` | Attendance summary `registered > 0` | Block UI delete | Ask for manual confirmation | Operational safety lives in UI |
| Streamlit delete | `Confirmation matches?` | Ack checkbox and exact event name match | Enable delete | Keep delete disabled | Prevent accidental clicks |
| Minor validator | `Job already exists?` | Same `pk/sk` already in jobs table | Skip duplicate record | Create pending job | Idempotency at job level |
| Minor validator | `Matching auth form exists now?` | Same email, same event, configured form id | Mark `authorized` | Mark `missing_form` | Immediate first-pass validation |
| YouForm router | `Known route?` | `form_id` configured or valid internal review form | Continue | Skip persistence | Router is config-driven |
| YouForm router | `Internal review payload?` | Exact internal review `form_id` plus valid hidden partition key | Update source submission | Treat as normal form routing | Internal review is special-cased |
| YouForm router | `Copy file answers?` | Answer URL matches `files.youform.com` and bucket exists | Download and store in S3 | Keep original URL | Partial degradation tolerated |
| YouForm router | `Reconcile minor job?` | Storage route for authorized minor form | Query jobs by email and event | Skip | Cross-system reconciliation |
| YouForm router | `Volunteer admin notification?` | Proposal route | Send SES email and persist status | Skip | Staff gets notified on proposal arrival |
| YouForm router | `Background review processing?` | Background check route | Build jobs per supported PDF | Skip | Fan-out into review queue |
| Background reviewer | `Configured form id?` | Message `form_id` matches configured compliance form | Continue | Ignore | Prevents mixed traffic in queue |
| Background reviewer | `Supported document kind?` | `cedula`, `antecedentes_judiciales`, `antecedentes_inhabilidades` | Continue | Ignore | Rejects unknown files |
| Background reviewer | `Cedula or certificate?` | `document_kind == cedula` | Render pages + Bedrock extraction | Textract OCR | Different engines by document type |
| Background reviewer | `Final summary possible?` | Enough review items exist, especially cedula | Build final summary | End with document review only | Summary depends on state across items |
| Background reviewer | `Notify ops?` | Final status is `PRE_APPROVED` or `REJECTED` and fingerprint changed | Send internal review email | Skip | Avoid duplicate notifications |
| Reminder | `Order still placed?` | Refreshed order status equals `placed` | Continue | Mark `closed_order` | Prevents reminders after cancellation/refund |
| Reminder | `Event passed?` | Current localized time >= event datetime | Mark `event_passed` | Continue | Stops stale reminders |
| Reminder | `Recipient email available?` | Buyer or attendee email present | Send email | Record `skipped_missing_email` | Missing contact becomes tracked state |
| Reminder | `SES succeeded?` | SES send does not raise | Record success and history | Record failure | Reminder loop is observable |
