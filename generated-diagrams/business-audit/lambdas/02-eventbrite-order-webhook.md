# Lambda audit: eventbrite_order_webhook

## Role

Receives Eventbrite order webhook payloads, fetches the authoritative order snapshot from Eventbrite, stores a normalized record and fans out one validation job per minor attendee. Main code: [eventbrite_order_webhook/lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | API Gateway HTTP API route `POST /webhooks/eventbrite/order-place` |
| Input | JSON payload with `api_url` pointing at an Eventbrite order resource |
| Auth | No visible signature verification in handler |
| Output | `200` for success or skipped persistence, `400` invalid JSON, `500` processing failure |

## Processing stages

| Stage | What it does | Code anchor |
| --- | --- | --- |
| Parse body | Decodes base64 when needed and parses JSON | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:423) |
| Validate `api_url` | Requires field and requires Eventbrite order URL shape | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:333) |
| Fetch order | Calls Eventbrite API using private token from secret/env | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:348) |
| Fetch event and venue | Enriches order with event and venue context | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:362) |
| Fetch attendees | Walks pagination for all order attendees | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:153) |
| Normalize snapshot | Builds one Dynamo row with buyer, attendees, venue and webhook metadata | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:183) |
| Minor detection | Scans attendee answers for age range `14 a 17 anos` | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:231) |
| Fan-out | Sends one SQS message per minor if queue is configured | [lambda_handler.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_order_webhook/lambda_handler.py:283) |

## Key decisions

| Decision | Condition | Yes branch | No branch |
| --- | --- | --- | --- |
| `api_url present?` | payload contains `api_url` | Continue | Skip persistence |
| `api_url supported?` | Host is Eventbrite API and path matches `/v3/orders/{id}` | Continue | Skip persistence |
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
| Eventbrite request error | 500 |
| Missing submissions table env | 500 |
| Queue missing | Snapshot still stored; async minor path silently disabled except logs |

## Observations

- Good separation between ingestion and async validation.
- Main audit gap: webhook trust is weak because I do not see a request-signature validation path.
