"""HTTP-contract tests for the 360nrs adapter; no credentials or network."""

import asyncio
import json

import httpx
import pytest

from app.client import NRS360APIError, NRS360Client


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url="https://app.360nrs.com/api/rest", transport=transport)
    return NRS360Client(http, "circleupcomm", "secret"), http


def test_client_builds_basic_auth_and_uses_account_endpoint() -> None:
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["path"] = request.url.path
        received["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json={"balance": 12})

    client, http = make_client(handler)
    try:
        result = asyncio.run(client.get_account())
    finally:
        asyncio.run(http.aclose())

    assert result == {"balance": 12}
    assert received == {
        "method": "GET",
        "path": "/api/rest/account",
        "authorization": "Basic Y2lyY2xldXBjb21tOnNlY3JldA==",
    }


def test_send_sms_posts_documented_payload() -> None:
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["path"] = request.url.path
        received["body"] = json.loads(request.content)
        return httpx.Response(202, json={"campaignId": 100000, "sendingId": 100001, "result": []})

    client, http = make_client(handler)
    try:
        result = asyncio.run(
            client.send_sms({"to": ["573194477860"], "from": "TEST", "message": "Hola"})
        )
    finally:
        asyncio.run(http.aclose())

    assert result["campaignId"] == 100000
    assert received == {
        "method": "POST",
        "path": "/api/rest/sms",
        "body": {"to": ["573194477860"], "from": "TEST", "message": "Hola"},
    }


def test_get_sms_uses_message_id_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/rest/sms/abc123"
        return httpx.Response(200, json={"id": "abc123", "status": "SENT"})

    client, http = make_client(handler)
    try:
        result = asyncio.run(client.get_sms("abc123"))
    finally:
        asyncio.run(http.aclose())

    assert result == {"id": "abc123", "status": "SENT"}


def test_client_preserves_error_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 102, "description": "No valid recipients"}})

    client, http = make_client(handler)
    try:
        with pytest.raises(NRS360APIError) as raised:
            asyncio.run(client.send_sms({"to": ["34"], "from": "TEST", "message": "Hola"}))
    finally:
        asyncio.run(http.aclose())

    assert raised.value.status_code == 400
    assert raised.value.detail["error"]["code"] == 102
