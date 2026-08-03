"""Route-level tests using dependency overrides, never Eventbrite credentials."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

import app.main as main_module
from app.config import Settings
from app.main import app, get_app_settings, get_client


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail_ticket = False
        self.structured_content = {
            "resource_uris": {"self": "https://www.eventbriteapi.com/v3/events/event-1/structured_content/1/"},
            "purpose": "listing",
            "modules": [
                {
                    "type": "text",
                    "data": {
                        "body": {
                            "type": "text",
                            "alignment": "left",
                            "text": '<h2><a href="https://app.youform.com/forms/iamr7tnj">NNA Primero, Siempre</a></h2>',
                        }
                    },
                }
            ],
        }

    async def list_events(self, params):
        self.calls.append(("list_events", params))
        return {"events": [], "pagination": {"has_more_items": False}}

    async def list_venues(self, params):
        self.calls.append(("list_venues", params))
        return {"venues": [], "pagination": {"has_more_items": False}}

    async def create_event(self, event):
        self.calls.append(("create_event", event))
        return {"id": "event-1", **event}

    async def create_free_ticket(self, event_id, name, quantity):
        self.calls.append(("create_ticket", event_id, name, quantity))
        if self.fail_ticket:
            raise RuntimeError("ticket rejected")
        return {"id": "ticket-1"}

    async def publish_event(self, event_id):
        self.calls.append(("publish", event_id))
        return {}

    async def get_event(self, event_id, params=None):
        self.calls.append(("get_event", event_id, params))
        return {
            "id": event_id,
            "status": "live",
            "url": "https://www.eventbrite.co/e/summer-triangle-corner-tickets-1996424879557",
            "start": {"local": "2026-08-07T19:00:00-05:00"},
        }

    async def delete_event(self, event_id):
        self.calls.append(("delete_event", event_id))

    async def update_venue(self, venue_id, venue):
        self.calls.append(("update_venue", venue_id, venue))
        return {"id": venue_id, **venue}

    async def complete_image_upload(self, upload_token, crop_mask):
        self.calls.append(("complete_image_upload", upload_token, crop_mask))
        return {"id": "image-1"}

    async def update_event(self, event_id, event):
        self.calls.append(("update_event", event_id, event))
        return {"id": event_id, **event}

    async def image_upload_instructions(self):
        self.calls.append(("image_upload_instructions",))
        return {
            "upload_url": "https://signed-upload.example/image",
            "upload_data": {"key": "signed-key"},
            "upload_token": "signed-token",
        }

    async def get_structured_content(self, event_id):
        self.calls.append(("get_structured_content", event_id))
        return self.structured_content

    async def create_structured_content(self, event_id, version, content):
        self.calls.append(("create_structured_content", event_id, version, content))
        self.structured_content = {
            "resource_uris": {"self": f"https://www.eventbriteapi.com/v3/events/{event_id}/structured_content/{version}/"},
            **content,
        }
        return self.structured_content


@pytest.fixture
def client_and_fake():
    fake = FakeClient()
    app.dependency_overrides[get_client] = lambda: fake
    app.dependency_overrides[get_app_settings] = lambda: Settings("org", "organizer", "token", "USD")
    try:
        yield TestClient(app), fake
    finally:
        app.dependency_overrides.clear()


def event_body():
    return {
        "name": "Clase", "start": "2026-08-04T10:00:00-05:00",
        "end": "2026-08-04T11:00:00-05:00", "publish": True,
    }


def test_event_creation_orchestrates_event_ticket_publish_and_read(client_and_fake) -> None:
    client, fake = client_and_fake
    response = client.post("/events", json=event_body())
    assert response.status_code == 201
    assert response.json()["published"] is True
    assert [call[0] for call in fake.calls] == ["create_event", "create_ticket", "publish", "get_event"]


def test_publish_event_instantiation_personalizes_minor_authorization_link(client_and_fake) -> None:
    client, fake = client_and_fake
    response = client.post("/event-instantiations/event-1/publish", json={})

    assert response.status_code == 200
    assert [call[0] for call in fake.calls] == [
        "publish",
        "get_event",
        "get_structured_content",
        "create_structured_content",
        "get_event",
    ]
    _, event_id, version, content = fake.calls[3]
    assert event_id == "event-1"
    assert version == 2
    text = content["modules"][0]["data"]["body"]["text"]
    assert "event_url=https%3A%2F%2Fwww.eventbrite.co%2Fe%2Fsummer-triangle-corner-tickets-1996424879557" in text
    assert "event_date=08%2F07%2F2026" in text


def test_event_creation_cleans_up_draft_when_ticket_creation_fails(client_and_fake) -> None:
    client, fake = client_and_fake
    fake.fail_ticket = True
    with pytest.raises(RuntimeError, match="ticket rejected"):
        client.post("/events", json=event_body())
    assert [call[0] for call in fake.calls] == ["create_event", "create_ticket", "delete_event"]


def test_venue_update_is_a_patch_and_rejects_an_empty_body(client_and_fake) -> None:
    client, fake = client_and_fake
    assert client.patch("/venues/venue-1", json={}).status_code == 422
    response = client.patch("/venues/venue-1", json={"name": "Casa"})
    assert response.status_code == 200
    assert fake.calls[-1] == ("update_venue", "venue-1", {"name": "Casa"})


def test_venue_delete_reports_that_eventbrite_does_not_support_it(client_and_fake) -> None:
    client, fake = client_and_fake
    response = client.delete("/venues/venue-1", params={"confirm": "true"})
    assert response.status_code == 501
    assert "does not support deleting venues" in response.text
    assert not any(call[0] == "delete_venue" for call in fake.calls)


def test_list_events_forwards_pagination_and_filters(client_and_fake) -> None:
    client, fake = client_and_fake
    response = client.get("/events", params={"page": 2, "page_size": 10, "status": "live"})
    assert response.status_code == 200
    assert fake.calls[-1] == ("list_events", {"page": 2, "page_size": 10, "order_by": "start_asc", "status": "live"})


def test_list_venues_never_forwards_unsupported_page_size(client_and_fake) -> None:
    client, fake = client_and_fake
    response = client.get("/venues", params={"page": 2, "page_size": 50})
    assert response.status_code == 200
    assert fake.calls[-1] == ("list_venues", {"page": 2})


def test_event_delete_returns_204_when_eventbrite_accepts_the_delete(client_and_fake) -> None:
    client, fake = client_and_fake
    response = client.delete("/events/event-1", params={"confirm": "true"})
    assert response.status_code == 204
    assert fake.calls[-1] == ("delete_event", "event-1")


def test_image_completion_accepts_the_studio_json_body(client_and_fake) -> None:
    client, fake = client_and_fake
    crop_mask = {"top_left": {"x": 0, "y": 0}, "width": 1200, "height": 600}
    response = client.post(
        "/events/event-1/image/complete",
        json={"upload_token": "signed-token", "crop_mask": crop_mask},
    )
    assert response.status_code == 200
    assert response.json()["event"]["logo_id"] == "image-1"
    assert fake.calls[-2:] == [
        ("complete_image_upload", "signed-token", crop_mask),
        ("update_event", "event-1", {"logo_id": "image-1"}),
    ]


def test_image_binary_upload_accepts_the_studio_png_fixture(client_and_fake, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the multipart contract with the same kind of PNG Studio sends."""
    client, fake = client_and_fake
    captured = {}

    class SignedUploadClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, data, files):
            captured.update({"url": url, "data": data, "files": files})
            return httpx.Response(204)

    monkeypatch.setattr(main_module.httpx, "AsyncClient", SignedUploadClient)
    image_path = Path(__file__).with_name("help-carrusel-2.png")
    response = client.post(
        "/events/event-1/image/upload-binary",
        data={
            "upload_url": "https://signed-upload.example/image",
            "upload_data": json.dumps({"key": "signed-key"}),
        },
        files={"image": (image_path.name, image_path.read_bytes(), "image/png")},
    )

    assert response.status_code == 204
    assert captured["url"] == "https://signed-upload.example/image"
    assert captured["data"] == {"key": "signed-key"}
    assert captured["files"]["file"][0] == image_path.name


def test_api_token_is_required_when_configured() -> None:
    fake = FakeClient()
    app.dependency_overrides[get_client] = lambda: fake
    app.dependency_overrides[get_app_settings] = lambda: Settings("org", "organizer", "token", "USD", api_auth_token="secret-token")
    try:
        with TestClient(app) as client:
            client.app.state.settings = Settings("org", "organizer", "token", "USD", api_auth_token="secret-token")
            unauthorized = client.get("/events")
            assert unauthorized.status_code == 401
            authorized = client.get("/events", headers={"Authorization": "Bearer secret-token"})
            assert authorized.status_code == 200
    finally:
        app.dependency_overrides.clear()
