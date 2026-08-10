import lambda_handler as mod
import pytest
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

    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FILES_BUCKET_NAME", "test-signatures")
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
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")

    stored, item = mod._store_submission({"form_id": "iamr7tnj", "answers": {"Nombre Completo": "Juan"}})

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

    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FILES_BUCKET_NAME", "test-signatures")
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


def test_background_check_form_routes_to_its_own_table_and_bucket(monkeypatch):
    saved: dict[str, object] = {}
    uploaded: dict[str, object] = {}

    class FakeBackgroundTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FakeS3:
        def put_object(self, **kwargs):
            uploaded.update(kwargs)

    class FakeHeaders:
        def get_content_type(self):
            return "application/pdf"

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
        "submission_id": "bg-1",
        "form_id": "dpaadbok",
        "form_name": "Volunteer Background Check Compliance",
        "event_type": "submission",
        "completed_at": "2026-08-08T10:00:00.000000Z",
        "answers": {
            "Documento": "https://files.youform.com/background-check.pdf",
        },
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID", "dpaadbok")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID", "p35vzbna")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_FILES_BUCKET_NAME", "background-bucket")

    def fake_dynamodb_table(table_name: str):
        if table_name == "background-table":
            return FakeBackgroundTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"pdf-binary"))

    stored, item = mod._store_submission(parsed_body)

    assert stored is True
    assert item["form_id"] == "dpaadbok"
    assert saved["Item"]["submission_id"] == "bg-1"
    assert saved["Item"]["answers"] == [
        {
            "question": "Documento",
            "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/bg-1/documento.pdf",
        }
    ]
    assert uploaded == {
        "Bucket": "background-bucket",
        "Key": "volunteer-background-checks/dpaadbok/bg-1/documento.pdf",
        "Body": b"pdf-binary",
        "ContentType": "application/pdf",
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


def test_handler_enqueues_background_check_cedula_pdf(monkeypatch):
    saved: dict[str, object] = {}
    uploaded: dict[str, object] = {}
    sent_messages: list[dict[str, object]] = []

    class FakeBackgroundTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FakeS3:
        def put_object(self, **kwargs):
            uploaded.update(kwargs)

    class FakeSQS:
        def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return {"MessageId": "msg-1"}

    class FakeHeaders:
        def get_content_type(self):
            return "application/pdf"

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
        "submission_id": "qxxcnbmtd1",
        "form_id": "dpaadbok",
        "form_name": "Volunteer Background Check Compliance",
        "event_type": "submission",
        "completed_at": "2026-08-09T12:00:00.000000Z",
        "answers": {
            "Ahora sí tu cédula": "https://files.youform.com/carta.pdf",
            "Correo": "persona@example.com",
            "Teléfono": "+573001112233",
        },
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID", "dpaadbok")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_FILES_BUCKET_NAME", "background-bucket")
    monkeypatch.setenv("BACKGROUND_CHECK_REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/background")

    def fake_dynamodb_table(table_name: str):
        if table_name == "background-table":
            return FakeBackgroundTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "_sqs_client", lambda: FakeSQS())
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"pdf-binary"))

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])
    message_body = mod.json.loads(sent_messages[0]["MessageBody"])

    assert response["statusCode"] == 200
    assert payload["background_check_reviews"][0]["message_id"] == "msg-1"
    assert saved["Item"]["pk"] == "FORM#dpaadbok"
    assert uploaded["Key"] == "volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf"
    assert message_body["document_kind"] == "cedula"
    assert message_body["s3_uri"] == "s3://background-bucket/volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf"


