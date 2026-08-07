import lambda_handler as mod


def test_store_order_submission_saves_minimal_order_shape(monkeypatch):
    order_id = "15413130193"
    event_id = "1996456922398"
    attendee_id = "22792951476"
    api_url = f"https://www.eventbriteapi.com/v3/orders/{order_id}/"
    saved: dict[str, object] = {}
    requested_urls: list[str] = []
    sent_messages: list[dict[str, object]] = []

    class FakeTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FakeSQS:
        def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return {"MessageId": "msg-123"}

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
        if url == f"https://www.eventbriteapi.com/v3/events/{event_id}/":
            return {
                "id": event_id,
                "name": {"text": "Architecture"},
                "url": "https://www.eventbrite.co/e/architecture-tickets-1996456922398",
                "venue_id": "700001",
                "start": {
                    "local": "2026-08-05T10:30:00",
                    "timezone": "America/Bogota",
                },
            }
        if url == "https://www.eventbriteapi.com/v3/venues/700001/":
            return {
                "id": "700001",
                "name": "Casa Centro",
                "address": {
                    "localized_address_display": "Cra 10 # 12-30, Bogota, Colombia",
                    "city": "Bogota",
                    "region": "Cundinamarca",
                    "country": "CO",
                },
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
    monkeypatch.setenv("AUTHORIZATION_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/minor-auth")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeTable())
    monkeypatch.setattr(mod, "_sqs_client", lambda: FakeSQS())

    result = mod._store_order_submission(
        {"api_url": api_url, "config": {"action": "order.placed", "webhook_id": "15905335"}},
        {"time": "03/Aug/2026:15:24:46 +0000"},
    )

    assert result == {
        "stored": True,
        "order_id": order_id,
        "attendee_count": 1,
        "webhook_action": "order.placed",
        "minor_authorization_jobs_enqueued": 1,
    }
    assert requested_urls == [
        api_url,
        f"https://www.eventbriteapi.com/v3/events/{event_id}/",
        "https://www.eventbriteapi.com/v3/venues/700001/",
        f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1",
    ]
    assert sent_messages == [
        {
            "QueueUrl": "https://sqs.us-east-1.amazonaws.com/123/minor-auth",
            "MessageBody": (
                '{"event_id": "1996456922398", "event_name": "Architecture", "event_url": "https://www.eventbrite.co/e/architecture-tickets-1996456922398", "event_date": "2026-08-05", '
                '"event_time": "10:30:00", "event_timezone": "America/Bogota", "venue_name": "Casa Centro", '
                '"venue_city": "Bogota", "venue_region": "Cundinamarca", "order_id": "15413130193", '
                '"order_created": "2026-08-03T15:23:52Z", "order_status": "placed", "attendee_id": "22792951476", '
                '"attendee_email": "gocircleup@gmail.com", "buyer_email": "gocircleup@gmail.com", '
                '"age_range": "14 a 17 años", "detected_at": "03/Aug/2026:15:24:46 +0000", '
                '"request_id": null, "source": "eventbrite_order_webhook"}'
            ),
        }
    ]
    assert saved["Item"] == {
        "pk": f"ORDER#{order_id}",
        "sk": f"ORDER#{order_id}",
        "entity_type": "eventbrite_order",
        "order_id": order_id,
        "event_id": event_id,
        "event_name": "Architecture",
        "event_url": "https://www.eventbrite.co/e/architecture-tickets-1996456922398",
        "event_date": "2026-08-05",
        "event_time": "10:30:00",
        "event_timezone": "America/Bogota",
        "venue_id": "700001",
        "venue_name": "Casa Centro",
        "venue_address": "Cra 10 # 12-30, Bogota, Colombia",
        "venue_city": "Bogota",
        "venue_region": "Cundinamarca",
        "venue_country": "CO",
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


def test_store_order_submission_does_not_enqueue_when_no_minor_is_detected(monkeypatch):
    order_id = "15413130194"
    event_id = "1996456922399"
    api_url = f"https://www.eventbriteapi.com/v3/orders/{order_id}/"
    sent_messages: list[dict[str, object]] = []

    class FakeTable:
        def put_item(self, Item):
            return None

    class FakeSQS:
        def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return {"MessageId": "msg-456"}

    def fake_request_json(url: str, token: str):
        assert token == "token-123"
        if url == api_url:
            return {
                "id": order_id,
                "event_id": event_id,
                "status": "placed",
                "created": "2026-08-03T15:23:52Z",
                "changed": "2026-08-03T15:24:04Z",
                "name": "Adult Person",
                "first_name": "Adult",
                "last_name": "Person",
                "email": "adult@example.com",
            }
        if url == f"https://www.eventbriteapi.com/v3/events/{event_id}/":
            return {
                "id": event_id,
                "name": {"text": "Astronomy"},
                "url": "https://www.eventbrite.co/e/astronomy-tickets-1996456922399",
                "venue_id": "700002",
                "start": {
                    "local": "2026-08-06T18:45:00",
                    "timezone": "America/Bogota",
                },
            }
        if url == "https://www.eventbriteapi.com/v3/venues/700002/":
            return {
                "id": "700002",
                "name": "Observatorio",
                "address": {
                    "localized_address_display": "Calle 1 # 2-3, Bogota, Colombia",
                    "city": "Bogota",
                    "region": "Cundinamarca",
                    "country": "CO",
                },
            }
        if url == f"https://www.eventbriteapi.com/v3/orders/{order_id}/attendees/?page=1":
            return {
                "attendees": [
                    {
                        "id": "22792951477",
                        "event_id": event_id,
                        "order_id": order_id,
                        "profile": {"email": "adult@example.com"},
                        "answers": [
                            {
                                "question_id": "323298497",
                                "question": "Â¿CuÃ¡l es tu rango de edad?",
                                "answer": "18 a 24 años",
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
    monkeypatch.setenv("AUTHORIZATION_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/minor-auth")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeTable())
    monkeypatch.setattr(mod, "_sqs_client", lambda: FakeSQS())

    result = mod._store_order_submission(
        {"api_url": api_url, "config": {"action": "order.placed"}},
        {"time": "03/Aug/2026:15:24:46 +0000"},
    )

    assert result["minor_authorization_jobs_enqueued"] == 0
    assert sent_messages == []
