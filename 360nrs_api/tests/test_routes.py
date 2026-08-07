"""Route-level tests using dependency overrides, never real credentials."""

from fastapi.testclient import TestClient
import pytest
import os

from app.config import Settings
from app.main import app, get_app_settings, get_client


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get_account(self):
        self.calls.append(("get_account",))
        return {"user": "circleupcomm", "balance": 12}

    async def send_sms(self, payload):
        self.calls.append(("send_sms", payload))
        accepted = [{"accepted": True, "to": payload["to"][0], "id": "abc123", "parts": 1}]
        return {"campaignId": 100000, "sendingId": 100001, "result": accepted}

    async def get_sms(self, message_id):
        self.calls.append(("get_sms", message_id))
        return {"id": message_id, "status": "SENT"}


@pytest.fixture
def client_and_fake():
    fake = FakeClient()
    app.dependency_overrides[get_client] = lambda: fake
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        username="circleupcomm",
        api_password="secret",
        dashboard_host="https://app.360nrs.com",
        api_base_url="https://app.360nrs.com/api/rest",
        default_notification_url="https://example.com/webhook",
    )
    try:
        yield TestClient(app), fake
    finally:
        app.dependency_overrides.clear()


def test_account_route_returns_provider_response(client_and_fake) -> None:
    client, fake = client_and_fake

    response = client.get("/account")

    assert response.status_code == 200
    assert response.json()["user"] == "circleupcomm"
    assert fake.calls == [("get_account",)]


def test_send_sms_route_uses_normalized_payload_and_default_notification_url(client_and_fake) -> None:
    client, fake = client_and_fake

    response = client.post(
        "/sms",
        json={
            "to": ["+57 319 447 7860"],
            "from": "TEST",
            "message": "Prueba Circle Up 360nrs",
        },
    )

    assert response.status_code == 202
    assert response.json()["campaignId"] == 100000
    assert fake.calls[-1] == (
        "send_sms",
        {
            "to": ["573194477860"],
            "from": "TEST",
            "message": "Prueba Circle Up 360nrs",
            "notificationUrl": "https://example.com/webhook",
        },
    )


def test_send_sms_returns_multi_status_when_provider_mixes_acceptance(client_and_fake) -> None:
    client, fake = client_and_fake

    async def mixed(payload):
        fake.calls.append(("send_sms", payload))
        return {
            "campaignId": 100000,
            "sendingId": 100001,
            "result": [
                {"accepted": True, "to": "573194477860", "id": "ok-1", "parts": 1},
                {"accepted": False, "to": "34", "error": {"code": 102, "description": "No valid recipients"}},
            ],
        }

    fake.send_sms = mixed
    response = client.post(
        "/sms",
        json={
            "to": ["573194477860", "34"],
            "from": "TEST",
            "message": "Prueba mixta",
        },
    )

    assert response.status_code == 207
    assert len(response.json()["result"]) == 2


def test_get_sms_requires_a_non_empty_message_id(client_and_fake) -> None:
    client, _ = client_and_fake

    response = client.get("/sms/%20")

    assert response.status_code == 422


def test_api_token_is_required_when_configured() -> None:
    fake = FakeClient()
    app.dependency_overrides[get_client] = lambda: fake
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        username="circleupcomm",
        api_password="secret",
        dashboard_host="https://app.360nrs.com",
        api_base_url="https://app.360nrs.com/api/rest",
        api_auth_token="wrapper-secret",
    )
    previous_username = os.environ.get("NRS360_USERNAME")
    previous_password = os.environ.get("NRS360_API_PASSWORD")
    os.environ["NRS360_USERNAME"] = "circleupcomm"
    os.environ["NRS360_API_PASSWORD"] = "secret"
    try:
        with TestClient(app) as client:
            client.app.state.settings = Settings(
                username="circleupcomm",
                api_password="secret",
                dashboard_host="https://app.360nrs.com",
                api_base_url="https://app.360nrs.com/api/rest",
                api_auth_token="wrapper-secret",
            )
            unauthorized = client.get("/account")
            assert unauthorized.status_code == 401
            authorized = client.get("/account", headers={"Authorization": "Bearer wrapper-secret"})
            assert authorized.status_code == 200
    finally:
        if previous_username is None:
            os.environ.pop("NRS360_USERNAME", None)
        else:
            os.environ["NRS360_USERNAME"] = previous_username
        if previous_password is None:
            os.environ.pop("NRS360_API_PASSWORD", None)
        else:
            os.environ["NRS360_API_PASSWORD"] = previous_password
        app.dependency_overrides.clear()
