import json
from urllib.error import HTTPError

import lambda_handler as mod


def test_store_submission_copies_signature_to_s3_and_persists(monkeypatch):
    saved: dict[str, object] = {}
    uploaded: dict[str, object] = {}

    class FakeSubmissionsTable:
        def put_item(self, Item):
            saved["Item"] = Item

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
            "Ã‚Â¿A quÃƒÂ© evento asiste?": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
            "Ã‚Â¿QuÃƒÂ© dÃƒÂ­a es el evento?": "2026-08-05",
            "Ã‚Â¿Con quÃƒÂ© correo vas a realizar la inscripciÃƒÂ³n?": "GoCircleUp@gmail.com",
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FILES_BUCKET_NAME", "test-signatures")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")

    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeSubmissionsTable())
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"png-binary"))

    stored, _item = mod._store_submission(parsed_body)

    assert stored is True
    assert uploaded == {
        "Bucket": "test-signatures",
        "Key": "youform-signatures/2jgxyorbkf/signature.png",
        "Body": b"png-binary",
        "ContentType": "image/png",
    }
    assert saved["Item"]["pk"] == "EVENT#1996461512126#FORM#iamr7tnj"
    assert saved["Item"]["registration_email"] == "gocircleup@gmail.com"


def test_store_submission_skips_without_submission_id(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")

    stored, item = mod._store_submission({"form_id": "iamr7tnj", "answers": {"Nombre Completo": "Juan"}})

    assert stored is False
    assert item is None


def test_store_submission_keeps_original_signature_url_when_copy_fails(monkeypatch):
    saved: dict[str, object] = {}

    class FakeSubmissionsTable:
        def put_item(self, Item):
            saved["Item"] = Item

    parsed_body = {
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "answers": {
            "Ã‚Â¿A quÃƒÂ© evento asiste?": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
            "Ã‚Â¿QuÃƒÂ© dÃƒÂ­a es el evento?": "2026-08-05",
            "Ã‚Â¿Con quÃƒÂ© correo vas a realizar la inscripciÃƒÂ³n?": "GoCircleUp@gmail.com",
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FILES_BUCKET_NAME", "test-signatures")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeSubmissionsTable())

    def fail_download(_: str):
        raise HTTPError(
            "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
            403,
            "Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(mod, "_download_signature", fail_download)

    stored, _item = mod._store_submission(parsed_body)

    assert stored is True
    assert saved["Item"]["answers"][-1]["answer"] == "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png"


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

    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeBackgroundTable())
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"pdf-binary"))

    stored, item = mod._store_submission(parsed_body)

    assert stored is True
    assert item["form_id"] == "dpaadbok"
    assert saved["Item"]["answers"] == [
        {
            "question": "Documento",
            "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/bg-1/documento.pdf",
        }
    ]
    assert uploaded["Key"] == "volunteer-background-checks/dpaadbok/bg-1/documento.pdf"


def test_handler_dispatches_background_check_cedula_pdf(monkeypatch):
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

    class FakeLambda:
        def __init__(self):
            self.invocations: list[dict[str, object]] = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {"StatusCode": 202}

    parsed_body = {
        "submission_id": "qxxcnbmtd1",
        "form_id": "dpaadbok",
        "form_name": "Volunteer Background Check Compliance",
        "event_type": "submission",
        "completed_at": "2026-08-09T12:00:00.000000Z",
        "answers": {
            "Ahora sÃ­ tu cÃ©dula": "https://files.youform.com/carta.pdf",
            "Correo": "persona@example.com",
            "TelÃ©fono": "+573001112233",
        },
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID", "dpaadbok")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_FILES_BUCKET_NAME", "background-bucket")
    monkeypatch.setenv("BACKGROUND_CHECK_DISPATCHER_FUNCTION_NAME", "background-check-dispatcher")

    fake_lambda = FakeLambda()
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeBackgroundTable())
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "_lambda_client", lambda: fake_lambda)
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"pdf-binary"))

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])
    invoke_payload = mod.json.loads(fake_lambda.invocations[0]["Payload"].decode("utf-8"))

    assert response["statusCode"] == 200
    assert payload["background_check_reviews"]["accepted"] is True
    assert fake_lambda.invocations[0]["FunctionName"] == "background-check-dispatcher"
    assert fake_lambda.invocations[0]["InvocationType"] == "Event"
    assert saved["Item"]["pk"] == "FORM#dpaadbok"
    assert uploaded["Key"] == "volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf"
    assert invoke_payload["answers"][0]["answer"] == "s3://background-bucket/volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf"


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
            "TelÃƒÂ©fono": "+573211231212",
            "Partition key": "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674",
            "Estado de aprobaciÃƒÂ³n": "BACKGROUND CHECK APPROVED",
            "Observaciones": "OK",
        },
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID", "p35vzbna")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeBackgroundTable())

    stored, item = mod._store_submission(parsed_body)

    assert stored is True
    assert item["pk"] == "FORM#dpaadbok"
    assert item["internal_review"]["source_document_number"] == "1020802674"
    assert saved["update"]["Key"] == {"pk": "FORM#dpaadbok", "sk": "SUBMISSION#dexr8ogxjb"}


