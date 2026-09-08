# Lambda audit: eventbrite_api

## Role

API facade for Circle Up studio over Eventbrite. It centralizes venue CRUD, event creation, event instantiation, publication, image upload and attendance summary logic. Main code: [eventbrite_api/app/main.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_api/app/main.py:1), [eventbrite_api/app/instantiation.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_api/app/instantiation.py:1), [eventbrite_api/app/client.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_api/app/client.py:1).

## Trigger and boundary

| Item | Detail |
| --- | --- |
| Trigger | API Gateway HTTP API with `ANY /` and `ANY /{proxy+}` routed into Mangum |
| Auth | Bearer token enforced in FastAPI middleware, not in API Gateway |
| State | Stateless; no local DB writes |
| Main caller | Streamlit studio via [studio_api.py](C:/Users/gocir/Documents/wearecircleup-streamlit/studio_api.py:14) |

## Endpoints and behavior

| Endpoint | Core behavior | Important internal logic |
| --- | --- | --- |
| `GET /health` | Health check | No auth |
| `POST /event-instantiations` | Create event instantiation | Creates event, buyer settings, ticket, questions and structured content; deletes draft on partial failure |
| `POST /event-instantiations/{id}/publish` | Publish event | Publishes, reloads event, personalizes minor auth links in listing content, creates next structured content version |
| `GET /events/{id}/image/upload-request` | Request upload metadata | Confirms event exists first |
| `POST /events/{id}/image/upload-binary` | Relay image upload | Validates JPEG/PNG and size <= 10 MB; POSTs binary to external upload URL |
| `POST /events/{id}/image/complete` | Finalize image | Completes upload and updates event `logo_id` explicitly |
| `GET /venues`, `GET /venues/{id}`, `POST /venues`, `PATCH /venues/{id}` | Venue facade | Rejects empty patch payload |
| `DELETE /venues/{id}` | Permanent delete attempt | Always returns 501 because Eventbrite public API does not support venue delete |
| `GET /events`, `GET /events/{id}` | Event reads | Simple Eventbrite pass-through |
| `GET /events/{id}/attendees`, `GET /events/{id}/attendees/{attendee_id}` | Attendee reads | Simple pass-through |
| `GET /events/{id}/attendance` | Attendance summary | Runs four attendee counts in parallel |
| `GET /events/{id}/export` | Export attendees | Loads all attendees across pages |
| `POST /events` | Basic event create | Creates event + free ticket, optionally publishes; deletes event if ticket step fails |
| `PATCH /events/{id}` | Event update | Rejects empty patch payload |
| `DELETE /events/{id}` | Hard delete | Requires `confirm=true`, then deletes event directly |

## Key decisions

| Decision | Condition | Effect |
| --- | --- | --- |
| Require auth? | Any path except `/health` and token configured | Return 401 if bearer token mismatch |
| Publish listing rewrite? | Published event returns URL | Rewrites listing with personalized minor form links |
| Accept image? | Content type must be JPEG or PNG and size <= 10 MB | Otherwise 422 |
| Roll back instantiation? | Any step after event creation fails | Deletes partial Eventbrite draft |
| Allow event delete? | Only `confirm=true` checked | Backend does not inspect attendance before delete |

## Reads, writes and calls

| Type | Uses |
| --- | --- |
| Reads | Secrets Manager via settings bootstrap |
| Writes | None in AWS storage owned by this repo |
| Outbound HTTP | Eventbrite API for all CRUD; signed Eventbrite media upload URL for binary image upload |

## Failure modes

| Failure mode | Current behavior |
| --- | --- |
| Eventbrite error | Converted to `EventbriteAPIError`, logged and returned with status code |
| Image upload rejected by signed URL | Returns 502 |
| Event create partially succeeds | Best-effort deletion of created draft |
| Unauthorized API access | 401 from middleware |

## Observations

- Strong operational value: it gives Streamlit one stable API surface.
- Main debt: delete guardrail is enforced in Streamlit, not here, so direct callers can bypass the no-attendee rule. See [delete_events.py](C:/Users/gocir/Documents/wearecircleup-streamlit/delete_events.py:158) and [eventbrite_api/app/main.py](C:/Users/gocir/Documents/wearecircleup-infra/eventbrite_api/app/main.py:376).
