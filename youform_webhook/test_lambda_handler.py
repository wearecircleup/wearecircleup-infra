import lambda_handler as mod
from urllib.error import HTTPError


def test_store_submission_copies_signature_to_s3_persists_and_reconciles_job(monkeypatch):
    saved: dict[str, object] = {}
    uploaded: dict[str, object] = {}
    updated_jobs: list[dict[str, object]] = []

    class FakeSubmissionsTable:
        def put_item(self, Item):
            saved["Item"] = Item

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

    class FakeS3:
        def put_object(self, **kwargs):
            uploaded.update(kwargs)

    class FakeHeaders:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        def __init__(self, content: bytes):
            self._content = content
            self.headers = FakeHeaders()

        def read(self):
            return self._content

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    parsed_body = {
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "answers": {
            "Nombre Completo": "Juan Mesa",
            "Â¿A quÃ© evento asiste?": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
            "Â¿QuÃ© dÃ­a es el evento?": "2026-08-05",
            "Â¿Con quÃ© correo vas a realizar la inscripciÃ³n?": "GoCircleUp@gmail.com",
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("SIGNATURES_BUCKET_NAME", "test-signatures")
    monkeypatch.setenv("MINOR_AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")

    def fake_dynamodb_table(table_name: str):
        if table_name == "test-table":
            return FakeSubmissionsTable()
        if table_name == "test-jobs":
            return FakeJobsTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"png-binary"))

    stored, item = mod._store_submission(parsed_body)
    reconciliation = mod._reconcile_minor_authorization_job(item)

    assert stored is True
    assert uploaded == {
        "Bucket": "test-signatures",
        "Key": "youform-signatures/2jgxyorbkf/signature.png",
        "Body": b"png-binary",
        "ContentType": "image/png",
    }
    assert saved["Item"] == {
        "pk": "EVENT#1996461512126#FORM#iamr7tnj",
        "sk": "SUBMISSION#2jgxyorbkf",
        "gsi1pk": "EVENT#1996461512126",
        "gsi1sk": "COMPLETED_AT#2026-08-03T15:32:33.000000Z#SUBMISSION#2jgxyorbkf",
        "gsi2pk": "EMAIL#gocircleup@gmail.com",
        "gsi2sk": "EVENT_DATE#2026-08-05#EVENT#1996461512126#SUBMISSION#2jgxyorbkf",
        "gsi3pk": "EVENT_DATE#2026-08-05",
        "gsi3sk": "EVENT#1996461512126#EMAIL#gocircleup@gmail.com#SUBMISSION#2jgxyorbkf",
        "entity_type": "youform_submission",
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "youform_event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "eventbrite_event_id": "1996461512126",
        "eventbrite_event_slug": "architecture",
        "eventbrite_event_name": "architecture",
        "eventbrite_event_url": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
        "event_date": "2026-08-05",
        "registration_email": "gocircleup@gmail.com",
        "answers": [
            {"question": "Nombre Completo", "answer": "Juan Mesa"},
            {
                "question": "Â¿A quÃ© evento asiste?",
                "answer": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
            },
            {"question": "Â¿QuÃ© dÃ­a es el evento?", "answer": "2026-08-05"},
            {
                "question": "Â¿Con quÃ© correo vas a realizar la inscripciÃ³n?",
                "answer": "GoCircleUp@gmail.com",
            },
            {
                "question": "Firma para autorizar",
                "answer": "s3://test-signatures/youform-signatures/2jgxyorbkf/signature.png",
            },
        ],
    }
    assert reconciliation == {
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
    assert updated_jobs[0]["ExpressionAttributeValues"][":validation_result"] == "form_found"
    assert updated_jobs[0]["ExpressionAttributeValues"][":authorization_found"] is True
    assert updated_jobs[0]["ExpressionAttributeValues"][":matched_submission_id"] == "2jgxyorbkf"
    assert updated_jobs[0]["ExpressionAttributeValues"][":gsi1pk"] == "STATUS#authorized"


def test_store_submission_skips_without_submission_id(monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")

    stored, item = mod._store_submission({"answers": {"Nombre Completo": "Juan"}})

    assert stored is False
    assert item is None


def test_store_submission_keeps_original_signature_url_when_copy_fails_and_no_job_matches(monkeypatch):
    saved: dict[str, object] = {}

    class FakeSubmissionsTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FakeJobsTable:
        def query(self, **kwargs):
            return {"Items": []}

        def update_item(self, **kwargs):
            raise AssertionError("update_item should not be called when no job matches")

    parsed_body = {
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "answers": {
            "Â¿A quÃ© evento asiste?": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
            "Â¿QuÃ© dÃ­a es el evento?": "2026-08-05",
            "Â¿Con quÃ© correo vas a realizar la inscripciÃ³n?": "GoCircleUp@gmail.com",
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("SIGNATURES_BUCKET_NAME", "test-signatures")
    monkeypatch.setenv("MINOR_AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")

    def fake_dynamodb_table(table_name: str):
        if table_name == "test-table":
            return FakeSubmissionsTable()
        if table_name == "test-jobs":
            return FakeJobsTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)

    def fail_download(_: str):
        raise HTTPError(
            "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
            403,
            "Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(mod, "_download_signature", fail_download)

    stored, item = mod._store_submission(parsed_body)
    reconciliation = mod._reconcile_minor_authorization_job(item)

    assert stored is True
    assert saved["Item"]["pk"] == "EVENT#1996461512126#FORM#iamr7tnj"
    assert saved["Item"]["gsi2pk"] == "EMAIL#gocircleup@gmail.com"
    assert saved["Item"]["gsi3pk"] == "EVENT_DATE#2026-08-05"
    assert saved["Item"]["answers"] == [
        {
            "question": "Â¿A quÃ© evento asiste?",
            "answer": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
        },
        {"question": "Â¿QuÃ© dÃ­a es el evento?", "answer": "2026-08-05"},
        {
            "question": "Â¿Con quÃ© correo vas a realizar la inscripciÃ³n?",
            "answer": "GoCircleUp@gmail.com",
        },
        {
            "question": "Firma para autorizar",
            "answer": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    ]
    assert reconciliation == {
        "reconciled": False,
        "reason": "no_matching_job",
    }


def test_reconciliation_skips_non_authorized_form(monkeypatch):
    class FakeJobsTable:
        def query(self, **kwargs):
            raise AssertionError("query should not be called for non-authorized forms")

    monkeypatch.setenv("MINOR_AUTHORIZATION_JOBS_TABLE_NAME", "test-jobs")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setattr(mod, "_minor_authorization_jobs_table", lambda: FakeJobsTable())

    reconciliation = mod._reconcile_minor_authorization_job(
        {
            "form_id": "another-form",
            "eventbrite_event_id": "1996461512126",
            "registration_email": "gocircleup@gmail.com",
            "submission_id": "sub-1",
            "completed_at": "2026-08-03T15:32:33.000000Z",
        }
    )

    assert reconciliation == {
        "reconciled": False,
        "reason": "form_id_not_authorized",
    }
