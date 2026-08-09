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
    monkeypatch.setattr(mod, "_render_pdf_pages", lambda pdf_bytes, max_pages: [b"png-page-1"])
    monkeypatch.setattr(
        mod,
        "_extract_document_with_bedrock",
        lambda images: {
            "tool_input": {
                "document_type": "cedula_pre_2020",
                "document_country": "colombia",
                "both_sides_present": True,
                "side_processed": "unica",
                "fields": {
                    "numero_documento": {"value": "123", "confidence": "confiable"},
                    "apellidos": {"value": "Bonaparte", "confidence": "confiable"},
                    "nombres": {"value": "Napoleon", "confidence": "confiable"},
                },
            },
            "usage": {"inputTokens": 1, "outputTokens": 1},
            "stop_reason": "tool_use",
        },
    )
    monkeypatch.setattr(mod, "_bedrock_model_id", lambda: "anthropic.claude-sonnet-5")
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))
    monkeypatch.setattr(
        mod,
        "_store_final_review_summary",
        lambda form_id, submission_id: {"final_review_status": "pending_documents"},
    )

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
            "contact_name": "Napoleon Bonaparte",
            "contact_email": "persona@example.com",
        }
    )

    assert result["status"] == "completed"
    assert stored[0]["pk"] == "FORM#dpaadbok"
    assert stored[0]["sk"] == "SUBMISSION#qxxcnbmtd1#DOCUMENT#cedula"
    assert stored[0]["status"] == "completed"
    assert stored[0]["review_payload"]["document_type"] == "cedula_pre_2020"
    assert stored[0]["validation_status"] == "valid"
    assert stored[0]["both_sides_present"] is True
    assert stored[0]["rendered_page_count"] == 1


def test_process_job_marks_invalid_when_pdf_is_not_colombian_cedula(monkeypatch):
    stored: list[dict] = []

    monkeypatch.setattr(mod, "_background_check_form_id", lambda: "dpaadbok")
    monkeypatch.setattr(mod, "_source_submission", lambda job: {"contact_email": "persona@example.com"})
    monkeypatch.setattr(mod, "_download_pdf", lambda bucket, key: b"%PDF-1.4")
    monkeypatch.setattr(mod, "_render_pdf_pages", lambda pdf_bytes, max_pages: [b"png-page-1", b"png-page-2"])
    monkeypatch.setattr(
        mod,
        "_extract_document_with_bedrock",
        lambda images: {
            "tool_input": {
                "document_type": "unsupported_document",
                "document_country": "otro",
                "both_sides_present": False,
                "side_processed": "unica",
                "fields": {
                    "numero_documento": {"value": None, "confidence": "no_aplica"},
                    "apellidos": {"value": None, "confidence": "no_aplica"},
                    "nombres": {"value": None, "confidence": "no_aplica"},
                },
            },
            "usage": {"inputTokens": 1, "outputTokens": 1},
            "stop_reason": "tool_use",
        },
    )
    monkeypatch.setattr(mod, "_bedrock_model_id", lambda: "anthropic.claude-sonnet-5")
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))
    monkeypatch.setattr(
        mod,
        "_store_final_review_summary",
        lambda form_id, submission_id: {"final_review_status": "rejected"},
    )

    result = mod._process_job(
        {
            "form_id": "dpaadbok",
            "submission_id": "qxxcnbmtd1",
            "submission_pk": "FORM#dpaadbok",
            "submission_sk": "SUBMISSION#qxxcnbmtd1",
            "document_kind": "cedula",
            "question": "Ahora sÃ­ tu cÃ©dula",
            "s3_uri": "s3://bucket/volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf",
            "s3_bucket": "bucket",
            "s3_key": "volunteer-background-checks/dpaadbok/qxxcnbmtd1/ahora-s-tu-c-dula.pdf",
            "contact_name": "Napoleon Bonaparte",
            "contact_email": "persona@example.com",
        }
    )

    assert result["status"] == "completed"
    assert stored[0]["validation_status"] == "invalid"
    assert "unsupported_identity_document" in stored[0]["validation_errors"]
    assert "document_not_colombian" in stored[0]["validation_errors"]
    assert "both_sides_not_detected" in stored[0]["validation_errors"]


