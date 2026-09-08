# Failure mode and business impact

| Failure mode | Technical symptom | Immediate business effect | Current containment | Residual risk |
| --- | --- | --- | --- | --- |
| Eventbrite webhook spoof or malformed trusted-looking payload | Order snapshot created from illegitimate POST | False minors, false jobs, noisy reminders | URL-shape validation only | High |
| YouForm webhook spoof with valid form id | Fake legal submission, fake volunteer lead or fake internal review | Wrong authorization state or corrupted volunteer history | Route and field-shape validation only | High |
| Delete endpoint called directly | Event removed despite registrations | Loss of intended cancellation-first procedure | UI discourages and blocks normal operator path | High |
| Queue config missing for minor jobs | Snapshot stored but minors not validated | Legal follow-up never starts | Logs only | Medium |
| Queue config missing for background reviews | Submission stored but PDFs never reviewed | Volunteer flow stalls silently | Logs only | Medium |
| File copy from YouForm to S3 fails | Original URL preserved instead of managed S3 URI | Later document access may depend on external file availability | Logs and graceful degradation | Medium |
| Event datetime parse fails in reminder | Job not recognized as expired | Stale reminders continue | Warning log | Medium |
| Event published outside API facade | Listing minor links never rewritten | Wrong or missing legal form link | None in system | Medium |
| Bedrock or Textract failure | Review item marked failed and SQS message fails | Volunteer approval delayed | Failure row plus retry through queue | Medium |
| Malformed background-review SQS payload | Worker receives invalid JSON or missing required fields | One bad job is discarded after failure record | Failed review row plus no retry for non-retryable input errors | Low |
| Malformed minor-validation SQS payload | Validator receives invalid JSON or missing required fields | One bad job is discarded without creating fake placeholder rows | Structured failure log plus no retry for non-retryable input errors | Low |
| Admin email failure in volunteer or background flow | Submission/review persists but no human sees it | Manual work waits invisibly unless logs reviewed | Status persisted on row | Medium |
