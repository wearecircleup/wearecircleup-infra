import lambda_handler as mod


def test_store_order_submission_fetches_attendee_details_and_saves_compact_item(monkeypatch):
    order_id = "15401099803"
    event_id = "1996317994862"
    attendee_id = "22790989374"
    api_url = f"https://www.eventbriteapi.com/v3/orders/{order_id}/"
    saved: dict[str, object] = {}
    requested_urls: list[str] = []

    class FakeTable:
        def put_item(self, Item):
            saved["Item"] = Item

    def fake_request_json(url: str, token: str):
        requested_urls.append(url)
        assert token == "token-123"
        if url == api_url:
            return {
                "id": order_id,
                "event_id": event_id,
                "status": "placed",
                "created": "2026-08-01T02:44:04Z",
                "changed": "2026-08-01T02:44:16Z",
                "name": "Daniel Diaz",
                "email": "danielnicolasmuner@gmail.com",
            }
        if url == f"https://www.eventbriteapi.com/v3/events/{event_id}/questions/":
            return {
                "questions": [
                    {
                        "id": "q1",
                        "type": "dropdown",
                        "required": True,
                        "respondent": "attendee",
                        "question": {"html": "¿Cuál es tu rango de edad?"},
                    }
                ]
            }
        if url == f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1":
            return {
                "attendees": [
                    {
                        "id": attendee_id,
                        "event_id": event_id,
                        "ticket_class_name": "Entrada General",
                        "profile": {"email": "fallback@example.com"},
                    }
                ],
                "pagination": {"has_more_items": False},
            }
        if url == f"https://www.eventbriteapi.com/v3/events/{event_id}/attendees/{attendee_id}/":
            return {
                "id": attendee_id,
                "ticket_class_name": "Entrada General",
                "profile": {"email": "danielnicolasmuner@gmail.com"},
                "answers": [
                    {"question": "¿Cuál es tu rango de edad?", "answer": "18 a 24 años"},
                    {
                        "question": {"html": "¿Cuál es tu nivel educativo actual?"},
                        "answer_text": "Universitario",
                    },
                ],
            }
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("EVENTBRITE_PRIVATE_TOKEN", "token-123")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeTable())

    result = mod._store_order_submission(
        {"api_url": api_url, "config": {"action": "order.placed"}},
        {"time": "01/Aug/2026:02:44:35 +0000"},
    )

    assert result == {
        "stored": True,
        "order_id": order_id,
        "attendee_count": 1,
        "webhook_action": "order.placed",
    }
    assert requested_urls == [
        api_url,
        f"https://www.eventbriteapi.com/v3/events/{event_id}/questions/",
        f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1",
        f"https://www.eventbriteapi.com/v3/events/{event_id}/attendees/{attendee_id}/",
    ]
    assert saved["Item"] == {
        "pk": f"ORDER#{order_id}",
        "sk": f"ORDER#{order_id}",
        "order_id": order_id,
        "event_id": event_id,
        "order_status": "placed",
        "order_created": "2026-08-01T02:44:04Z",
        "order_changed": "2026-08-01T02:44:16Z",
        "buyer": {
            "name": "Daniel Diaz",
            "email": "danielnicolasmuner@gmail.com",
        },
        "attendees": [
            {
                "attendee_id": attendee_id,
                "ticket_class_name": "Entrada General",
                "email": "danielnicolasmuner@gmail.com",
                "answers": [
                    {"question": "¿Cuál es tu rango de edad?", "answer": "18 a 24 años"},
                    {
                        "question": "¿Cuál es tu nivel educativo actual?",
                        "answer": "Universitario",
                    },
                ],
            }
        ],
        "webhook": {
            "api_url": api_url,
            "received_at": "01/Aug/2026:02:44:35 +0000",
            "action": "order.placed",
        },
    }


def test_store_order_submission_supports_attendee_updated_webhooks(monkeypatch):
    order_id = "15402564773"
    event_id = "1996317994862"
    attendee_id = "22791222904"
    attendee_api_url = f"https://www.eventbriteapi.com/v3/events/{event_id}/attendees/{attendee_id}/"
    saved: dict[str, object] = {}
    requested_urls: list[str] = []

    class FakeTable:
        def put_item(self, Item):
            saved["Item"] = Item

    def fake_request_json(url: str, token: str):
        requested_urls.append(url)
        assert token == "token-123"
        if url == attendee_api_url:
            return {
                "id": attendee_id,
                "event_id": event_id,
                "order_id": order_id,
                "ticket_class_name": "Entrada General",
                "profile": {"email": "mvelena68@gmail.com"},
                "answers": [
                    {"question": "¿Cuál es tu rango de edad?", "answer": "35 a 44 años"},
                ],
            }
        if url == f"https://www.eventbriteapi.com/v3/orders/{order_id}/":
            return {
                "id": order_id,
                "event_id": event_id,
                "status": "placed",
                "created": "2026-08-01T11:29:13Z",
                "changed": "2026-08-01T11:30:22Z",
                "name": "Elena Munevar",
                "email": "mvelena68@gmail.com",
            }
        if url == f"https://www.eventbriteapi.com/v3/events/{event_id}/questions/":
            return {
                "questions": [
                    {
                        "id": "q1",
                        "type": "dropdown",
                        "required": True,
                        "respondent": "attendee",
                        "question": {"html": "¿Cuál es tu rango de edad?"},
                    }
                ]
            }
        if url == f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1":
            return {
                "attendees": [
                    {
                        "id": attendee_id,
                        "event_id": event_id,
                        "ticket_class_name": "Entrada General",
                        "profile": {"email": "mvelena68@gmail.com"},
                    }
                ],
                "pagination": {"has_more_items": False},
            }
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("EVENTBRITE_PRIVATE_TOKEN", "token-123")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeTable())

    result = mod._store_order_submission(
        {"api_url": attendee_api_url, "config": {"action": "attendee.updated"}},
        {"time": "01/Aug/2026:11:31:00 +0000"},
    )

    assert result == {
        "stored": True,
        "order_id": order_id,
        "attendee_count": 1,
        "webhook_action": "attendee.updated",
    }
    assert requested_urls == [
        attendee_api_url,
        f"https://www.eventbriteapi.com/v3/orders/{order_id}/",
        f"https://www.eventbriteapi.com/v3/events/{event_id}/questions/",
        f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1",
        attendee_api_url,
    ]
    assert saved["Item"]["attendees"] == [
        {
            "attendee_id": attendee_id,
            "ticket_class_name": "Entrada General",
            "email": "mvelena68@gmail.com",
            "answers": [
                {"question": "¿Cuál es tu rango de edad?", "answer": "35 a 44 años"},
            ],
        }
    ]