def test_process_job_uses_textract_for_judicial_certificate(monkeypatch):
    stored: list[dict] = []

    monkeypatch.setattr(mod, "_background_check_form_id", lambda: "dpaadbok")
    monkeypatch.setattr(mod, "_source_submission", lambda job: {"contact_email": "persona@example.com"})
    monkeypatch.setattr(mod, "_download_pdf", lambda bucket, key: b"%PDF-1.4")
    monkeypatch.setattr(
        mod,
        "_get_review_item",
        lambda form_id, submission_id, document_kind: {
            "review_payload": {
                "fields": {
                    "numero_documento": {"value": "1020802674", "confidence": "confiable"},
                    "apellidos": {"value": "BONAPARTE", "confidence": "confiable"},
                    "nombres": {"value": "NAPOLEON", "confidence": "confiable"},
                }
            }
        }
        if document_kind == "cedula"
        else None,
    )
    monkeypatch.setattr(
        mod,
        "_extract_text_with_textract",
        lambda pdf_bytes: {
            "lines": [
                "Consulta en línea de Antecedentes Penales y Requerimientos Judiciales",
                "Que siendo las 08:13:16 AM horas del 09/08/2026, el ciudadano identificado con:",
                "Cédula de Ciudadanía N° 1020802674",
                "Apellidos y Nombres: BONAPARTE NAPOLEON",
                "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES",
            ],
            "text": (
                "Consulta en línea de Antecedentes Penales y Requerimientos Judiciales\n"
                "Que siendo las 08:13:16 AM horas del 09/08/2026, el ciudadano identificado con:\n"
                "Cédula de Ciudadanía N° 1020802674\n"
                "Apellidos y Nombres: BONAPARTE NAPOLEON\n"
                "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES"
            ),
            "page_count_detected": 1,
        },
    )
    monkeypatch.setattr(mod, "_bedrock_model_id", lambda: "anthropic.claude-sonnet-5")
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))
    monkeypatch.setattr(
        mod,
        "_store_final_review_summary",
        lambda form_id, submission_id: {"final_review_status": "pending_documents"},
    )

    result = mod._process_job(
        {
            "form_id": "dpaadbok",
            "submission_id": "qxxcnbmtd1",
            "submission_pk": "FORM#dpaadbok",
            "submission_sk": "SUBMISSION#qxxcnbmtd1",
            "document_kind": "antecedentes_judiciales",
            "question": "Certificado de antecedentes judiciales",
            "s3_uri": "s3://bucket/volunteer-background-checks/dpaadbok/qxxcnbmtd1/certificado-de-antecedentes-judiciales.pdf",
            "s3_bucket": "bucket",
            "s3_key": "volunteer-background-checks/dpaadbok/qxxcnbmtd1/certificado-de-antecedentes-judiciales.pdf",
            "contact_name": "Napoleon Bonaparte",
            "contact_email": "persona@example.com",
        }
    )

    assert result["status"] == "completed"
    assert stored[0]["status"] == "completed"
    assert stored[0]["review_engine"] == "textract_detect_document_text"
    assert stored[0]["validation_status"] == "valid"
    assert stored[0]["consultation_datetime_text"] == "08:13:16 AM 09/08/2026"
    assert stored[0]["matched_document_number"] is True
    assert stored[0]["matched_full_name"] is True
    assert stored[0]["matched_required_phrase"] is True


