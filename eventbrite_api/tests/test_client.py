"""HTTP-contract tests for the Eventbrite adapter; no credentials or network."""

import asyncio
import json

import httpx
import pytest

from app.client import EventbriteAPIError, EventbriteClient


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url="https://www.eventbriteapi.com/v3", transport=transport)
    return EventbriteClient(http, "organization-1"), http


def test_create_event_uses_the_documented_organization_endpoint_and_wrapper() -> None:
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["path"] = request.url.path
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "event-1"})

    client, http = make_client(handler)
    try:
        result = asyncio.run(client.create_event({"name": {"html": "Clase"}}))
    finally:
        asyncio.run(http.aclose())

    assert result == {"id": "event-1"}
    assert received == {
        "method": "POST",
        "path": "/v3/organizations/organization-1/events/",
        "body": {"event": {"name": {"html": "Clase"}}},
    }


@pytest.mark.parametrize(
    ("call", "method", "path"),
    [
        (lambda client: client.get_event("event-1"), "GET", "/v3/events/event-1/"),
        (
            lambda client: client.update_ticket_buyer_settings(
                "event-1",
                {
                    "collect_questions_after_payment": False,
                    "allow_attendee_update": False,
                    "survey_time_limit": 10,
                },
            ),
            "POST",
            "/v3/events/event-1/ticket_buyer_settings/",
        ),
        (lambda client: client.update_event("event-1", {"summary": "x"}), "POST", "/v3/events/event-1/"),
        (lambda client: client.create_ticket("event-1", {"name": "General"}), "POST", "/v3/events/event-1/ticket_classes/"),
        (lambda client: client.create_question("event-1", {"type": "text"}), "POST", "/v3/events/event-1/questions/"),
        (lambda client: client.create_structured_content("event-1", 1, {"modules": [], "publish": True, "purpose": "listing"}), "POST", "/v3/events/event-1/structured_content/1/"),
        (lambda client: client.publish_event("event-1"), "POST", "/v3/events/event-1/publish/"),
        (lambda client: client.delete_event("event-1"), "DELETE", "/v3/events/event-1/"),
    ],
)
def test_client_uses_expected_eventbrite_methods_and_paths(call, method, path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == method
        assert request.url.path == path
        return httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={})

    client, http = make_client(handler)
    try:
        result = asyncio.run(call(client))
    finally:
        asyncio.run(http.aclose())
    if method == "DELETE":
        assert result is None
    else:
        assert result == {}


def test_client_preserves_eventbrite_error_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "INVALID", "error_description": "Bad input"})

    client, http = make_client(handler)
    try:
        with pytest.raises(EventbriteAPIError) as raised:
            asyncio.run(client.get_event("bad"))
    finally:
        asyncio.run(http.aclose())

    assert raised.value.status_code == 422
    assert raised.value.detail["error"] == "INVALID"
