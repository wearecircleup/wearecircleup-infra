# Lambda audit: background_check_reviewer

## Role

Consumes one SQS message per uploaded background-check PDF, reviews the document, stores per-document evidence, computes a final summary across documents and may notify ops with a link to an internal review form. Main code: [background_check_reviewer/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | SQS event source mapping, batch size 1 |
| Input | Job with `form_id`, `submission_id`, `document_kind`, S3 location and contact context |
| Engines | Bedrock for cedula extraction, Textract for certificates |
| Operational file-size assumption | The PDFs handled here are expected to stay below `50 KB` and effectively never reach `0.5 MB` |

## Processing stages

| Stage | What it does |
| --- | --- |
| Parse and validate record | Decodes the SQS body and rejects malformed or incomplete jobs |
| Form gate | Only processes jobs for the configured background-check form id |
| Document gate | Only accepts `cedula`, `antecedentes_judiciales` and `antecedentes_inhabilidades` |
| Load dependencies | Reads the source submission and downloads the PDF from S3 |
| Cedula path | Renders page images, lightly cleans them and sends them to Bedrock |
| Certificate path | Runs Textract OCR and stores normalized text |
| Validate | Applies document-specific rules and certificate-to-cedula cross-checks |
| Store review | Writes one review row keyed by submission and document kind |
| Finalize summary | Aggregates document states into `PRE_APPROVED`, `REJECTED` or `PENDING_DOCUMENTS` |
| Notify ops | Sends the internal-review email only when final state is terminal and fingerprint changed |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Correct form id? | Message matches configured compliance form | Otherwise ignore |
| Supported document kind? | Kind is among three supported values | Otherwise ignore |
| Cedula path? | `document_kind == cedula` | Bedrock extraction path; otherwise Textract path |
| Can finalize summary? | Enough document state exists, especially a cedula row | Build summary on cedula review row |
| Notify ops? | Final status is `PRE_APPROVED` or `REJECTED` and fingerprint changed | Send internal review email |
| Error retryable? | Infrastructure or extraction problem vs malformed job | Retry only the retryable failures |

## Data and side effects

| Item | Detail |
| --- | --- |
| Writes | Background check reviews table |
| Reads | Background submissions table, reviews table, S3 files, shared secret |
| Outbound | Bedrock, Textract, SES |
| Derived data | WhatsApp links, internal review prefill URL, final errors, resolved identity |

## Failure modes

| Failure mode | Current behavior |
| --- | --- |
| Invalid record body | Stores failed review item and acknowledges message |
| Missing required job field | Stores failed review item and acknowledges message |
| PDF cannot render | Raises and stores failed review item |
| Bedrock or Textract failure | Raises; failed review row persisted before message failure bubbles so SQS can retry |
| Admin email failure | Failure state persisted on summary row |
| Missing secret/config | Lambda error |

## Observations

- This is the most domain-rich async lambda after `youform_webhook`.
- The key thing diagrams must show is aggregation: final approval is not decided by one document but by the combination of cedula + two certificates + summary rules.
- The main risk here is not oversized files; it is the amount of processing stages chained onto each small file.
- The recent refactor made poison-message cases more explicit by separating non-retryable bad jobs from retryable service failures.
