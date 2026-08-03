import lambda_handler as mod


def test_store_order_submission_saves_minimal_order_shape(monkeypatch):
    order_id = "15413130193"
    event_id = "1996456922398"
    attendee_id = "22792951476"
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
                "created": "2026-08-03T15:23:52Z",
                "changed": "2026-08-03T15:24:04Z",
                "name": "Nicolas CircleUp",
                "first_name": "Nicolas",
                "last_name": "CircleUp",
                "email": "gocircleup@gmail.com",
            }
        if url == f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1":
            return {
                "attendees": [
                    {
                        "id": attendee_id,
                        "event_id": event_id,
                        "order_id": order_id,
                        "created": "2026-08-03T15:24:01Z",
                        "changed": "2026-08-03T15:24:02Z",
                        "status": "Attending",
                        "checked_in": False,
                        "cancelled": False,
                        "refunded": False,
                        "ticket_class_id": "3445465366",
                        "ticket_class_name": "Entrada General",
                        "quantity": 1,
                        "delivery_method": "electronic",
                        "profile": {
                            "name": "Nicolas CircleUp",
                            "first_name": "Nicolas",
                            "last_name": "CircleUp",
                            "email": "gocircleup@gmail.com",
                        },
                        "barcodes": [
                            {
                                "barcode": "1541313019322792951476001",
                                "status": "unused",
                                "qr_code_url": "https://example.com/qr",
                            }
                        ],
                        "answers": [
                            {
                                "question_id": "323298496",
                                "question": "Â¿CuÃ¡l es tu rango de edad?",
                                "answer": "14 a 17 aÃ±os",
                                "type": "multiple_choice",
                            },
                        ],
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
        {"api_url": api_url, "config": {"action": "order.placed", "webhook_id": "15905335"}},
        {"time": "03/Aug/2026:15:24:46 +0000"},
    )

    assert result == {
        "stored": True,
        "order_id": order_id,
        "attendee_count": 1,
        "webhook_action": "order.placed",
    }
    assert requested_urls == [
        api_url,
        f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1",
    ]
    assert saved["Item"] == {
        "pk": f"ORDER#{order_id}",
        "sk": f"ORDER#{order_id}",
        "entity_type": "eventbrite_order",
        "order_id": order_id,
        "event_id": event_id,
        "order_status": "placed",
        "order_created": "2026-08-03T15:23:52Z",
        "order_changed": "2026-08-03T15:24:04Z",
        "attendee_count": 1,
        "buyer": {
            "name": "Nicolas CircleUp",
            "first_name": "Nicolas",
            "last_name": "CircleUp",
            "email": "gocircleup@gmail.com",
        },
        "attendees": [
            {
                "attendee_id": attendee_id,
                "event_id": event_id,
                "order_id": order_id,
                "created": "2026-08-03T15:24:01Z",
                "changed": "2026-08-03T15:24:02Z",
                "status": "Attending",
                "checked_in": False,
                "cancelled": False,
                "refunded": False,
                "ticket_class_id": "3445465366",
                "ticket_class_name": "Entrada General",
                "quantity": 1,
                "delivery_method": "electronic",
                "profile": {
                    "name": "Nicolas CircleUp",
                    "first_name": "Nicolas",
                    "last_name": "CircleUp",
                    "email": "gocircleup@gmail.com",
                },
                "barcodes": [
                    {
                        "barcode": "1541313019322792951476001",
                        "status": "unused",
                        "qr_code_url": "https://example.com/qr",
                    }
                ],
                "answers": [
                    {
                        "question_id": "323298496",
                        "question": "¿Cuál es tu rango de edad?",
                        "answer": "14 a 17 años",
                        "type": "multiple_choice",
                    }
                ],
            }
        ],
        "webhook": {
            "api_url": api_url,
            "received_at": "03/Aug/2026:15:24:46 +0000",
            "action": "order.placed",
            "webhook_id": "15905335",
        },
    }


def test_store_order_submission_skips_unsupported_api_url(monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("EVENTBRITE_PRIVATE_TOKEN", "token-123")

    result = mod._store_order_submission(
        {
            "api_url": "https://www.eventbriteapi.com/v3/events/1996456922398/attendees/22792951476/",
            "config": {"action": "attendee.updated"},
        },
        {"time": "03/Aug/2026:15:24:46 +0000"},
    )

    assert result == {
        "stored": False,
        "reason": "unsupported_api_url",
    }
