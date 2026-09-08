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

| Stage | What it does | Code anchor |
| --- | --- | --- |
| Form gate | Only processes jobs for configured background-check form id | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1196) |
| Document gate | Only accepts `cedula`, `antecedentes_judiciales`, `antecedentes_inhabilidades` | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1203) |
| Load source submission | Reads original submission row | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1118) |
| Download file | Pulls PDF from S3 | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:260) |
| Cedula path | Renders PDF pages, soft-cleans image, asks Bedrock to extract identity payload | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:265), [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:347) |
| Certificate path | Runs Textract OCR and stores text | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:398) |
| Validate | Applies document-specific validation and certificate-to-cedula cross-check | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:474), [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:567) |
| Store per-document review | Writes review row keyed by submission and document kind | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1125) |
| Finalize summary | Aggregates document states into `PRE_APPROVED`, `REJECTED` or `PENDING_DOCUMENTS` | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:637) |
| Notify ops | Sends internal review email when final state is terminal and fingerprint changed | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1043), [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/background_check_reviewer/lambda_handler.py:1069) |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Correct form id? | Message matches configured compliance form | Otherwise ignore |
| Supported document kind? | Kind is among three supported values | Otherwise ignore |
| Cedula path? | `document_kind == cedula` | Bedrock extraction path; otherwise Textract path |
| Can finalize summary? | Enough document state exists, especially a cedula row | Build summary on cedula review row |
| Notify ops? | Final status is `PRE_APPROVED` or `REJECTED` and fingerprint changed | Send internal review email |

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
| PDF cannot render | Raises and stores failed review item |
| Bedrock or Textract failure | Raises; failed review row persisted before message failure bubbles |
| Admin email failure | Failure state persisted on summary row |
| Missing secret/config | Lambda error |

## Observations

- This is the most domain-rich async lambda after `youform_webhook`.
- The key thing diagrams must show is aggregation: final approval is not decided by one document but by the combination of cedula + two certificates + summary rules.
- The main risk here is not oversized files; it is the amount of processing stages chained onto each small file.