def test_certificate_validation_allows_minor_ocr_name_difference():
    cedula_review = {
        "review_payload": {
            "fields": {
                "numero_documento": {"value": "1020802674", "confidence": "confiable"},
                "apellidos": {"value": "DIAZ MUNEVAAR", "confidence": "confiable"},
                "nombres": {"value": "DANIEL NICOLAS", "confidence": "confiable"},
            }
        }
    }

    validation = mod._certificate_validation_result(
        "antecedentes_judiciales",
        (
            "Que siendo las 08:13:16 AM horas del 09/08/2026, el ciudadano identificado con: "
            "Cedula de Ciudadania N 1020802674 Apellidos y Nombres: DIAZ MUNEVAR DANIEL NICOLAS "
            "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES"
        ),
        cedula_review,
    )

    assert validation["validation_status"] == "valid"
    assert validation["matched_document_number"] is True
    assert validation["matched_full_name"] is True
    assert validation["matched_full_name_strategy"] == "fuzzy_minor_ocr"
    assert validation["matched_full_name_distance"] == 1


def test_certificate_validation_marks_invalid_on_phrase_mismatch():
    cedula_review = {
        "review_payload": {
            "fields": {
                "numero_documento": {"value": "1020802674", "confidence": "confiable"},
                "apellidos": {"value": "BONAPARTE", "confidence": "confiable"},
                "nombres": {"value": "NAPOLEON", "confidence": "confiable"},
            }
        }
    }

    validation = mod._certificate_validation_result(
        "antecedentes_inhabilidades",
        (
            "Que siendo las 08:11:56 horas del 09/08/2026, el ciudadano identificado con cédula de ciudadanía "
            "No. 1020802674, Apellidos y Nombres BONAPARTE NAPOLEON REGISTRA INHABILIDAD"
        ),
        cedula_review,
    )

    assert validation["validation_status"] == "invalid"
    assert "required_phrase_mismatch" in validation["validation_errors"]


def test_reconcile_certificate_reviews_after_cedula(monkeypatch):
    stored: list[dict] = []
    cedula_item = {
        "pk": "FORM#dpaadbok",
        "sk": "SUBMISSION#sub-1#DOCUMENT#cedula",
        "document_kind": "cedula",
        "review_payload": {
            "fields": {
                "numero_documento": {"value": "1020802674", "confidence": "confiable"},
                "apellidos": {"value": "BONAPARTE", "confidence": "confiable"},
                "nombres": {"value": "NAPOLEON", "confidence": "confiable"},
            }
        },
    }
    pending_certificate = {
        "pk": "FORM#dpaadbok",
        "sk": "SUBMISSION#sub-1#DOCUMENT#antecedentes_inhabilidades",
        "document_kind": "antecedentes_inhabilidades",
        "review_text": (
            "Que siendo las 08:11:56 horas del 09/08/2026, el ciudadano identificado con cédula de ciudadanía "
            "No. 1020802674, Apellidos y Nombres BONAPARTE NAPOLEON NO REGISTRA INHABILIDAD"
        ),
    }

    monkeypatch.setattr(mod, "_get_review_item", lambda form_id, submission_id, document_kind: cedula_item)
    monkeypatch.setattr(mod, "_query_submission_review_items", lambda submission_id: [cedula_item, pending_certificate])
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))

    reconciled = mod._reconcile_certificate_reviews("dpaadbok", "sub-1")

    assert reconciled[0]["document_kind"] == "antecedentes_inhabilidades"
    assert reconciled[0]["validation_status"] == "valid"
    assert stored[0]["validation_status"] == "valid"


