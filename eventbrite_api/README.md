# Eventbrite API

FastAPI service for creating, listing, reading, updating and deleting Eventbrite events. Its interactive test interface is at `/docs`.

The same codebase supports local development with `.env` and AWS deployment through Lambda + API Gateway.

## Operating Contract

For the controlled Circle Up event-creation process, use
`event_instantiation_input.template.json` together with
`EVENTBRITE_INSTANTIATION_STRATEGY.md`. The JSON contains only API request
attributes for the simplified draft request, including a single `overview`
field for the body shown in Eventbrite's native Overview. In this simplified
flow, no separate public summary is sent; the strategy contains the
required human checks, endpoint order, image workflow, default FAQs,
validation and delete/recreate policy.

The normal operating path is **create draft -> validate -> publish**. If an
event is wrong, delete it and create a corrected replacement rather than using
`PATCH`. The patch endpoint remains available for exceptional manual recovery,
not as the standard event-instantiation workflow.

## Endpoints

- `GET /venues`: paginated venue list.
- `GET /venues/{venue_id}`: venue detail.
- `POST /venues`: creates a venue.
- `PATCH /venues/{venue_id}`: updates supplied venue fields.
- `DELETE /venues/{venue_id}?confirm=true`: intentionally returns `501` because Eventbrite's public API does not support venue deletion.
- `GET /events`: paginated list.
- `GET /events/{event_id}`: detail.
- `POST /events`: creates an event, creates a free ticket, then publishes it by default.
- `PATCH /events/{event_id}`: updates supplied fields.
- `DELETE /events/{event_id}?confirm=true`: deletes an event. A subsequent read can surface either a readable record with status `deleted` or an eventual-consistency `404`; clients should treat both as a successful delete outcome.
- `GET /events/{event_id}/attendees`: paginated attendee list, including Eventbrite answers and check-in state.
- `GET /events/{event_id}/attendees/{attendee_id}`: attendee detail, including barcode and check-in status from Eventbrite.
- `GET /events/{event_id}/attendance`: registered, checked-in, not checked-in, unpaid and attendance rate.
- `GET /events/{event_id}/export`: normalized JSON export for later DynamoDB ingestion. It intentionally excludes barcodes.
- `GET /health`: health endpoint.
- `POST /event-instantiations`: creates a draft, ticket, default questions and listing content, then validates it. It never publishes.
- `POST /event-instantiations/{event_id}/publish`: publishes a previously validated draft.
- `GET /events/{event_id}/image/upload-request`, `POST /events/{event_id}/image/upload-binary`, `POST /events/{event_id}/image/complete`: the three signed Eventbrite image-upload steps.

## Images And Recurrence

Recurring schedules are **not implemented yet**. Create each date as a normal
event through the instantiation flow.

### Event image

The Studio uses the three local image endpoints after draft creation. Prepare a
JPEG or PNG no larger than 10 MB; the Studio normalizes it to 2:1 before the
upload and sends that crop mask in the completion step.

### Recurring workshops

Proposed endpoint: `POST /events/{event_id}/schedule` with a list of future
start/end date pairs. It will create Eventbrite occurrences under a series
parent. Use this only for the same workshop repeated at different times;
each occurrence has its own attendee list and ticket inventory.

For now, create each date as a normal event through `POST /events`.

## Setup With uv

```powershell
cd eventbrite_api
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000/docs>. The API uses exported variables first, then the root `../.env.local`, then `./.env`. Copy `.env.example` to `.env` only if you want a self-contained local configuration.

For faster local work, you can also keep service-only credentials in `eventbrite_api/.env.local`.
Set `EVENTBRITE_RUNTIME_MODE=local` there to skip AWS Secrets Manager entirely and rely only on exported variables plus local env files.

`uv sync` creates and maintains `.venv` from `pyproject.toml` and the locked dependency graph in `uv.lock`. Do not use `pip`, manual virtual-environment activation, or `requirements.txt` for this API.

If this machine blocks access to uv's global cache or managed Python folders, point both into the repo before running commands:

```powershell
$env:UV_CACHE_DIR = "..\\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "..\\.uv-python"
```

`EVENTBRITE_DEFAULT_CURRENCY` defaults to `USD`, which Eventbrite accepts for
this organization. A live validation on 2026-07-28 confirmed that `COP` is
currently rejected by Eventbrite for this organization as `event.currency:
INVALID`. Do not override it until Eventbrite enables COP for the account.

## Create request

Use this body in `POST /events` at `/docs`:

```json
{
  "name": "Taller de prueba Circle Up",
  "start": "2026-07-27T10:00:00-05:00",
  "end": "2026-07-27T11:00:00-05:00",
  "timezone": "America/Bogota",
  "ticket_quantity": 100,
  "publish": true
}
```

Dates must include their UTC offset. `POST /events` has real side effects: it creates and publishes an Eventbrite event. Set `publish` to `false` only when you explicitly need a draft.

## Tests

```powershell
$env:EVENTBRITE_RUNTIME_MODE = "local"
uv run pytest
```

The default suite is network-free and automatically excludes the live Eventbrite
tests unless their opt-in environment variables are set. To validate every
endpoint against Eventbrite, run the integration test below. It creates and
publishes one temporary event, then deletes it after checking create, read and
update operations.

```powershell
$env:EVENTBRITE_LIVE_TEST = "1"
uv run pytest -m live
Remove-Item Env:EVENTBRITE_LIVE_TEST
```

If you are working on a locked-down Windows machine, keep uv fully inside the
repo before the first run:

```powershell
$env:UV_CACHE_DIR = "..\\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "..\\.uv-python"
$env:EVENTBRITE_RUNTIME_MODE = "local"
uv run pytest -m "not live"
```

Add mocked HTTPX tests before expanding the API or running bulk changes.

## AWS deployment

The cloud deployment reads these values from AWS Secrets Manager:

- `EVENTBRITE_PRIVATE_TOKEN`
- `EVENTBRITE_ORGANIZATION_ID`
- `EVENTBRITE_API_AUTH_TOKEN`

The Lambda environment must provide:

- `EVENTBRITE_SECRET_ID`
- `EVENTBRITE_DEFAULT_CURRENCY` (optional, defaults to `USD`)

### Real attendee notification check

Eventbrite creates attendees through its public checkout, not through a public
API endpoint. For a real notification scenario, publish a disposable test
event, complete checkout once with each test account, then verify that the API
can read both registrations without modifying check-in state:

```powershell
$env:EVENTBRITE_LIVE_ATTENDEE_TEST = "1"
$env:EVENTBRITE_ATTENDEE_EVENT_ID = "your-published-test-event-id"
uv run pytest tests/test_live_attendees.py -m live
Remove-Item Env:EVENTBRITE_LIVE_ATTENDEE_TEST
Remove-Item Env:EVENTBRITE_ATTENDEE_EVENT_ID
```
