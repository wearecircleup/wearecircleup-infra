import lambda_handler as mod


def test_handler_marks_job_as_authorized_when_youform_submission_exists(monkeypatch):
    saved: dict[str, object] = {}
    updated: dict[str, object] = {}

    class FakeJobsTable:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            saved["Item"] = Item

        def update_item(self, **kwargs):
            updated.update(kwargs)

    class FakeYouformTable:
        def query(self, **kwargs):
            assert kwargs["IndexName"] == "gsi2"
            return {
                "Items": [
                    {
                        "submission_id": "o6ro2kooc5",
                        "eventbrite_event_id": "1996475418721",
                        "registration_email": "minor@example.com",
                        "completed_at": "2026-08-03T18:18:00Z",
                    }
                ]
            }

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("YOUFORM_SUBMISSIONS_TABLE_NAME", "test-youform")
    monkeypatch.setenv("AUTHORIZATION_MAX_ATTEMPTS", "5")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeJobsTable())
    monkeypatch.setattr(mod, "_youform_table", lambda: FakeYouformTable())

    result = mod.handler(
        {
            "Records": [
                {
                    "body": (
                        '{"event_id": "1996475418721", "order_id": "15414161473", '
                        '"attendee_id": "22793113508", "attendee_email": "Minor@example.com", '
                        '"buyer_email": "buyer@example.com", "age_range": "14 a 17 aÃ±os", '
                        '"detected_at": "2026-08-03T18:19:14Z", "request_id": "req-1", '
                        '"source": "eventbrite_order_webhook"}'
                    )
                }
            ]
        },
        None,
    )

    assert result["ok"] is True
    assert result["processed"] == [
        {
            "stored": True,
            "pk": "EVENT#1996475418721",
            "sk": "ATTENDEE#22793113508",
            "status": "authorized",
            "validation_result": "form_found",
            "authorization_found": True,
            "matched_submission_id": "o6ro2kooc5",
        }
    ]
    assert saved["Item"] == {
        "pk": "EVENT#1996475418721",
        "sk": "ATTENDEE#22793113508",
        "entity_type": "minor_authorization_validation",
        "event_id": "1996475418721",
        "order_id": "15414161473",
        "attendee_id": "22793113508",
        "attendee_email": "Minor@example.com",
        "buyer_email": "buyer@example.com",
        "age_range": "14 a 17 aÃ±os",
        "status": "pending",
        "validation_result": "unknown",
        "action_taken": "none",
        "attempt_count": 0,
        "max_attempts": 5,
        "first_seen_at": "2026-08-03T18:19:14Z",
        "authorization_found": False,
        "delete_attempted": False,
        "delete_succeeded": False,
        "request_id": "req-1",
        "source": "eventbrite_order_webhook",
        "gsi1pk": "STATUS#pending",
        "gsi1sk": "FIRST_SEEN_AT#2026-08-03T18:19:14Z#EVENT#1996475418721#ATTENDEE#22793113508",
        "gsi2pk": "EMAIL#minor@example.com",
        "gsi2sk": "EVENT#1996475418721#ATTENDEE#22793113508",
    }
    assert updated["Key"] == {
        "pk": "EVENT#1996475418721",
        "sk": "ATTENDEE#22793113508",
    }
    assert updated["ExpressionAttributeValues"][":status"] == "authorized"
    assert updated["ExpressionAttributeValues"][":validation_result"] == "form_found"
    assert updated["ExpressionAttributeValues"][":authorization_found"] is True
    assert updated["ExpressionAttributeValues"][":matched_submission_id"] == "o6ro2kooc5"
    assert updated["ExpressionAttributeValues"][":attempt_count"] == 1
    assert updated["ExpressionAttributeValues"][":gsi1pk"] == "STATUS#authorized"


def test_handler_marks_job_as_missing_form_when_youform_submission_does_not_exist(monkeypatch):
    updated: dict[str, object] = {}

    class FakeJobsTable:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            return None

        def update_item(self, **kwargs):
            updated.update(kwargs)

    class FakeYouformTable:
        def query(self, **kwargs):
            return {"Items": []}

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("YOUFORM_SUBMISSIONS_TABLE_NAME", "test-youform")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeJobsTable())
    monkeypatch.setattr(mod, "_youform_table", lambda: FakeYouformTable())

    result = mod.handler(
        {
            "Records": [
                {
                    "body": (
                        '{"event_id": "1996475418721", "attendee_id": "22793113508", '
                        '"attendee_email": "minor@example.com"}'
                    )
                }
            ]
        },
        None,
    )

    assert result["processed"][0]["status"] == "missing_form"
    assert result["processed"][0]["validation_result"] == "form_missing"
    assert result["processed"][0]["authorization_found"] is False
    assert result["processed"][0]["matched_submission_id"] is None
    assert updated["ExpressionAttributeValues"][":status"] == "missing_form"
    assert updated["ExpressionAttributeValues"][":validation_result"] == "form_missing"
    assert updated["ExpressionAttributeValues"][":authorization_found"] is False
    assert updated["ExpressionAttributeValues"][":matched_submission_id"] is None
    assert updated["ExpressionAttributeValues"][":gsi1pk"] == "STATUS#missing_form"


def test_handler_skips_duplicate_minor_authorization_job(monkeypatch):
    class FakeJobsTable:
        def get_item(self, Key):
            return {"Item": {"pk": Key["pk"], "sk": Key["sk"]}}

        def put_item(self, Item):
            raise AssertionError("put_item should not be called for duplicates")

        def update_item(self, **kwargs):
            raise AssertionError("update_item should not be called for duplicates")

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeJobsTable())

    result = mod.handler(
        {
            "Records": [
                {
                    "body": (
                        '{"event_id": "1996475418721", "attendee_id": "22793113508", '
                        '"attendee_email": "minor@example.com"}'
                    )
                }
            ]
        },
        None,
    )

    assert result["processed"] == [
        {
            "stored": False,
            "reason": "already_exists",
            "pk": "EVENT#1996475418721",
            "sk": "ATTENDEE#22793113508",
        }
    ]
