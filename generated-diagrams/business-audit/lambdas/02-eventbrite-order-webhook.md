# Lambda audit: eventbrite_order_webhook

## Role

Receives Eventbrite order webhook payloads, fetches the authoritative order snapshot from Eventbrite, stores a normalized record and fans out one validation job per minor attendee. Main code: [eventbrite_order_webhook/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | API Gateway HTTP API route `POST /webhooks/eventbrite/order-place` |
| Input | JSON payload with `api_url` pointing at an Eventbrite order resource |
| Auth | No visible signature verification in handler |
| Output | `200` for success or skipped persistence, `400` invalid JSON, `500` for upstream, persistence or queue failures |

## Processing stages

| Stage | What it does |
| --- | --- |
| Parse webhook | Decodes base64 when needed and parses JSON into one webhook object |
| Resolve order URL | Accepts only supported Eventbrite order URLs and skips everything else |
| Fetch authoritative bundle | Calls Eventbrite for order, event, venue and attendees |
| Validate bundle shape | Confirms the fetched order bundle is internally consistent before storing |
| Build submission snapshot | Produces one normalized Dynamo item with buyer, attendees and webhook metadata |
| Detect minors | Scans attendee answers for the expected minor age-range string |
| Fan-out validation jobs | Sends one SQS message per minor attendee when queue config exists |

## Key decisions

| Decision | Condition | Yes branch | No branch |
| --- | --- | --- | --- |
| `api_url present?` | payload contains `api_url` | Continue | Skip persistence |
| `api_url supported?` | Host is Eventbrite API and path matches `/v3/orders/{id}` | Continue | Skip persistence |
| Bundle coherent? | Returned order id and payload shapes match expectations | Continue | Return `eventbrite_error` |
| `Minor detected?` | Age question answer matches configured minor answer | Create job(s) | Store snapshot only |
| `Queue configured?` | `AUTHORIZATION_QUEUE_URL` exists | Send SQS | Log skip |

## Data and side effects

| Item | Detail |
| --- | --- |
| Writes | Eventbrite order submissions table |
| Reads | Shared Eventbrite secret |
| Outbound | Eventbrite API reads, SQS `SendMessage` |
| Join keys emitted | `event_id`, `order_id`, `attendee_id`, `buyer_email`, `attendee_email` |

## Failure modes

| Failure mode | Current behavior |
| --- | --- |
| Invalid JSON | 400 |
| Missing `api_url` | 200 with `stored=false` and `reason=missing_api_url` |
| Unsupported `api_url` | 200 with `stored=false` and `reason=unsupported_api_url` |
| Eventbrite request error | 500 |
| Eventbrite bundle inconsistency | 500 as `eventbrite_error` |
| Missing submissions table env | 500 |
| Queue missing | Snapshot still stored; async minor path disabled and logged |

## Observations

- Good separation between ingestion and async validation.
- The handler is now internally modular without changing topology: parse, fetch bundle, build snapshot, persist, enqueue.
- Main audit gap: webhook trust is weak because I do not see a request-signature validation path.
