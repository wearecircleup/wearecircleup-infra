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
                        "order_id": "15414161473",
                        "order_status": "placed",
                        "event_name": "Architecture",
                        "event_url": "https://www.eventbrite.co/e/ardillas-tickets-1996633294933",
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

    class FakeOrdersTable:
        def get_item(self, Key):
            return {"Item": {"order_status": "placed"}}

    class FakeSesClient:
        def send_email(self, **kwargs):
            sent_emails.append(kwargs)
            return {"MessageId": "ses-msg-123"}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("REMINDER_FROM_EMAIL", "Circle Up Autorizacion <hola@circleup.com.co>")
    monkeypatch.setenv("REMINDER_HERO_IMAGE_URL", "https://assets.example.com/email-assets/circleupemail.png")
    monkeypatch.setenv("REMINDER_REPLY_TO_EMAIL", "hola@circleup.com.co")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FORM_URL", "https://app.youform.com/forms/iamr7tnj")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_order_submissions_table", lambda: FakeOrdersTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")
    monkeypatch.setattr(mod, "_event_has_passed", lambda item: False)

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
            "order_status": "placed",
        }
    ]
    assert sent_emails[0]["FromEmailAddress"] == "Circle Up Autorizacion <hola@circleup.com.co>"
    assert sent_emails[0]["Destination"] == {"ToAddresses": ["buyer@example.com"]}
    assert "Architecture" in sent_emails[0]["Content"]["Simple"]["Subject"]["Data"]
    assert "Completar formulario" in sent_emails[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert 'src="https://assets.example.com/email-assets/circleupemail.png"' in sent_emails[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "Te escribimos porque todavia nos falta un paso importante para el check-in si quieres participar siendo menor de edad: necesitas la autorizacion de tu representante legal para el 5 de agosto de 2026 a las 10:30 (America/Bogota) en Casa Centro, Bogota, Cundinamarca. Te estaremos esperando en Architecture, tu participacion es importante." in sent_emails[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "https://app.youform.com/forms/iamr7tnj?event_url=https%3A%2F%2Fwww.eventbrite.co%2Fe%2Fardillas-tickets-1996633294933&amp;event_date=2026-08-05" in sent_emails[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "https://app.youform.com/forms/iamr7tnj?event_url=https%3A%2F%2Fwww.eventbrite.co%2Fe%2Fardillas-tickets-1996633294933&event_date=2026-08-05" in sent_emails[0]["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert updates[0]["Key"] == {
        "pk": "EVENT#1996475418721",
        "sk": "ATTENDEE#22793113508",
    }
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_status"] == "sent"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_message_id"] == "ses-msg-123"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_error"] is None
    assert updates[0]["ExpressionAttributeValues"][":order_status"] == "placed"
    assert updates[0]["ExpressionAttributeValues"][":reminder_history_entry"] == [
        {
            "email": "buyer@example.com",
            "sent_at": "2026-08-04T17:00:00Z",
        }
    ]


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
                        "order_id": "15414161474",
                        "order_status": "placed",
                        "event_name": "Event",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeOrdersTable:
        def get_item(self, Key):
            return {"Item": {"order_status": "placed"}}

    class FakeSesClient:
        def send_email(self, **kwargs):
            sent_emails.append(kwargs)
            return {"MessageId": "should-not-send"}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("REMINDER_FROM_EMAIL", "Circle Up Autorizacion <hola@circleup.com.co>")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_order_submissions_table", lambda: FakeOrdersTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")
    monkeypatch.setattr(mod, "_event_has_passed", lambda item: False)

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
                        "order_id": "15414161475",
                        "order_status": "placed",
                        "buyer_email": "buyer@example.com",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeOrdersTable:
        def get_item(self, Key):
            return {"Item": {"order_status": "placed"}}

    class FakeSesClient:
        def send_email(self, **kwargs):
            raise RuntimeError("ses unavailable")

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("REMINDER_FROM_EMAIL", "Circle Up Autorizacion <hola@circleup.com.co>")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_order_submissions_table", lambda: FakeOrdersTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")
    monkeypatch.setattr(mod, "_event_has_passed", lambda item: False)

    result = mod.handler({}, None)

    assert result["processed"][0]["status"] == "failed"
    assert result["processed"][0]["error"] == "ses unavailable"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_status"] == "failed"
    assert updates[0]["ExpressionAttributeValues"][":last_reminder_error"] == "ses unavailable"


def test_handler_skips_cancelled_order(monkeypatch):
    updates: list[dict[str, object]] = []
    sent_emails: list[dict[str, object]] = []

    class FakeTable:
        def query(self, **kwargs):
            return {
                "Items": [
                    {
                        "pk": "EVENT#1",
                        "sk": "ATTENDEE#1",
                        "event_id": "1",
                        "attendee_id": "1",
                        "order_id": "123",
                        "order_status": "placed",
                        "buyer_email": "buyer@example.com",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeOrdersTable:
        def get_item(self, Key):
            return {"Item": {"order_status": "cancelled"}}

    class FakeSesClient:
        def send_email(self, **kwargs):
            sent_emails.append(kwargs)
            return {"MessageId": "should-not-send"}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_order_submissions_table", lambda: FakeOrdersTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")

    result = mod.handler({}, None)

    assert result["processed"] == [
        {
            "pk": "EVENT#1",
            "sk": "ATTENDEE#1",
            "status": "skipped_order_not_placed",
            "order_status": "cancelled",
        }
    ]
    assert sent_emails == []
    assert updates[0]["ExpressionAttributeValues"][":status_override"] == "closed_order"
    assert updates[0]["ExpressionAttributeValues"][":validation_result_override"] == "order_not_placed"
    assert updates[0]["ExpressionAttributeValues"][":order_status"] == "cancelled"


def test_handler_skips_past_event(monkeypatch):
    updates: list[dict[str, object]] = []
    sent_emails: list[dict[str, object]] = []

    class FakeTable:
        def query(self, **kwargs):
            return {
                "Items": [
                    {
                        "pk": "EVENT#1",
                        "sk": "ATTENDEE#1",
                        "event_id": "1",
                        "attendee_id": "1",
                        "order_id": "123",
                        "event_date": "2026-08-01",
                        "event_time": "10:30:00",
                        "event_timezone": "America/Bogota",
                        "buyer_email": "buyer@example.com",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updates.append(kwargs)

    class FakeOrdersTable:
        def get_item(self, Key):
            return {"Item": {"order_status": "placed"}}

    class FakeSesClient:
        def send_email(self, **kwargs):
            sent_emails.append(kwargs)
            return {"MessageId": "should-not-send"}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeTable())
    monkeypatch.setattr(mod, "_order_submissions_table", lambda: FakeOrdersTable())
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSesClient())
    monkeypatch.setattr(mod, "_utc_now", lambda: "2026-08-04T17:00:00Z")
    monkeypatch.setattr(mod, "_event_has_passed", lambda item: True)

    result = mod.handler({}, None)

    assert result["processed"] == [
        {
            "pk": "EVENT#1",
            "sk": "ATTENDEE#1",
            "status": "skipped_event_passed",
            "order_status": "placed",
        }
    ]
    assert sent_emails == []
    assert updates[0]["ExpressionAttributeValues"][":status_override"] == "event_passed"
    assert updates[0]["ExpressionAttributeValues"][":validation_result_override"] == "event_passed"


def test_build_form_url_falls_back_to_generated_eventbrite_url(monkeypatch):
    monkeypatch.setenv("MINOR_AUTHORIZATION_FORM_URL", "https://app.youform.com/forms/iamr7tnj")

    form_url = mod._build_form_url(
        {
            "event_id": "1996633294933",
            "event_name": "Ardillas Ñandú: Física y Café",
            "event_date": "2026-08-07",
        }
    )

    assert (
        form_url
        == "https://app.youform.com/forms/iamr7tnj?event_url=https%3A%2F%2Fwww.eventbrite.co%2Fe%2Fardillas-nandu-fisica-y-cafe-tickets-1996633294933&event_date=2026-08-07"
    )
