import json

import lambda_handler as mod


def test_handler_reconciles_authorized_minor_submission(monkeypatch):
    updated_jobs: list[dict[str, object]] = []

    class FakeJobsTable:
        def query(self, **kwargs):
            assert kwargs["IndexName"] == "gsi2"
            return {
                "Items": [
                    {
                        "pk": "EVENT#1996461512126",
                        "sk": "ATTENDEE#22793263885",
                        "event_id": "1996461512126",
                        "attendee_id": "22793263885",
                        "status": "missing_form",
                    }
                ]
            }

        def update_item(self, **kwargs):
            updated_jobs.append(kwargs)

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeJobsTable())

    response = mod.handler(
        {
            "form_id": "iamr7tnj",
            "eventbrite_event_id": "1996461512126",
            "registration_email": "gocircleup@gmail.com",
            "submission_id": "2jgxyorbkf",
            "completed_at": "2026-08-03T15:32:33.000000Z",
        },
        None,
    )
    payload = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert payload == {
        "reconciled": True,
        "updated_jobs": [
            {
                "pk": "EVENT#1996461512126",
                "sk": "ATTENDEE#22793263885",
            }
        ],
        "submission_id": "2jgxyorbkf",
    }
    assert updated_jobs[0]["Key"] == {
        "pk": "EVENT#1996461512126",
        "sk": "ATTENDEE#22793263885",
    }
    assert updated_jobs[0]["ExpressionAttributeValues"][":status"] == "authorized"


def test_handler_skips_non_authorized_form(monkeypatch):
    class FakeJobsTable:
        def query(self, **kwargs):
            raise AssertionError("query should not be called for non-authorized forms")

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeJobsTable())

    response = mod.handler(
        {
            "form_id": "another-form",
            "eventbrite_event_id": "1996461512126",
            "registration_email": "gocircleup@gmail.com",
            "submission_id": "sub-1",
            "completed_at": "2026-08-03T15:32:33.000000Z",
        },
        None,
    )

    assert json.loads(response["body"]) == {
        "reconciled": False,
        "reason": "form_id_not_authorized",
    }


def test_handler_returns_no_matching_job(monkeypatch):
    class FakeJobsTable:
        def query(self, **kwargs):
            return {"Items": []}

        def update_item(self, **kwargs):
            raise AssertionError("update_item should not be called when no job matches")

    monkeypatch.setenv("AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setattr(mod, "_jobs_table", lambda: FakeJobsTable())

    response = mod.handler(
        {
            "form_id": "iamr7tnj",
            "eventbrite_event_id": "1996461512126",
            "registration_email": "gocircleup@gmail.com",
            "submission_id": "2jgxyorbkf",
            "completed_at": "2026-08-03T15:32:33.000000Z",
        },
        None,
    )

    assert json.loads(response["body"]) == {
        "reconciled": False,
        "reason": "no_matching_job",
    }