def test_final_review_summary_prefers_certificate_name_when_certificates_agree(monkeypatch):
    cedula_item = {
        "pk": "FORM#dpaadbok",
        "sk": "SUBMISSION#sub-1#DOCUMENT#cedula",
        "document_kind": "cedula",
        "status": "completed",
        "validation_status": "valid",
        "validation_errors": [],
        "review_payload": {
            "fields": {
                "numero_documento": {"value": "1020802674", "confidence": "confiable"},
                "apellidos": {"value": "DIAZ MUNEVAAR", "confidence": "confiable"},
                "nombres": {"value": "NAPOLEON", "confidence": "confiable"},
            }
        },
        "identity_document_number": "1020802674",
        "identity_full_name": "DIAZ MUNEVAAR NAPOLEON",
    }
    judicial_item = {
        "document_kind": "antecedentes_judiciales",
        "status": "completed",
        "validation_status": "valid",
        "validation_errors": [],
        "extracted_document_number": "1020802674",
        "extracted_full_name": "BONAPARTE NAPOLEON",
        "consultation_datetime_text": "08:13:16 AM 09/08/2026",
    }
    inhabilidades_item = {
        "document_kind": "antecedentes_inhabilidades",
        "status": "completed",
        "validation_status": "valid",
        "validation_errors": [],
        "extracted_document_number": "1020802674",
        "extracted_full_name": "BONAPARTE NAPOLEON",
        "consultation_datetime_text": "08:11:56 09/08/2026",
    }

    monkeypatch.setattr(
        mod,
        "_query_submission_review_items",
        lambda submission_id: [cedula_item, judicial_item, inhabilidades_item],
    )

    summary = mod._final_review_summary("dpaadbok", "sub-1")

    assert summary is not None
    assert summary["final_review_status"] == "approved"
    assert summary["resolved_document_number"] == "1020802674"
    assert summary["resolved_full_name"] == "BONAPARTE NAPOLEON"
    assert summary["resolved_full_name_source"] == "certificates"


def test_build_background_check_internal_review_url_includes_prefilled_values(monkeypatch):
    monkeypatch.setenv("BACKGROUND_CHECK_INTERNAL_REVIEW_FORM_URL", "https://app.youform.com/forms/p35vzbna")

    summary_item = {
        "form_id": "dpaadbok",
        "submission_id": "qxxcnbmtd1",
        "contact_email": "napoleonbonaparte@gmail.com",
        "contact_phone": "+573194477859",
        "identity_first_names": "DANIEL NICOLAS",
        "identity_last_names": "DIAZ MUNEVAR",
        "identity_document_number": "1020802674",
        "resolved_document_number": "1020802674",
        "resolved_full_name": "DIAZ MUNEVAR DANIEL NICOLAS",
        "final_review_status": "approved",
        "final_review_errors": ["nombre_no_coincide", "fecha_vencida"],
        "judicial_consultation_datetime_text": "08:13:16 AM 09/08/2026",
        "inhabilidades_consultation_datetime_text": "08:11:56 09/08/2026",
        "review_payload": {
            "document_type": "cedula_pre_2020",
        },
        "final_review_details": {
            "antecedentes_judiciales": {
                "required_phrase": "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES",
            },
            "antecedentes_inhabilidades": {
                "required_phrase": "NO REGISTRA INHABILIDAD",
            },
        },
    }

    url = mod._build_background_check_internal_review_url(summary_item)

    assert url.startswith("https://app.youform.com/forms/p35vzbna?")
    assert "contact.first_name=DANIEL+NICOLAS" in url
    assert "contact.last_name=DIAZ+MUNEVAR" in url
    assert "document_number=1020802674" in url
    assert "final_review_status=approved" in url
    assert "final_review_errors=nombre_no_coincide%2Cfecha_vencida" in url


def test_should_not_resend_background_check_notification_for_same_fingerprint():
    summary_item = {
        "final_review_status": "approved",
        "final_review_errors": ["nombre_no_coincide"],
        "resolved_document_number": "1020802674",
        "resolved_full_name": "DIAZ MUNEVAR DANIEL NICOLAS",
        "internal_review_notification_status": "sent",
    }
    summary_item["internal_review_notification_fingerprint"] = mod._background_check_notification_fingerprint(summary_item)

    assert mod._should_send_background_check_admin_notification(summary_item) is False


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
