import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.client import EventbriteAPIError, EventbriteClient
from app.config import Settings, get_settings
from app.exports import attendee_export
from app.instantiation import EventInstantiationManager
from app.schemas import (
    EventCreate,
    EventInstantiation,
    EventUpdate,
    ImageUploadCompletion,
    VenueCreate,
    VenueUpdate,
    personalize_minor_authorization_links,
)


logger = logging.getLogger(__name__)


def next_structured_content_version(structured_content: dict) -> int:
    for key in ("page_version_number", "version_number"):
        value = structured_content.get(key)
        if isinstance(value, int):
            return value + 1
        if isinstance(value, str) and value.isdigit():
            return int(value) + 1
    resource_uri = ((structured_content.get("resource_uris") or {}).get("self") or "").rstrip("/")
    match = resource_uri and resource_uri.split("/")[-1]
    if match and match.isdigit():
        return int(match) + 1
    return 2


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers={"Authorization": f"Bearer {settings.private_token}", "Accept": "application/json"},
        timeout=httpx.Timeout(30.0),
    ) as http_client:
        app.state.eventbrite = EventbriteClient(http_client, settings.organization_id)
        app.state.settings = settings
        yield


app = FastAPI(
    title="Eventbrite API",
    version="1.0.0",
    description="Eventbrite CRUD interface for Circle Up.",
    lifespan=lifespan,
)


def get_client(request: Request) -> EventbriteClient:
    return request.app.state.eventbrite


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return await call_next(request)
    if settings.api_auth_token:
        authorization = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.api_auth_token}"
        if authorization != expected:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Unauthorized"})
    return await call_next(request)


async def get_all_attendees(client: EventbriteClient, event_id: str) -> list[dict]:
    attendees: list[dict] = []
    page = 1
    while True:
        response = await client.list_attendees(event_id, {"page": page})
        attendees.extend(response.get("attendees", []))
        if not (response.get("pagination") or {}).get("has_more_items"):
            return attendees
        page += 1


async def attendee_count(client: EventbriteClient, event_id: str, status_filter: str | None = None) -> int:
    params: dict[str, int | str] = {"page": 1}
    if status_filter:
        params["status"] = status_filter
    response = await client.list_attendees(event_id, params)
    return int((response.get("pagination") or {}).get("object_count", 0))


@app.exception_handler(EventbriteAPIError)
async def eventbrite_error_handler(request: Request, exc: EventbriteAPIError) -> JSONResponse:
    logger.exception(
        "Eventbrite API error on %s %s: status=%s detail=%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/event-instantiations", status_code=status.HTTP_201_CREATED, tags=["instantiation"])
async def create_event_instantiation(
    payload: EventInstantiation,
    client: EventbriteClient = Depends(get_client),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    return await EventInstantiationManager(client, settings).create_and_validate(payload)


@app.post("/event-instantiations/{event_id}/publish", tags=["instantiation"])
async def publish_event_instantiation(event_id: str, client: EventbriteClient = Depends(get_client)) -> dict:
    await client.publish_event(event_id)
    published_event = await client.get_event(event_id, {"expand": "venue,ticket_classes,ticket_availability"})
    event_url = published_event.get("url")
    if isinstance(event_url, str) and event_url.strip():
        structured_content = await client.get_structured_content(event_id)
        updated_content = personalize_minor_authorization_links(structured_content, event_url.strip())
        if updated_content is not None:
            await client.create_structured_content(
                event_id,
                next_structured_content_version(structured_content),
                updated_content,
            )
            published_event = await client.get_event(event_id, {"expand": "venue,ticket_classes,ticket_availability"})
    return published_event


@app.get("/events/{event_id}/image/upload-request", tags=["images"])
async def image_upload_request(event_id: str, client: EventbriteClient = Depends(get_client)) -> dict:
    await client.get_event(event_id)
    return await client.image_upload_instructions()


@app.post("/events/{event_id}/image/upload-binary", status_code=status.HTTP_204_NO_CONTENT, tags=["images"])
async def upload_event_image_binary(
    event_id: str,
    upload_url: str = Form(),
    upload_data: str = Form(),
    file_parameter_name: str = Form(default="file"),
    image: UploadFile = File(),
    client: EventbriteClient = Depends(get_client),
) -> Response:
    await client.get_event(event_id)
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=422, detail="Image must be JPEG or PNG.")
    content = await image.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Image must be 10 MB or smaller.")
    try:
        fields = json.loads(upload_data)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="upload_data must be JSON.") from exc
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as upload_client:
        response = await upload_client.post(
            upload_url,
            data=fields,
            files={file_parameter_name: (image.filename or "event-image", content, image.content_type)},
        )
    if response.is_error:
        raise HTTPException(status_code=502, detail="The signed image upload was rejected.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/events/{event_id}/image/complete", tags=["images"])
async def complete_event_image_upload(
    event_id: str,
    payload: ImageUploadCompletion,
    client: EventbriteClient = Depends(get_client),
) -> dict:
    await client.get_event(event_id)
    image = await client.complete_image_upload(payload.upload_token, payload.crop_mask)
    # Completing media upload creates an Image resource; it does not by itself
    # mutate the Event. Associate its returned id as the event logo explicitly.
    image_id = image.get("id") or image.get("image_id")
    if not image_id:
        raise HTTPException(status_code=502, detail="Eventbrite completed the upload without returning an image id.")
    event = await client.update_event(event_id, {"logo_id": str(image_id)})
    return {"image": image, "event": event}


