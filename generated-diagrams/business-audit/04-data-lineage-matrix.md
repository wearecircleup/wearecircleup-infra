# Data lineage matrix

| Data object | Producer | Where it is stored | Consumers | Key joins / indexes | Notes |
| --- | --- | --- | --- | --- | --- |
| Eventbrite order snapshot | `eventbrite_order_webhook` | Eventbrite order submissions table | Reminder lambda, audits | `pk=ORDER#{order_id}`, `sk=ORDER#{order_id}` | Contains event, venue, buyer and attendee context |
| Minor authorization job | `eventbrite_order_webhook` then validator | Minor authorization jobs table | Validator, YouForm webhook, reminder | `pk=EVENT#{event_id}`, `sk=ATTENDEE#{attendee_id}`, `gsi1` by status, `gsi2` by email | Central state machine for minors |
| Authorized minor submission | `youform_webhook` | YouForm minor submissions table | Minor validator lookups | `gsi2pk=EMAIL#{email}`, event id on item | Match requires email + event_id + exact form id |
| Volunteer proposal submission | `youform_webhook` | Volunteer proposal table | Staff email workflow | `gsi2` by email, `gsi3` by phone | Same webhook, different table and semantics |
| Background compliance submission | `youform_webhook` | Background submissions table | Background reviewer, internal review | Form and submission keys, email/phone GSIs | Also stores copied S3 URIs |
| Internal review payload | `youform_webhook` | Embedded in original background submission row | Human follow-up, audits | Hidden `partition_key` parsed from form | Not a separate service or queue |
| Signature or uploaded PDF | `youform_webhook` | S3 private buckets | Background reviewer or legal audit | Bucket key derived from form route + submission id | Original YouForm URL may remain if S3 copy fails |
| Background document review | `background_check_reviewer` | Background check reviews table | Same worker, admin notification | `gsi2pk=SUBMISSION#{submission_id}` | One row per document kind |
| Background final summary | `background_check_reviewer` | Stored onto cedula review row | Admin email, internal review form | `gsi4pk=PARTITION_KEY#{partition_key}` when available | Status is `PRE_APPROVED`, `REJECTED` or `PENDING_DOCUMENTS` |
| Volunteer proposal admin notification state | `youform_webhook` | Proposal table | Audits | Fields on same row | Tracks delivery outcome |
| Reminder history | `minor_authorization_reminder` | Minor jobs table | Audits, future support | List append on same row | Prevents invisible repeated reminders |
