import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("lambda_handler.py")
SPEC = importlib.util.spec_from_file_location("background_check_reviewer_lambda_handler", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_process_job_ignores_wrong_form(monkeypatch):
    monkeypatch.setattr(mod, "_background_check_form_id", lambda: "dpaadbok")

    result = mod._process_job(
        {
            "form_id": "other-form",
            "submission_id": "sub-1",
            "document_kind": "cedula",
        }
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "form_id_mismatch"


def test_process_job_stores_completed_review(monkeypatch):
    stored: list[dict] = []

    monkeypatch.setattr(mod, "_background_check_form_id", lambda: "dpaadbok")
    monkeypatch.setattr(mod, "_source_submission", lambda job: {"contact_email": "persona@example.com"})
    monkeypatch.setattr(mod, "_download_pdf", lambda bucket, key: b"%PDF-1.4")
    monkeypatch.setattr(mod, "_render_pdf_pages", lambda pdf_bytes, max_pages: [b"png-page"])
    monkeypatch.setattr(
        mod,
        "_extract_document_with_bedrock",
        lambda images: {
            "tool_input": {
                "document_type": "cedula_pre_2020",
                "side_processed": "frente",
                "fields": {
                    "numero_documento": {"value": "123", "confidence": "confiable"},
                    "apellidos": {"value": "Diaz", "confidence": "confiable"},
                    "nombres": {"value": "Nicolas", "confidence": "confiable"},
                },
            },
            "usage": {"inputTokens": 1, "outputTokens": 1},
            "stop_reason": "tool_use",
        },
    )
    monkeypatch.setattr(mod, "_bedrock_model_id", lambda: "anthropic.claude-sonnet-5")
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))

    result = mod._process_job(
        {
            "form_id": "dpaadbok",
            "submission_id": "qxxcnbmtd1",
            "submission_pk": "FORM#dpaadbok",
            "submission_sk": "SUBMISSION#qxxcnbmtd1",
            "document_kind": "cedula",
            "question": "Ahora sí tu cédula",
            "s3_uri": "s3://bucket/volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf",
            "s3_bucket": "bucket",
            "s3_key": "volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf",
            "contact_name": "Nicolas Diaz",
            "contact_email": "persona@example.com",
        }
    )

    assert result["status"] == "completed"
    assert stored[0]["pk"] == "FORM#dpaadbok"
    assert stored[0]["sk"] == "SUBMISSION#qxxcnbmtd1#DOCUMENT#cedula"
    assert stored[0]["status"] == "completed"
    assert stored[0]["review_payload"]["document_type"] == "cedula_pre_2020"


def test_handler_records_failure_and_raises(monkeypatch):
    stored: list[dict] = []

    monkeypatch.setattr(mod, "_process_job", lambda job: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(mod, "_source_submission", lambda job: {"contact_email": "persona@example.com"})
    monkeypatch.setattr(mod, "_bedrock_model_id", lambda: "anthropic.claude-sonnet-5")
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))

    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "form_id": "dpaadbok",
                        "submission_id": "sub-1",
                        "submission_pk": "FORM#dpaadbok",
                        "submission_sk": "SUBMISSION#sub-1",
                        "document_kind": "cedula",
                    }
                )
            }
        ]
    }

    try:
        mod.handler(event, None)
        raised = False
    except RuntimeError as exc:
        raised = str(exc) == "boom"

    assert raised is True
    assert stored[0]["status"] == "failed"