def test_background_check_internal_review_requires_exact_configured_form_id(monkeypatch):
    parsed_body = {
        "submission_id": "v275sfa3sn",
        "form_id": "otro-form",
        "form_name": "Volunteer Background Internal Review",
        "event_type": "submission",
        "completed_at": "2026-08-09T23:01:59.000000Z",
        "answers": {
            "Partition key": "FORM#dpaadbok#SUBMISSION#dexr8ogxjb#DOCUMENT#1020802674",
            "Estado de aprobaciÃƒÆ’Ã‚Â³n": "BACKGROUND CHECK APPROVED",
        },
    }

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME", "background-table")
    monkeypatch.setenv("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID", "p35vzbna")

    stored, item = mod._store_submission(parsed_body)

    assert stored is False
    assert item is None


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
            "Â¿CÃ³mo se llama tu evento?": "El arte de escuchar",
            "Â¿De quÃ© se tratarÃ¡ tu evento?": "HablarÃ© sobre SOLID.",
            "Â¿QuÃ© dÃ­a te gustarÃ­a que fuera el evento?": "2026-08-12",
            "Â¿A quÃ© hora?": "8:00 p.m.",
            "Â¿Tienes alguna pregunta para nosotros?": "No",
            "Nombre": "Napoleon Bonaparte",
            "Correo": "napoleonbonaparte@gmail.com",
            "TelÃƒÂ©fono": "+573211231212",
        },
    }

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_FORM_ID", "46titbii")
    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeProposalTable())

    stored, item = mod._store_submission(parsed_body)

    assert stored is True
    assert item["pk"] == "FORM#46titbii"
    assert item["gsi2pk"] == "EMAIL#napoleonbonaparte@gmail.com"
    assert saved["Item"]["pk"] == "FORM#46titbii"


def test_handler_dispatches_volunteer_intent_notification(monkeypatch):
    saved: dict[str, object] = {}

    class FakeProposalTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FakeLambda:
        def __init__(self):
            self.invocations: list[dict[str, object]] = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {"StatusCode": 202}

    parsed_body = {
        "submission_id": "ahcscgfgka",
        "form_id": "46titbii",
        "form_name": "Volunteer Intent Proposal",
        "event_type": "submission",
        "completed_at": "2026-08-08T21:13:52.000000Z",
        "answers": {
            "Â¿CÃ³mo se llama tu evento?": "El arte de escuchar",
            "Â¿De quÃ© se tratarÃ¡ tu evento?": "HablarÃ© sobre SOLID.",
            "Â¿QuÃ© dÃ­a te gustarÃ­a que fuera el evento?": "2026-08-12",
            "Â¿A quÃ© hora?": "8:00 p.m.",
            "Â¿Tienes alguna pregunta para nosotros?": "No",
            "Nombre": "Napoleon Bonaparte",
            "Correo": "napoleonbonaparte@gmail.com",
            "TelÃ©fono": "+573211231212",
        },
    }

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_FORM_ID", "46titbii")
    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFIER_FUNCTION_NAME", "volunteer-intent-notifier")
    fake_lambda = FakeLambda()

    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeProposalTable())
    monkeypatch.setattr(mod, "_lambda_client", lambda: fake_lambda)

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])
    invoke_payload = mod.json.loads(fake_lambda.invocations[0]["Payload"].decode("utf-8"))

    assert response["statusCode"] == 200
    assert payload["stored"] is True
    assert payload["admin_notification"]["accepted"] is True
    assert fake_lambda.invocations[0]["FunctionName"] == "volunteer-intent-notifier"
    assert fake_lambda.invocations[0]["InvocationType"] == "Event"
    assert invoke_payload["pk"] == "FORM#46titbii"
    assert saved["Item"]["pk"] == "FORM#46titbii"


