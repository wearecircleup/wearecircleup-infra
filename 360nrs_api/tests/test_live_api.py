"""Opt-in live checks for the real 360nrs account and SMS API."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


pytestmark = pytest.mark.live


def test_live_account_and_optional_sms_send() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200

        account = client.get("/account")
        assert account.status_code == 200, account.text
        account_body = account.json()
        assert isinstance(account_body, dict)

        if os.getenv("NRS360_LIVE_SEND_SMS") != "1":
            return

        to = os.getenv("NRS360_TEST_TO")
        from_value = os.getenv("NRS360_TEST_FROM")
        message = os.getenv("NRS360_TEST_MESSAGE", "Prueba Circle Up 360nrs")
        assert to, "Set NRS360_TEST_TO to send a real SMS."
        assert from_value, "Set NRS360_TEST_FROM to send a real SMS."

        sent = client.post(
            "/sms",
            json={
                "to": [to],
                "from": from_value,
                "message": message,
            },
        )
        assert sent.status_code in {202, 207}, sent.text
        body = sent.json()
        assert "result" in body
        accepted = [item for item in body["result"] if item.get("accepted")]
        assert accepted, body

        message_id = accepted[0].get("id")
        assert message_id, body

        fetched = client.get(f"/sms/{message_id}")
        assert fetched.status_code == 200, fetched.text
