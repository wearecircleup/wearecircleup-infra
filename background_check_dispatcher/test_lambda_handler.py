import json

import lambda_handler as mod


def test_handler_dispatches_background_check_cedula_pdf(monkeypatch):
    sent_messages: list[dict[str, object]] = []

    class FakeSQS:
        def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return {"MessageId": "msg-1"}

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID", "dpaadbok")
    monkeypatch.setenv("BACKGROUND_CHECK_REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/background")
    monkeypatch.setattr(mod, "_sqs_client", lambda: FakeSQS())

    response = mod.handler(
        {
            "pk": "FORM#dpaadbok",
            "sk": "SUBMISSION#qxxcnbmtd1",
            "submission_id": "qxxcnbmtd1",
            "form_id": "dpaadbok",
            "contact_email": "persona@example.com",
            "contact_phone": "+573001112233",
            "answers": [
                {
                    "question": "Ahora sí tu cédula",
                    "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf",
                }
            ],
        },
        None,
    )
    payload = json.loads(response["body"])
    message_body = json.loads(sent_messages[0]["MessageBody"])

    assert response["statusCode"] == 200
    assert payload["dispatched"] is True
    assert payload["job_count"] == 1
    assert message_body["document_kind"] == "cedula"


def test_handler_requires_exact_configured_form_id(monkeypatch):
    sent_messages: list[dict[str, object]] = []

    class FakeSQS:
        def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return {"MessageId": "msg-1"}

    monkeypatch.setenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID", "dpaadbok")
    monkeypatch.setenv("BACKGROUND_CHECK_REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/background")
    monkeypatch.setattr(mod, "_sqs_client", lambda: FakeSQS())

    response = mod.handler(
        {
            "form_id": "otro-form",
            "submission_id": "sub-1",
            "answers": [
                {
                    "question": "Ahora sí tu cédula",
                    "answer": "s3://background-bucket/volunteer-background-checks/dpaadbok/sub-1/ahora-s-tu-c-dula.pdf",
                }
            ],
        },
        None,
    )

    assert json.loads(response["body"]) == {
        "dispatched": False,
        "reason": "form_id_mismatch",
        "submission_id": "sub-1",
    }
    assert sent_messages == []


def test_review_messages_detect_all_three_document_types():
    messages = mod._review_messages(
        {
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
    )

    assert [message["document_kind"] for message in messages] == [
        "cedula",
        "antecedentes_judiciales",
        "antecedentes_inhabilidades",
    ]
