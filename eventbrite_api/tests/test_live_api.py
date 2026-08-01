"""Opt-in end-to-end coverage for every FastAPI endpoint.

Run only with EVENTBRITE_LIVE_TEST=1. It creates a published event and deletes
that same event in a finally block.
"""

import json
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


pytestmark = pytest.mark.live


def assert_event_removed_or_marked_deleted(client: TestClient, event_id: str) -> None:
    """Eventbrite can expose a just-deleted event as deleted or as missing."""
    last_response = None
    for _ in range(5):
        response = client.get(f"/events/{event_id}")
        if response.status_code == 404:
            return
        if response.status_code == 200 and response.json().get("status") == "deleted":
            return
        last_response = response
        time.sleep(0.5)
    assert last_response is not None
    pytest.fail(
        f"Expected Eventbrite to expose deleted event {event_id} as missing or deleted, "
        f"got {last_response.status_code}: {last_response.text}"
    )


def test_full_eventbrite_crud_lifecycle() -> None:
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(hours=1)
    event_id: str | None = None

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert "/events" in openapi.json()["paths"]
        assert client.get("/events", params={"page": 1, "page_size": 1}).status_code == 200

        try:
            created = client.post(
                "/events",
                json={
                    "name": f"API verification {start.date().isoformat()}",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "timezone": "America/Bogota",
                    "description": "Temporary automated API verification event.",
                    "ticket_name": "Verification ticket",
                    "ticket_quantity": 1,
                    "publish": True,
                },
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["published"] is True
            event_id = str(body["event"]["id"])

            assert client.get(f"/events/{event_id}").status_code == 200
            attendees = client.get(f"/events/{event_id}/attendees")
            assert attendees.status_code == 200, attendees.text
            assert "attendees" in attendees.json()
            missing_attendee = client.get(f"/events/{event_id}/attendees/not-a-real-attendee")
            assert missing_attendee.status_code == 404, missing_attendee.text
            assert client.get(f"/events/{event_id}/attendance").status_code == 200
            exported = client.get(f"/events/{event_id}/export")
            assert exported.status_code == 200, exported.text
            assert exported.json()["event"]["id"] == event_id

            updated = client.patch(
                f"/events/{event_id}",
                json={"summary": "Verified through the local FastAPI CRUD test."},
            )
            assert updated.status_code == 200, updated.text
        finally:
            if event_id:
                deleted = client.delete(f"/events/{event_id}", params={"confirm": "true"})
                assert deleted.status_code == 204, deleted.text

        assert_event_removed_or_marked_deleted(client, event_id)


def test_controlled_instantiation_content_questions_and_image_lifecycle() -> None:
    """Validate the simplified Studio payload and image flow against Eventbrite."""
    start = (datetime.now(timezone.utc) + timedelta(days=4)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(hours=1)
    event_id: str | None = None
    image_path = Path(__file__).with_name("help-carrusel-2.png")
    image_bytes = image_path.read_bytes()
    width, height = struct.unpack(">II", image_bytes[16:24])
    crop_height = width // 2
    crop_top = max(0, (height - crop_height) // 2)

    payload = {
        "name": f"Controlled integration {start.date().isoformat()}",
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "America/Bogota",
        "online_event": True,
        "capacity": 3,
        "ticket_name": "Integration ticket",
        "registration_opens": (start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overview": "FAQ integration check.",
        "venue_consumption_note": "",
        "venue_consumption_amount": 0,
        "presenter_questions": [
            {"prompt": "Learning goal?", "type": "text", "required": False, "choices": []}
        ],
    }

    with TestClient(app) as client:
        try:
            created = client.post("/event-instantiations", json=payload)
            assert created.status_code == 201, created.text
            created_body = created.json()
            event_id = str(created_body["event"]["id"])
            assert created_body["validated"] is True
            assert len(created_body["questions"]) == 6

            instructions = client.get(f"/events/{event_id}/image/upload-request")
            assert instructions.status_code == 200, instructions.text
            upload = instructions.json()
            binary = client.post(
                f"/events/{event_id}/image/upload-binary",
                data={
                    "upload_url": upload["upload_url"],
                    "upload_data": json.dumps(upload["upload_data"]),
                    "file_parameter_name": upload.get("file_parameter_name", "file"),
                },
                files={"image": (image_path.name, image_bytes, "image/png")},
            )
            assert binary.status_code == 204, binary.text
            completed = client.post(
                f"/events/{event_id}/image/complete",
                json={
                    "upload_token": upload["upload_token"],
                    "crop_mask": {
                        "top_left": {"x": 0, "y": crop_top},
                        "width": width,
                        "height": crop_height,
                    },
                },
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["event"]["logo_id"]

            published = client.post(f"/event-instantiations/{event_id}/publish", json={})
            assert published.status_code == 200, published.text
            assert published.json()["status"] == "live"
        finally:
            if event_id:
                deleted = client.delete(f"/events/{event_id}", params={"confirm": "true"})
                assert deleted.status_code == 204, deleted.text
