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
    assert summary["final_review_status"] == "PRE_APPROVED"
    assert summary["resolved_document_number"] == "1020802674"
    assert summary["resolved_full_name"] == "BONAPARTE NAPOLEON"
    assert summary["resolved_full_name_source"] == "certificates"
    assert summary["partition_key"] == "FORM#dpaadbok#SUBMISSION#sub-1#DOCUMENT#1020802674"
    assert summary["gsi4pk"] == "PARTITION_KEY#FORM#dpaadbok#SUBMISSION#sub-1#DOCUMENT#1020802674"


def test_build_background_check_internal_review_url_includes_prefilled_values(monkeypatch):
    monkeypatch.setenv("BACKGROUND_CHECK_INTERNAL_REVIEW_FORM_URL", "https://app.youform.com/forms/p35vzbna")

    summary_item = {
        "submission_id": "qxxcnbmtd1",
        "contact_email": "gocircleup@gmail.com",
        "contact_phone": "+573194477859",
        "identity_document_number": "1020802674",
        "resolved_document_number": "1020802674",
        "resolved_full_name": "DIAZ MUNEVAR DANIEL NICOLAS",
        "partition_key": "FORM#dpaadbok#SUBMISSION#qxxcnbmtd1#DOCUMENT#1020802674",
        "final_review_status": "PRE_APPROVED",
        "final_review_errors": ["NOMBRE_NO_COINCIDE", "FECHA_VENCIDA"],
        "judicial_consultation_datetime_text": "08:13:16 AM 09/08/2026",
        "inhabilidades_consultation_datetime_text": "08:11:56 09/08/2026",
        "review_payload": {
            "document_type": "cedula_pre_2020",
            "fields": {
                "fecha_nacimiento": {"value": "03/11/1994", "confidence": "confiable"},
                "lugar_nacimiento": {"value": "Bogota", "confidence": "confiable"},
                "nacionalidad": {"value": "Colombiana", "confidence": "confiable"},
            },
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
    assert "contact.email=gocircleup%40gmail.com" in url
    assert "contact.phone_number=%2B573194477859" in url
    assert "document_type=CEDULA_PRE_2020" in url
    assert "date_of_birth=1994-11-03" in url
    assert "place_of_birth=Bogota" in url
    assert "nationality=Colombiana" in url
    assert "partition_key=FORM%23dpaadbok%23SUBMISSION%23qxxcnbmtd1%23DOCUMENT%231020802674" in url
    assert "final_review_status=PRE_APPROVED" in url
    assert "final_review_errors=NOMBRE_NO_COINCIDE%2CFECHA_VENCIDA" in url
    assert "judicial_date=2026-08-09" in url
    assert "inhabilidades_date=2026-08-09" in url
    assert "resolved_document_number=1020802674" in url
    assert "resolved_full_name=DIAZ+MUNEVAR+DANIEL+NICOLAS" in url
    assert "contact.first_name=" not in url
    assert "contact.last_name=" not in url
    assert "&document_number=" not in url
    assert "form_id=" not in url
    assert "submission_id=" not in url
    assert "judicial_datetime=" not in url
    assert "inhabilidades_datetime=" not in url


def test_should_not_resend_background_check_notification_for_same_fingerprint():
    summary_item = {
        "final_review_status": "PRE_APPROVED",
        "final_review_errors": ["NOMBRE_NO_COINCIDE"],
        "resolved_document_number": "1020802674",
        "resolved_full_name": "DIAZ MUNEVAR DANIEL NICOLAS",
        "internal_review_notification_status": "sent",
    }
    summary_item["internal_review_notification_fingerprint"] = mod._background_check_notification_fingerprint(summary_item)

    assert mod._should_send_background_check_admin_notification(summary_item) is False


def test_background_check_email_status_text_uses_clear_english_labels():
    summary_item = {
        "final_review_details": {
            "antecedentes_judiciales": {
                "validation_status": "valid",
                "required_phrase": "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES",
            },
            "antecedentes_inhabilidades": {
                "validation_status": "valid",
                "required_phrase": "NO REGISTRA INHABILIDAD",
            },
        }
    }

    assert mod._background_check_email_status_text(summary_item, "antecedentes_judiciales") == "NO CRIMINAL RECORDS"
    assert mod._background_check_email_status_text(summary_item, "antecedentes_inhabilidades") == "NO DISQUALIFICATIONS"


def test_build_background_check_whatsapp_url_uses_uppercase_name_and_status():
    summary_item = {
        "contact_phone": "+57 319 447 7859",
        "resolved_full_name": "Daniel Nicolas Diaz Munevar",
    }

    approved_url = mod._build_background_check_whatsapp_url(summary_item, "pre_approved")
    denied_url = mod._build_background_check_whatsapp_url(summary_item, "denied")

    assert approved_url is not None
    assert denied_url is not None
    assert approved_url.startswith("https://wa.me/573194477859?")
    assert "DANIEL+NICOLAS+DIAZ+MUNEVAR" in approved_url
    assert "%2AAPROBADO%2A" in approved_url
    assert "%2ADENEGADO%2A" in denied_url


def test_build_background_check_admin_email_includes_whatsapp_buttons(monkeypatch):
    monkeypatch.setenv("BACKGROUND_CHECK_INTERNAL_REVIEW_FORM_URL", "https://app.youform.com/forms/p35vzbna")
    monkeypatch.setenv("BACKGROUND_CHECK_NOTIFICATION_SUPPORT_URL", "https://circleup.com.co")
    monkeypatch.setenv(
        "BACKGROUND_CHECK_NOTIFICATION_LOGO_URL",
        "https://wearecircleup-prod-public-assets-311923415472-us-east-1.s3.us-east-1.amazonaws.com/email-assets/logo.png",
    )

    summary_item = {
        "submission_id": "qxxcnbmtd1",
        "contact_email": "gocircleup@gmail.com",
        "contact_phone": "+573194477859",
        "resolved_document_number": "1020802674",
        "resolved_full_name": "DIAZ MUNEVAR DANIEL NICOLAS",
        "partition_key": "FORM#dpaadbok#SUBMISSION#qxxcnbmtd1#DOCUMENT#1020802674",
        "final_review_status": "PRE_APPROVED",
        "final_review_errors": [],
        "judicial_consultation_datetime_text": "08:13:16 AM 09/08/2026",
        "inhabilidades_consultation_datetime_text": "08:11:56 09/08/2026",
        "review_payload": {
            "document_type": "cedula_pre_2020",
            "fields": {
                "fecha_nacimiento": {"value": "03/11/1994", "confidence": "confiable"},
                "lugar_nacimiento": {"value": "Bogota", "confidence": "confiable"},
                "nacionalidad": {"value": "Colombiana", "confidence": "confiable"},
            },
        },
        "final_review_details": {
            "antecedentes_judiciales": {
                "validation_status": "valid",
                "required_phrase": "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES",
            },
            "antecedentes_inhabilidades": {
                "validation_status": "valid",
                "required_phrase": "NO REGISTRA INHABILIDAD",
            },
        },
    }

    subject, text_body, html_body = mod._build_background_check_admin_email(summary_item)

    assert subject == "Revision final de antecedentes: PRE_APPROVED"
    assert "WhatsApp Aprobado:" in text_body
    assert "WhatsApp Denegado:" in text_body
    assert "WhatsApp: Aprobado" in html_body
    assert "WhatsApp: Denegado" in html_body
    assert "DIAZ+MUNEVAR+DANIEL+NICOLAS" in html_body


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
    assert stored[0]["review_error_type"] == "RuntimeError"


def test_process_job_fails_with_missing_job_field(monkeypatch):
    monkeypatch.setattr(mod, "_background_check_form_id", lambda: "dpaadbok")
    monkeypatch.setattr(mod, "_source_submission", lambda job: {"contact_email": "persona@example.com"})

    try:
        mod._process_job(
            {
                "form_id": "dpaadbok",
                "submission_id": "sub-1",
                "document_kind": "cedula",
                "s3_bucket": "bucket",
            }
        )
        raised = None
    except Exception as exc:
        raised = exc

    assert isinstance(raised, mod.ReviewProcessingError)
    assert raised.error_type == "missing_job_field"
    assert "s3_key" in raised.detail


def test_handler_records_invalid_record_body_as_failed(monkeypatch):
    stored: list[dict] = []

    monkeypatch.setattr(mod, "_source_submission", lambda job: None)
    monkeypatch.setattr(mod, "_store_review", lambda item: stored.append(item))

    event = {
        "Records": [
            {
                "body": "{bad-json",
            }
        ]
    }

    try:
        mod.handler(event, None)
        raised = None
    except Exception as exc:
        raised = exc

    assert isinstance(raised, mod.ReviewProcessingError)
    assert raised.error_type == "invalid_record_body"
    assert stored[0]["status"] == "failed"
    assert stored[0]["review_error_type"] == "invalid_record_body"
    assert stored[0]["document_kind"] == "unknown"


def test_handler_preserves_original_error_when_failure_persistence_also_fails(monkeypatch):
    monkeypatch.setattr(mod, "_process_job", lambda job: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(mod, "_source_submission", lambda job: None)
    monkeypatch.setattr(mod, "_store_review", lambda item: (_ for _ in ()).throw(RuntimeError("cannot persist failure")))

    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "form_id": "dpaadbok",
                        "submission_id": "sub-1",
                        "document_kind": "cedula",
                    }
                )
            }
        ]
    }

    try:
        mod.handler(event, None)
        raised = None
    except Exception as exc:
        raised = exc

    assert isinstance(raised, RuntimeError)
    assert str(raised) == "boom"