@app.get("/venues", tags=["venues"])
async def list_venues(
    page: int = Query(default=1, ge=1),
    client: EventbriteClient = Depends(get_client),
) -> dict:
    # Eventbrite accepts `page` for this endpoint but rejects `page_size`.
    # Its documented page size is already 50, so do not forward a parameter
    # that would turn a valid venue listing into a 400 response.
    return await client.list_venues({"page": page})


@app.get("/venues/{venue_id}", tags=["venues"])
async def get_venue(venue_id: str, client: EventbriteClient = Depends(get_client)) -> dict:
    return await client.get_venue(venue_id)


@app.post("/venues", status_code=status.HTTP_201_CREATED, tags=["venues"])
async def create_venue(
    payload: VenueCreate,
    client: EventbriteClient = Depends(get_client),
) -> dict:
    return await client.create_venue(payload.eventbrite_payload())


@app.patch("/venues/{venue_id}", tags=["venues"])
async def update_venue(
    venue_id: str, payload: VenueUpdate, client: EventbriteClient = Depends(get_client)
) -> dict:
    update = payload.eventbrite_payload()
    if not update:
        raise HTTPException(status_code=422, detail="Provide at least one field to update.")
    return await client.update_venue(venue_id, update)


@app.delete("/venues/{venue_id}", tags=["venues"])
async def delete_venue(
    venue_id: str,
    confirm: bool = Query(default=False, description="Must be true because deletion is permanent."),
) -> Response:
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to permanently delete this venue.")
    raise HTTPException(
        status_code=501,
        detail="Eventbrite's public API does not support deleting venues. Edit the venue or remove it manually in Eventbrite.",
    )


@app.get("/events", tags=["events"])
async def list_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=50),
    status_filter: str | None = Query(default=None, alias="status"),
    order_by: str = Query(default="start_asc"),
    client: EventbriteClient = Depends(get_client),
) -> dict:
    params = {"page": page, "page_size": page_size, "order_by": order_by}
    if status_filter:
        params["status"] = status_filter
    return await client.list_events(params)


@app.get("/events/{event_id}", tags=["events"])
async def get_event(event_id: str, client: EventbriteClient = Depends(get_client)) -> dict:
    return await client.get_event(event_id)


@app.get("/events/{event_id}/attendees", tags=["attendees"])
async def list_attendees(
    event_id: str,
    page: int = Query(default=1, ge=1),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Eventbrite status: attending, not_attending, or unpaid.",
    ),
    client: EventbriteClient = Depends(get_client),
) -> dict:
    params = {"page": page}
    if status_filter:
        params["status"] = status_filter
    return await client.list_attendees(event_id, params)


@app.get("/events/{event_id}/attendees/{attendee_id}", tags=["attendees"])
async def get_attendee(
    event_id: str, attendee_id: str, client: EventbriteClient = Depends(get_client)
) -> dict:
    return await client.get_attendee(event_id, attendee_id)


@app.get("/events/{event_id}/attendance", tags=["attendees"])
async def attendance_summary(event_id: str, client: EventbriteClient = Depends(get_client)) -> dict:
    total, checked_in, not_checked_in, unpaid = await asyncio.gather(
        attendee_count(client, event_id),
        attendee_count(client, event_id, "attending"),
        attendee_count(client, event_id, "not_attending"),
        attendee_count(client, event_id, "unpaid"),
    )
    return {
        "event_id": event_id,
        "registered": total,
        "checked_in": checked_in,
        "not_checked_in": not_checked_in,
        "unpaid": unpaid,
        "attendance_rate": round(checked_in / total, 4) if total else 0,
    }


@app.get("/events/{event_id}/export", tags=["attendees"])
async def export_attendees(event_id: str, client: EventbriteClient = Depends(get_client)) -> dict:
    event, attendees = await asyncio.gather(
        client.get_event(event_id), get_all_attendees(client, event_id)
    )
    return attendee_export(event, attendees)


@app.post("/events", status_code=status.HTTP_201_CREATED, tags=["events"])
async def create_event(
    payload: EventCreate,
    client: EventbriteClient = Depends(get_client),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    created_event = await client.create_event(payload.eventbrite_payload(settings.default_currency))
    event_id = created_event["id"]
    try:
        ticket = await client.create_free_ticket(event_id, payload.ticket_name, payload.ticket_quantity)
    except Exception:
        # An event without its required ticket must not be left behind as a
        # draft when the second step fails.
        try:
            await client.delete_event(event_id)
        except Exception:
            pass
        raise
    if not payload.publish:
        return {"event": created_event, "ticket": ticket, "published": False}
    await client.publish_event(event_id)
    # Eventbrite's publish response is not consistently a full Event object.
    published_event = await client.get_event(event_id)
    return {"event": published_event, "ticket": ticket, "published": True}


@app.patch("/events/{event_id}", tags=["events"])
async def update_event(event_id: str, payload: EventUpdate, client: EventbriteClient = Depends(get_client)) -> dict:
    update = payload.eventbrite_payload()
    if not update:
        raise HTTPException(status_code=422, detail="Provide at least one field to update.")
    return await client.update_event(event_id, update)


@app.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["events"])
async def delete_event(
    event_id: str,
    confirm: bool = Query(default=False, description="Must be true because deletion is permanent."),
    client: EventbriteClient = Depends(get_client),
) -> Response:
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to permanently delete this event.")
    logger.info("Deleting Eventbrite event %s", event_id)
    try:
        await client.delete_event(event_id)
    except EventbriteAPIError:
        logger.exception("Eventbrite rejected delete for event %s", event_id)
        raise
    except Exception:
        logger.exception("Unexpected delete failure for event %s", event_id)
        raise
    logger.info("Deleted Eventbrite event %s", event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