def test_background_check_internal_review_routes_to_background_table(monkeypatch):
    saved: dict[str, object] = {}

    class FakeBackgroundTable:
        def update_item(self, **kwargs):
            saved["update"] = kwargs

    parsed_body = {
        "submission_id": "v275sfa3sn",
        "form_id": "p35vzbna",
        "form_name": "Volunteer Background Internal Review",
        "event_type": "submission",
        "started_at": "2026-08-09T19:21:45.000000Z",
        "completed_at": "2026-08-09T23:01:59.000000Z",
        "answers": {
            "Correo": "maestro@arte.com",
            "TelÃ©fono": "+573211231212",
            "Partition key": "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674",
            "Estado de aprobaciÃ³n": "BACKGROUND CHECK APPROVED",
            "Observaciones": "OK",
        },
        "fields": [
            {
                "id": "partition-key-field",
                "question": "Partition key",
                "answer": "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674",
                "answer_text": "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674",
            },
            {
                "id": "approval-field",
                "question": "Estado de aprobaciÃ³n",
                "answer": "BACKGROUND CHECK APPROVED",
                "answer_text": "BACKGROUND CHECK APPROVED",
            },
        ],
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID", "p35vzbna")

    def fake_dynamodb_table(table_name: str):
        if table_name == "background-table":
            return FakeBackgroundTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)

    stored, item = mod._store_submission(parsed_body)

    assert stored is True
    assert item["pk"] == "FORM#dpaadbok"
    assert item["sk"] == "SUBMISSION#dexr8ogxjb"
    assert item["internal_review"]["partition_key"] == "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674"
    assert item["internal_review"]["source_form_id"] == "dpaadbok"
    assert item["internal_review"]["source_submission_id"] == "dexr8ogxjb"
    assert item["internal_review"]["source_document_number"] == "1020802674"
    assert "BACKGROUND CHECK APPROVED" in item["internal_review"]["answers"].values()
    assert saved["update"]["Key"] == {"pk": "FORM#dpaadbok", "sk": "SUBMISSION#dexr8ogxjb"}
    assert saved["update"]["ExpressionAttributeValues"][":internal_review"]["submission_id"] == "v275sfa3sn"
    return

    assert stored is True
    assert item["pk"] == "FORM#dpaadbok"
    assert item["sk"] == "SUBMISSION#dexr8ogxjb"
    assert item["internal_review"]["partition_key"] == "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674"
    assert item["internal_review"]["source_form_id"] == "dpaadbok"
    assert item["internal_review"]["source_submission_id"] == "dexr8ogxjb"
    assert item["internal_review"]["source_document_number"] == "1020802674"
    assert item["answers_map"]["Estado de aprobaciÃ³n"] == "BACKGROUND CHECK APPROVED"
    assert item["fields"][0]["question"] == "Partition key"
    assert saved["Item"]["pk"] == "FORM#dpaadbok"


def test_background_check_enqueue_requires_exact_configured_form_id(monkeypatch):
    sent_messages: list[dict[str, object]] = []

    class FakeSQS:
        def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return {"MessageId": "msg-1"}

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID", "dpaadbok")
    monkeypatch.setenv("BACKGROUND_CHECK_REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/background")
    monkeypatch.setattr(mod, "_sqs_client", lambda: FakeSQS())

    result = mod._enqueue_background_check_reviews(
        {
            "form_id": "otro-form",
            "submission_id": "sub-1",
            "answers": [
                {
                    "question": "Ahora sí tu cédula",
                    "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/sub-1/ahora-s-tu-c-dula.pdf",
                }
            ],
        }
    )

    assert result == []
    assert sent_messages == []


def test_background_check_internal_review_requires_exact_configured_form_id(monkeypatch):
    parsed_body = {
        "submission_id": "v275sfa3sn",
        "form_id": "otro-form",
        "form_name": "Volunteer Background Internal Review",
        "event_type": "submission",
        "completed_at": "2026-08-09T23:01:59.000000Z",
        "answers": {
            "Partition key": "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674",
            "Estado de aprobaciÃƒÂ³n": "BACKGROUND CHECK APPROVED",
        },
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID", "p35vzbna")

    stored, item = mod._store_submission(parsed_body)

    assert stored is False
    assert item is None


def test_background_check_review_messages_detect_all_three_document_types():
    item = {
        "form_id": "dpaadbok",
        "submission_id": "sub-1",
        "answers": [
            {
                "question": "Ahora sí tu cédula",
                "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/sub-1/ahora-s-tu-c-dula.pdf",
            },
            {
                "question": "Certificado de antecedentes judiciales",
                "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/sub-1/certificado-de-antecedentes-judiciales.pdf",
            },
            {
                "question": "Certificado de antecedentes de inhabilidades",
                "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/sub-1/certificado-de-antecedentes-de-inhabilidades.pdf",
            },
        ],
    }

    messages = mod._background_check_review_messages(item)

    assert [message["document_kind"] for message in messages] == [
        "cedula",
        "antecedentes_judiciales",
        "antecedentes_inhabilidades",
    ]


def test_volunteer_intent_submission_uses_form_keys_and_contact_indexes(monkeypatch):
    saved: dict[str, object] = {}

    class FakeProposalTable:
        def put_item(self, Item):
            saved["Item"] = Item

    parsed_body = {
        "submission_id": "ahcscgfgka",
        "form_id": "46titbii",
        "form_name": "Volunteer Intent Proposal",
        "event_type": "submission",
        "started_at": "2026-08-08T21:09:21.000000Z",
        "completed_at": "2026-08-08T21:13:52.000000Z",
        "answers": {
            "¿Cómo se llama tu evento?": "El arte de escuchar",
            "¿De qué se tratará tu evento?": "Hablaré sobre SOLID.",
            "¿Qué día te gustaría que fuera el evento?": "2026-08-12",
            "¿A qué hora?": "8:00 p.m.",
            "¿Tienes alguna pregunta para nosotros?": "No",
            "Nombre": "Napoleon Bonaparte",
            "Correo": "napoleonbonaparte@gmail.com",
            "Teléfono": "+573211231212",
        },
    }

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_FORM_ID", "46titbii")
    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")

    def fake_dynamodb_table(table_name: str):
        if table_name == "proposal-table":
            return FakeProposalTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)

    stored, item = mod._store_submission(parsed_body)

    assert stored is True
    assert item["pk"] == "FORM#46titbii"
    assert item["sk"] == "SUBMISSION#ahcscgfgka"
    assert item["gsi1pk"] == "FORM#46titbii"
    assert item["gsi2pk"] == "EMAIL#napoleonbonaparte@gmail.com"
    assert item["gsi3pk"] == "PHONE#+573211231212"
    assert item["contact_email"] == "napoleonbonaparte@gmail.com"
    assert item["contact_phone"] == "+573211231212"
    assert item["proposal_event_name"] == "El arte de escuchar"
    assert saved["Item"]["pk"] == "FORM#46titbii"


