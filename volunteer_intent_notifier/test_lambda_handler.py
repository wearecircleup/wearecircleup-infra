import json

import lambda_handler as mod
import pytest


def test_handler_sends_volunteer_intent_admin_notification(monkeypatch):
    updated: list[dict[str, object]] = []
    sent: dict[str, object] = {}

    class FakeTable:
        def get_item(self, **kwargs):
            return {"Item": {"pk": kwargs["Key"]["pk"], "sk": kwargs["Key"]["sk"]}}

        def update_item(self, **kwargs):
            updated.append(kwargs)

    class FakeSes:
        def send_email(self, **kwargs):
            sent.update(kwargs)
            return {"MessageId": "ses-msg-1"}

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL", "Circle Up Voluntariado <hola@circleup.com.co>")
    monkeypatch.setenv(
        "VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL",
        "wearecircleup@gmail.com,hola@circleup.com.co",
    )
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFICATION_REPLY_TO_EMAIL", "hola@circleup.com.co")
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFICATION_LOGO_URL", "https://circleup.com.co/logo.png")

    monkeypatch.setattr(mod, "_dynamodb_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSes())

    response = mod.handler(
        {
            "pk": "FORM#46titbii",
            "sk": "SUBMISSION#ahcscgfgka",
            "submission_id": "ahcscgfgka",
            "proposal_event_name": "El arte de escuchar",
            "proposal_topic": "Hablaré sobre SOLID.",
            "proposal_requested_date": "2026-08-12",
            "proposal_requested_time": "8:00 p.m.",
            "proposal_admin_question": "No",
            "contact_name": "Napoleon Bonaparte",
            "contact_email": "napoleonbonaparte@gmail.com",
            "contact_phone": "+573211231212",
        },
        None,
    )
    payload = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert payload["status"] == "sent"
    assert sent["Destination"] == {
        "ToAddresses": ["wearecircleup@gmail.com", "hola@circleup.com.co"]
    }
    assert "wa.me/573211231212" in sent["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert updated[0]["Key"] == {"pk": "FORM#46titbii", "sk": "SUBMISSION#ahcscgfgka"}


def test_handler_skips_when_notification_was_already_sent(monkeypatch):
    updated: list[dict[str, object]] = []

    class FakeTable:
        def get_item(self, **kwargs):
            return {"Item": {"admin_notification_status": "sent"}}

        def update_item(self, **kwargs):
            updated.append(kwargs)

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda: FakeTable())

    response = mod.handler(
        {
            "pk": "FORM#46titbii",
            "sk": "SUBMISSION#ahcscgfgka",
            "submission_id": "ahcscgfgka",
        },
        None,
    )

    assert json.loads(response["body"])["status"] == "already_sent"
    assert updated[0]["ExpressionAttributeValues"][":status"] == "already_sent"


def test_volunteer_intent_to_emails_rejects_unauthorized_recipient(monkeypatch):
    monkeypatch.setenv(
        "VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL",
        "hola@circleup.com.co,alguien@example.com",
    )

    with pytest.raises(RuntimeError, match="unauthorized recipients"):
        mod._volunteer_intent_to_emails()
