import lambda_handler as mod


def test_handler_sends_reminder_and_updates_job(monkeypatch):
    updates: list[dict[str, object]] = []
    sent_emails: list[dict[str, object]] = []

    class FakeTable:
        def query(self, **kwargs):
            assert kwargs["IndexName"] == "gsi1"
            return {
                "Items": [
                    {
                        "pk": "EVENT#1996475418721",
                        "sk": "ATTENDEE#22793113508",
                        "event_name": "Architecture",
                        "event_date": "2026-08-05",
                        "event_time": "10:30:00",
                        "event_timezone": "America/Bogota",
                        "venue_name": "Casa Centro",
                        "venue_city": "Bogota",
                        "venue_region": "Cundinamarca",
                        "buyer_email": "buyer@example.com",
                        "attendee_email": "minor@example.com",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeSesClient:
        def send_email(self, **kwargs):
            sent_emails.append(kwargs)
            return {"MessageId": "ses-msg-123"}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("REMINDER_FROM_EMAIL", "hola@circleup.com.co")
    monkeypatch.setenv("REMINDER_REPLY_TO_EMAIL", "hola@circleup.com.co")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FORM_URL", "https://app.youform.com/forms/iamr7tnj")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")

    result = mod.handler({}, None)

    assert result["ok"] is True
    assert result["jobs_found"] == 1
    assert result["processed"] == [
        {
            "pk": "EVENT#1996475418721",
            "sk": "ATTENDEE#22793113508",
            "status": "sent",
            "recipient": "buyer@example.com",
            "message_id": "ses-msg-123",
        }
    ]
    assert sent_emails[0]["FromEmailAddress"] == "hola@circleup.com.co"
    assert sent_emails[0]["Destination"] == {"ToAddresses": ["buyer@example.com"]}
    assert "Architecture" in sent_emails[0]["Content"]["Simple"]["Subject"]["Data"]
    assert updates[0]["Key"] == {
        "pk": "EVENT#1996475418721",
        "sk": "ATTENDEE#22793113508",
    }
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_status"] == "sent"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_message_id"] == "ses-msg-123"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_error"] is None


def test_handler_marks_missing_email_without_sending(monkeypatch):
    updates: list[dict[str, object]] = []
    sent_emails: list[dict[str, object]] = []

    class FakeTable:
        def query(self, **kwargs):
            return {
                "Items": [
                    {
                        "pk": "EVENT#1",
                        "sk": "ATTENDEE#1",
                        "event_name": "Event",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeSesClient:
        def send_email(self, **kwargs):
            sent_emails.append(kwargs)
            return {"MessageId": "should-not-send"}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("REMINDER_FROM_EMAIL", "hola@circleup.com.co")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")

    result = mod.handler({}, None)

    assert result["processed"][0]["status"] == "skipped_missing_email"
    assert sent_emails == []
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_status"] == "skipped_missing_email"


def test_handler_marks_failure_when_ses_raises(monkeypatch):
    updates: list[dict[str, object]] = []

    class FakeTable:
        def query(self, **kwargs):
            return {
                "Items": [
                    {
                        "pk": "EVENT#1",
                        "sk": "ATTENDEE#1",
                        "buyer_email": "buyer@example.com",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeSesClient:
        def send_email(self, **kwargs):
            raise RuntimeError("ses unavailable")

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("REMINDER_FROM_EMAIL", "hola@circleup.com.co")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")

    result = mod.handler({}, None)

    assert result["processed"][0]["status"] == "failed"
    assert result["processed"][0]["error"] == "ses unavailable"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_status"] == "failed"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_error"] == "ses unavailable"
