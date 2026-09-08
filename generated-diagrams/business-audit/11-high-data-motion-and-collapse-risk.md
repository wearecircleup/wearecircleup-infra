# High data motion and collapse risk

## Operational constraint

Por restriccion operativa conocida del negocio, los archivos y PDFs usados en estos flujos pesan casi siempre menos de `50 KB` y no se espera que lleguen ni siquiera a `0.5 MB`. En este sistema, por tanto, el riesgo no viene de archivos grandes sino de:

- varios pasos encadenados sobre un mismo payload,
- fetch + copia + persistencia + logging del mismo evento,
- fan-out a colas,
- y dependencia de servicios externos en serie.

| Flow | Main data in motion | Why it is heavy | Current guards | Collapse mode |
| --- | --- | --- | --- | --- |
| Eventbrite order webhook intake | Full order payload, full event payload, full venue payload, all attendees, normalized snapshot, one SQS message per minor | One webhook can trigger several external fetches, store a denormalized Dynamo row and log most of it | 30s Lambda timeout, 256 MB memory, queue fan-out only for minors | Timeout by chained upstream calls, CloudWatch log bloat, burst of minor jobs |
| YouForm background-check intake | Raw form body, copied PDF files, normalized answers, one SQS message per detected PDF | The files are small, but one submission can still copy multiple files from YouForm into S3 and then fan out review jobs | 30s Lambda timeout, 256 MB memory, queue decoupling | Slow ingress, retries on file fetch/copy, downstream queue backlog |
| Background-check review worker | Small PDF bytes, rendered PNG page images, Bedrock request payload, Textract OCR response, review rows, summary rows, SES notifications | File size is not the issue here; the real cost is read -> render -> AI/OCR -> summary -> notification in one worker path | 300s timeout, 1024 MB memory, SQS batch size 1, queue visibility 300s | Long-running worker, queue growth, repeated retries if one file consistently fails |
| Event attendance export and summary | Full attendee list across pages or four separate attendee count calls | These paths refetch Eventbrite data live, not from a local cache | API Lambda 60s timeout, 1024 MB memory | Slower studio experience, upstream rate or timeout sensitivity |
| Minor authorization reminder run | Full query of every `missing_form` job plus one order lookup per job and SES send | Work scales with unresolved backlog rather than fresh traffic | EventBridge scheduler, per-job state updates | Daily spike, longer runs as backlog grows, noisy reminders if state is stale |
| YouForm webhook global logging | Raw body, parsed body, stored item, file detections, review jobs and reconciliation result logged as JSON | Logging cost grows with payload size, not just business volume | None beyond CloudWatch defaults | Log volume bloat, sensitive data spread, slower invocations |
| Eventbrite webhook global logging | Raw order, attendees array, stored snapshot and parsed request logged | Logs nearly the same data that is already persisted | None beyond CloudWatch defaults | Log volume bloat, duplicated PII, slower invocations |

## Hot-path ranking

1. `background_check_reviewer`
2. `youform_webhook` when processing background-check forms
3. `eventbrite_order_webhook`
4. `minor_authorization_reminder`
5. `eventbrite_api` attendance/export paths

## Why these are the hottest

- They either move the same payload through many steps, render PDFs, paginate attendees, or duplicate payloads into logs and DynamoDB.
- They can amplify one user action into many downstream operations: multiple HTTP fetches, multiple SQS messages, multiple Dynamo writes, and SES notifications.
- In this system, their stress comes much more from orchestration density than from raw file size or user count.