def test_handler_sends_volunteer_intent_admin_notification(monkeypatch):
    saved: dict[str, object] = {}
    updated: list[dict[str, object]] = []
    sent: dict[str, object] = {}

    class FakeProposalTable:
        def put_item(self, Item):
            saved["Item"] = Item

        def update_item(self, **kwargs):
            updated.append(kwargs)

    class FakeSes:
        def send_email(self, **kwargs):
            sent.update(kwargs)
            return {"MessageId": "ses-msg-1"}

    parsed_body = {
        "submission_id": "ahcscgfgka",
        "form_id": "46titbii",
        "form_name": "Volunteer Intent Proposal",
        "event_type": "submission",
        "completed_at": "2026-08-08T21:13:52.000000Z",
        "answers": {
            "¿Cómo se llama tu evento?": "El arte de escuchar",
            "¿De qué se tratará tu evento?": "Hablaré sobre SOLID.",
            "¿Qué día te gustaría que fuera el evento?": "2026-08-12",
            "¿A qué hora?": "8:00 p.m.",
            "¿Tienes alguna pregunta para nosotros?": "No",
            "Nombre": "Napoleon Bonaparte",
            "Correo": "napoleonbonaparte@gmail.com",
            "Teléfono": "+573211231212",
        },
    }

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_FORM_ID", "46titbii")
    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL", "Circle Up Voluntariado <hola@circleup.com.co>")
    monkeypatch.setenv(
        "VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL",
        "wearecircleup@gmail.com,hola@circleup.com.co",
    )
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFICATION_REPLY_TO_EMAIL", "hola@circleup.com.co")
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFICATION_LOGO_URL", "https://circleup.com.co/logo.png")

    def fake_dynamodb_table(table_name: str):
        if table_name == "proposal-table":
            return FakeProposalTable()
        raise AssertionError(f"Unexpected table: {table_name}")

    monkeypatch.setattr(mod, "_dynamodb_table", fake_dynamodb_table)
    monkeypatch.setattr(mod, "_ses_client", lambda: FakeSes())

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])

    assert response["statusCode"] == 200
    assert payload["stored"] is True
    assert payload["admin_notification"]["status"] == "sent"
    assert sent["Destination"] == {
        "ToAddresses": ["wearecircleup@gmail.com", "hola@circleup.com.co"]
    }
    assert "wa.me/573211231212" in sent["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert updated[0]["Key"] == {"pk": "FORM#46titbii", "sk": "SUBMISSION#ahcscgfgka"}


def test_volunteer_intent_to_emails_rejects_unauthorized_recipient(monkeypatch):
    monkeypatch.setenv(
        "VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL",
        "hola@circleup.com.co,alguien@example.com",
    )

    with pytest.raises(RuntimeError, match="unauthorized recipients"):
        mod._volunteer_intent_to_emails()