def test_handler_calls_minor_authorization_processor_synchronously(monkeypatch):
    class FakeSubmissionsTable:
        def put_item(self, Item):
            return None

    class FakeS3:
        def put_object(self, **kwargs):
            return None

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

    class FakePayload:
        def __init__(self, payload: str):
            self._payload = payload

        def read(self):
            return self._payload.encode("utf-8")

    class FakeLambda:
        def __init__(self):
            self.invocations: list[dict[str, object]] = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {
                "StatusCode": 200,
                "Payload": FakePayload(
                    json.dumps(
                        {
                            "statusCode": 200,
                            "body": json.dumps(
                                {
                                    "reconciled": True,
                                    "submission_id": "2jgxyorbkf",
                                    "updated_jobs": [{"pk": "EVENT#1", "sk": "ATTENDEE#1"}],
                                }
                            ),
                        }
                    )
                ),
            }

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
            "Ã‚Â¿A quÃƒÂ© evento asiste?": "https://www.eventbrite.co/e/architecture-tickets-1996461512126",
            "Ã‚Â¿QuÃƒÂ© dÃƒÂ­a es el evento?": "2026-08-05",
            "Ã‚Â¿Con quÃƒÂ© correo vas a realizar la inscripciÃƒÂ³n?": "GoCircleUp@gmail.com",
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("MINOR_AUTHORIZATION_FILES_BUCKET_NAME", "test-signatures")
    monkeypatch.setenv("AUTHORIZED_MINOR_FORM_ID", "iamr7tnj")
    monkeypatch.setenv("MINOR_AUTHORIZATION_PROCESSOR_FUNCTION_NAME", "minor-authorization-processor")

    fake_lambda = FakeLambda()
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeSubmissionsTable())
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "_lambda_client", lambda: fake_lambda)
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"png-binary"))

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])

    assert response["statusCode"] == 200
    assert payload["reconciliation"]["reconciled"] is True
    assert fake_lambda.invocations[0]["FunctionName"] == "minor-authorization-processor"
    assert fake_lambda.invocations[0]["InvocationType"] == "RequestResponse"


def test_handler_rejects_invalid_json():
    response = mod.handler({"body": "{"}, None)
    payload = mod.json.loads(response["body"])

    assert response["statusCode"] == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_payload"


def test_handler_reports_storage_error(monkeypatch):
    class FailingTable:
        def put_item(self, Item):
            raise RuntimeError("ddb down")

    parsed_body = {
        "submission_id": "ahcscgfgka",
        "form_id": "46titbii",
        "form_name": "Volunteer Intent Proposal",
        "event_type": "submission",
        "completed_at": "2026-08-08T21:13:52.000000Z",
        "answers": {"Nombre": "Napoleon"},
    }

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_FORM_ID", "46titbii")
    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FailingTable())

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])

    assert response["statusCode"] == 500
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["stored"] is False


def test_handler_reports_downstream_invoke_error_after_store(monkeypatch):
    saved: dict[str, object] = {}

    class FakeProposalTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FailingLambda:
        def invoke(self, **kwargs):
            raise RuntimeError("lambda invoke failed")

    parsed_body = {
        "submission_id": "ahcscgfgka",
        "form_id": "46titbii",
        "form_name": "Volunteer Intent Proposal",
        "event_type": "submission",
        "completed_at": "2026-08-08T21:13:52.000000Z",
        "answers": {
            "Nombre": "Napoleon Bonaparte",
            "Correo": "napoleonbonaparte@gmail.com",
        },
    }

    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_FORM_ID", "46titbii")
    monkeypatch.setenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME", "proposal-table")
    monkeypatch.setenv("VOLUNTEER_INTENT_NOTIFIER_FUNCTION_NAME", "volunteer-intent-notifier")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeProposalTable())
    monkeypatch.setattr(mod, "_lambda_client", lambda: FailingLambda())

    response = mod.handler({"body": mod.json.dumps(parsed_body)}, None)
    payload = mod.json.loads(response["body"])

    assert response["statusCode"] == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "downstream_invoke_error"
    assert payload["stored"] is True
    assert saved["Item"]["pk"] == "FORM#46titbii"
