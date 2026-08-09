import io
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}

EXTRACTION_PROMPT = """Eres un extractor de datos de documentos de identidad colombianos (cedula de
ciudadania formato pre-2020, cedula 2020+ con MRZ, cedula de extranjeria).

Reglas:
- Usa SIEMPRE la herramienta extract_id_document. No respondas en texto plano.
- Este flujo solo acepta cedula de ciudadania colombiana o cedula de extranjeria colombiana.
- Si el archivo no corresponde a uno de esos documentos, marca document_type como
  "unsupported_document", document_country como "otro" o "desconocido", both_sides_present como false
  y deja los fields en null cuando no sea posible extraerlos con seguridad.
- Evalua si el PDF realmente muestra ambas caras del documento, aunque esten en una sola pagina
  o repartidas en varias. Si falta una cara o no se puede confirmar, both_sides_present debe ser false.
- Si un campo no es legible o no aplica al tipo de documento, usa null y marca
  su confidence como "no_confiable" o "no_aplica" segun corresponda.
- NO calcules ni valides checksums del MRZ. Transcribe mrz_raw tal cual
  aparece, linea por linea, sin corregir ni interpretar.
- confidence "confiable" solo si el campo es legible sin ambiguedad. Ante
  duda, "no_confiable". No optimices por parecer seguro.
- Si la imagen esta rotada, igual extrae los datos; reporta
  rotation_detected_degrees.
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dynamodb_table(table_name_env: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    table_name = os.getenv(table_name_env)
    if not table_name:
        raise RuntimeError(f"{table_name_env} is not configured.")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _s3_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("s3", region_name=region)


def _bedrock_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("bedrock-runtime", region_name=region)


def _textract_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("textract", region_name=region)


def _load_secret(secret_id: str) -> dict[str, str]:
    cached = _SECRET_CACHE.get(secret_id)
    if cached is not None:
        return cached
    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    payload = response.get("SecretString")
    if not payload:
        raise RuntimeError(f"Secret {secret_id} does not contain SecretString.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"Secret {secret_id} must contain a JSON object.")
    secret = {str(key): str(value) for key, value in data.items() if value is not None}
    _SECRET_CACHE[secret_id] = secret
    return secret


def _shared_secret() -> dict[str, str]:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if not secret_id:
        return {}
    return _load_secret(secret_id)


def _secret_or_env(secret_key_env: str, fallback_env: str | None = None) -> str:
    secret_key = (os.getenv(secret_key_env) or "").strip()
    if secret_key:
        secret_value = (_shared_secret().get(secret_key) or "").strip()
        if secret_value:
            return secret_value
        raise RuntimeError(f"{secret_key} is missing in secret {os.getenv('EVENTBRITE_SECRET_ID')}.")
    if fallback_env:
        value = (os.getenv(fallback_env) or "").strip()
        if value:
            return value
    raise RuntimeError(f"{secret_key_env} is not configured.")


def _background_check_form_id() -> str:
    return _secret_or_env("BACKGROUND_CHECK_FORM_ID_SECRET_KEY", "VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID")


def _bedrock_model_id() -> str:
    return _secret_or_env("BACKGROUND_CHECK_MODEL_ID_SECRET_KEY", "BEDROCK_MODEL_ID")


def _submissions_table():
    return _dynamodb_table("BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME")


def _reviews_table():
    return _dynamodb_table("BACKGROUND_CHECK_REVIEWS_TABLE_NAME")


def _normalized_ascii_upper(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.strip().split())
    return (
        unicodedata.normalize("NFKD", cleaned)
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
    )


def _normalized_ascii_upper_preserve_lines(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized_lines: list[str] = []
    for raw_line in value.splitlines():
        cleaned_line = " ".join(raw_line.strip().split())
        if not cleaned_line:
            continue
        normalized_lines.append(
            unicodedata.normalize("NFKD", cleaned_line)
            .encode("ascii", "ignore")
            .decode("ascii")
            .upper()
        )
    return "\n".join(normalized_lines)


def _normalized_digits(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value if character.isdigit())


def _review_item_key(form_id: Any, submission_id: Any, document_kind: str) -> dict[str, str]:
    safe_form_id = str(form_id or "UNKNOWN_FORM")
    safe_submission_id = str(submission_id or "UNKNOWN_SUBMISSION")
    return {
        "pk": f"FORM#{safe_form_id}",
        "sk": f"SUBMISSION#{safe_submission_id}#DOCUMENT#{document_kind}",
    }


def _get_review_item(form_id: Any, submission_id: Any, document_kind: str) -> dict[str, Any] | None:
    response = _reviews_table().get_item(Key=_review_item_key(form_id, submission_id, document_kind))
    return response.get("Item")


def _query_submission_review_items(submission_id: Any) -> list[dict[str, Any]]:
    response = _reviews_table().query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"SUBMISSION#{submission_id}"),
    )
    return response.get("Items") or []


def _download_pdf(bucket_name: str, key: str) -> bytes:
    response = _s3_client().get_object(Bucket=bucket_name, Key=key)
    return response["Body"].read()


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int) -> list[bytes]:
    import pymupdf as fitz  # type: ignore

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[bytes] = []
    for page_index in range(min(len(document), max_pages)):
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(alpha=False, colorspace=fitz.csGRAY)
        png_bytes = pixmap.tobytes("png")
        images.append(_soft_image_cleanup(png_bytes))
    return images


def _soft_image_cleanup(png_bytes: bytes) -> bytes:
    try:
        from PIL import Image, ImageEnhance, ImageOps  # type: ignore
    except ImportError:
        return png_bytes

    with Image.open(io.BytesIO(png_bytes)) as image:
        grayscale = image.convert("L")
        normalized = ImageOps.autocontrast(grayscale, cutoff=1)
        toned = ImageEnhance.Brightness(normalized).enhance(0.98)
        output = io.BytesIO()
        toned.save(output, format="PNG")
        return output.getvalue()


def _field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "value": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["confiable", "no_confiable", "no_aplica"]},
        },
        "required": ["value", "confidence"],
    }


def _tool_schema() -> dict[str, Any]:
    field = _field_schema()
    return {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": [
                    "cedula_pre_2020",
                    "cedula_2020_mrz",
                    "cedula_extranjeria",
                    "unsupported_document",
                ],
            },
            "document_country": {"type": "string", "enum": ["colombia", "otro", "desconocido"]},
            "both_sides_present": {"type": "boolean"},
            "side_processed": {"type": "string", "enum": ["frente", "reverso", "unica"]},
            "rotation_detected_degrees": {"type": "integer", "enum": [0, 90, 180, 270]},
            "image_quality": {"type": "string", "enum": ["adecuada", "degradada"]},
            "fields": {
                "type": "object",
                "properties": {
                    "numero_documento": field,
                    "apellidos": field,
                    "nombres": field,
                    "fecha_nacimiento": field,
                    "lugar_nacimiento": field,
                    "sexo": field,
                    "nacionalidad": field,
                    "estatura": field,
                    "grupo_sanguineo_rh": field,
                    "fecha_expedicion": field,
                    "lugar_expedicion": field,
                    "fecha_expiracion": field,
                    "mrz_raw": field,
                },
                "required": ["numero_documento", "apellidos", "nombres"],
            },
        },
        "required": ["document_type", "document_country", "both_sides_present", "side_processed", "fields"],
    }


def _extract_document_with_bedrock(rendered_images: list[bytes]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "text": (
                "Extrae los datos del documento adjunto usando la herramienta obligatoria extract_id_document. "
                "Este job corresponde por ahora a una cedula y debe tratarse como documento de identidad colombiano."
            )
        }
    ]
    for image_bytes in rendered_images:
        content.append(
            {
                "image": {
                    "format": "png",
                    "source": {"bytes": image_bytes},
                }
            }
        )

    response = _bedrock_client().converse(
        modelId=_bedrock_model_id(),
        system=[{"text": EXTRACTION_PROMPT}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 2500, "temperature": 0},
        toolConfig={
            "tools": [
                {
                    "toolSpec": {
                        "name": "extract_id_document",
                        "description": "Extrae campos de un documento de identidad colombiano.",
                        "inputSchema": {"json": _tool_schema()},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": "extract_id_document"}},
        },
    )

    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict) and tool_use.get("name") == "extract_id_document":
            return {
                "tool_name": tool_use.get("name"),
                "tool_input": tool_use.get("input"),
                "stop_reason": response.get("stopReason"),
                "usage": response.get("usage"),
                "raw_response": response,
            }
    raise RuntimeError("Bedrock did not return extract_id_document tool output.")


def _extract_text_with_textract(pdf_bytes: bytes) -> dict[str, Any]:
    response = _textract_client().detect_document_text(
        Document={
            "Bytes": pdf_bytes,
        }
    )
    blocks = response.get("Blocks") or []
    lines = [block.get("Text") for block in blocks if block.get("BlockType") == "LINE" and block.get("Text")]
    pages = [block for block in blocks if block.get("BlockType") == "PAGE"]
    return {
        "raw_response": response,
        "lines": lines,
        "text": "\n".join(lines),
        "page_count_detected": len(pages) or None,
    }


def _cedula_identity_snapshot(review_item: dict[str, Any] | None) -> dict[str, str | None]:
    if not isinstance(review_item, dict):
        return {
            "document_number": None,
            "last_names": None,
            "first_names": None,
            "full_name": None,
        }
    payload = review_item.get("review_payload")
    if not isinstance(payload, dict):
        return {
            "document_number": None,
            "last_names": None,
            "first_names": None,
            "full_name": None,
        }
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return {
            "document_number": None,
            "last_names": None,
            "first_names": None,
            "full_name": None,
        }

    def field_value(name: str) -> str | None:
        field = fields.get(name)
        if isinstance(field, dict):
            value = field.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    last_names = field_value("apellidos")
    first_names = field_value("nombres")
    full_name = " ".join(part for part in (last_names, first_names) if isinstance(part, str) and part.strip()) or None
    return {
        "document_number": field_value("numero_documento"),
        "last_names": last_names,
        "first_names": first_names,
        "full_name": full_name,
    }


def _cedula_document_validation(tool_input: Any, rendered_page_count: int) -> dict[str, Any]:
    payload = tool_input if isinstance(tool_input, dict) else {}
    document_type = str(payload.get("document_type") or "").strip()
    document_country = str(payload.get("document_country") or "").strip()
    both_sides_present = payload.get("both_sides_present")

    errors: list[str] = []
    if document_type not in {"cedula_pre_2020", "cedula_2020_mrz", "cedula_extranjeria"}:
        errors.append("unsupported_identity_document")
    if document_country != "colombia":
        errors.append("document_not_colombian")
    if both_sides_present is not True:
        errors.append("both_sides_not_detected")

    return {
        "validation_status": "valid" if not errors else "invalid",
        "validation_errors": errors,
        "document_country": document_country or None,
        "both_sides_present": both_sides_present if isinstance(both_sides_present, bool) else None,
        "rendered_page_count": rendered_page_count,
    }


def _parse_certificate_identity(review_text: Any) -> dict[str, str | None]:
    if not isinstance(review_text, str) or not review_text.strip():
        return {
            "document_number": None,
            "full_name": None,
            "consultation_datetime_text": None,
        }
    normalized = _normalized_ascii_upper_preserve_lines(review_text)
    # Textract/OCR can degrade "N°" / "No." into variants like "N?".
    # We anchor on the surrounding identity phrase and capture the first
    # plausible document number that appears after it.
    number_match = re.search(r"CEDULA DE CIUDADANIA[^0-9]{0,20}([0-9][0-9\.\-]+)", normalized)
    name_match = re.search(
        r"APELLIDOS Y NOMBRES[:\s]+([A-Z ]+?)(?=\s+NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES|\s+NO REGISTRA INHABILIDAD|\s+DE CONFORMIDAD|\n|$)",
        normalized,
    )
    consultation_match = re.search(
        r"QUE SIENDO LAS\s+(\d{1,2}:\d{2}:\d{2}(?:\s*[AP]M)?)\s+HORAS DEL\s+(\d{2}/\d{2}/\d{4})",
        normalized,
    )
    return {
        "document_number": number_match.group(1).strip() if number_match else None,
        "full_name": " ".join(name_match.group(1).split()) if name_match else None,
        "consultation_datetime_text": (
            f"{consultation_match.group(1).strip()} {consultation_match.group(2).strip()}"
            if consultation_match
            else None
        ),
    }


def _certificate_required_phrase(document_kind: str) -> str | None:
    if document_kind == "antecedentes_judiciales":
        return "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES"
    if document_kind == "antecedentes_inhabilidades":
        return "NO REGISTRA INHABILIDAD"
    return None


def _certificate_validation_result(
    document_kind: str,
    review_text: Any,
    cedula_review_item: dict[str, Any] | None,
) -> dict[str, Any]:
    parsed_certificate = _parse_certificate_identity(review_text)
    cedula_identity = _cedula_identity_snapshot(cedula_review_item)
    if not cedula_identity.get("document_number") or not cedula_identity.get("full_name"):
        return {
            "validation_status": "pending_reference",
            "validation_errors": ["cedula_not_processed_yet"],
            "required_phrase": _certificate_required_phrase(document_kind),
            "extracted_document_number": parsed_certificate.get("document_number"),
            "extracted_full_name": parsed_certificate.get("full_name"),
            "consultation_datetime_text": parsed_certificate.get("consultation_datetime_text"),
            "expected_document_number": cedula_identity.get("document_number"),
            "expected_full_name": cedula_identity.get("full_name"),
        }

    errors: list[str] = []
    extracted_number = parsed_certificate.get("document_number")
    extracted_full_name = parsed_certificate.get("full_name")
    consultation_datetime_text = parsed_certificate.get("consultation_datetime_text")
    expected_number = cedula_identity.get("document_number")
    expected_full_name = cedula_identity.get("full_name")
    required_phrase = _certificate_required_phrase(document_kind)
    normalized_text = _normalized_ascii_upper(review_text if isinstance(review_text, str) else "")

    number_matches = _normalized_digits(extracted_number) == _normalized_digits(expected_number)
    full_name_matches = _normalized_ascii_upper(extracted_full_name) == _normalized_ascii_upper(expected_full_name)
    required_phrase_matches = bool(required_phrase and required_phrase in normalized_text)
    consultation_datetime_found = bool(consultation_datetime_text)

    if not number_matches:
        errors.append("document_number_mismatch")
    if not full_name_matches:
        errors.append("full_name_mismatch")
    if not required_phrase_matches:
        errors.append("required_phrase_mismatch")
    if not consultation_datetime_found:
        errors.append("consultation_datetime_missing")

    return {
        "validation_status": "valid" if not errors else "invalid",
        "validation_errors": errors,
        "required_phrase": required_phrase,
        "matched_document_number": number_matches,
        "matched_full_name": full_name_matches,
        "matched_required_phrase": required_phrase_matches,
        "consultation_datetime_found": consultation_datetime_found,
        "extracted_document_number": extracted_number,
        "extracted_full_name": extracted_full_name,
        "consultation_datetime_text": consultation_datetime_text,
        "expected_document_number": expected_number,
        "expected_full_name": expected_full_name,
    }


def _source_submission(job: dict[str, Any]) -> dict[str, Any] | None:
    submission_pk = job.get("submission_pk") or f"FORM#{job.get('form_id') or 'UNKNOWN_FORM'}"
    submission_sk = job.get("submission_sk") or f"SUBMISSION#{job.get('submission_id') or 'UNKNOWN_SUBMISSION'}"
    response = _submissions_table().get_item(Key={"pk": submission_pk, "sk": submission_sk})
    return response.get("Item")


def _review_item(job: dict[str, Any], submission: dict[str, Any] | None, result: dict[str, Any], status: str) -> dict[str, Any]:
    form_id = str(job.get("form_id") or "UNKNOWN_FORM")
    submission_id = str(job.get("submission_id") or "UNKNOWN_SUBMISSION")
    document_kind = str(job.get("document_kind") or "unknown")
    contact_email = (
        job.get("contact_email")
        or (submission or {}).get("contact_email")
        or (submission or {}).get("registration_email")
    )
    processed_at = _utc_now()
    item = {
        "pk": f"FORM#{form_id}",
        "sk": f"SUBMISSION#{submission_id}#DOCUMENT#{document_kind}",
        "entity_type": "background_check_review",
        "form_id": form_id,
        "submission_id": submission_id,
        "document_kind": document_kind,
        "question": job.get("question"),
        "contact_name": job.get("contact_name") or (submission or {}).get("contact_name"),
        "contact_email": contact_email,
        "contact_phone": job.get("contact_phone") or (submission or {}).get("contact_phone"),
        "source_submission_pk": job.get("submission_pk"),
        "source_submission_sk": job.get("submission_sk"),
        "source_s3_uri": job.get("s3_uri"),
        "source_s3_bucket": job.get("s3_bucket"),
        "source_s3_key": job.get("s3_key"),
        "status": status,
        "form_name": (submission or {}).get("form_name"),
        "submission_completed_at": (submission or {}).get("completed_at"),
        "processed_at": processed_at,
        "gsi1pk": f"STATUS#{status}",
        "gsi1sk": f"PROCESSED_AT#{processed_at}#SUBMISSION#{submission_id}",
        "gsi2pk": f"SUBMISSION#{submission_id}",
        "gsi2sk": f"DOCUMENT#{document_kind}",
    }
    if isinstance(contact_email, str) and contact_email.strip():
        item["gsi3pk"] = f"EMAIL#{contact_email.strip().lower()}"
        item["gsi3sk"] = f"SUBMISSION#{submission_id}#DOCUMENT#{document_kind}"
    item.update(result)
    if item.get("review_engine") == "bedrock":
        item["model_id"] = _bedrock_model_id()
    return {key: value for key, value in item.items() if value is not None}


def _store_review(item: dict[str, Any]) -> None:
    _reviews_table().put_item(Item=item)


def _update_review_validation(item: dict[str, Any], validation_result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(item)
    updated.update(validation_result)
    return updated


def _reconcile_certificate_reviews(form_id: Any, submission_id: Any) -> list[dict[str, Any]]:
    cedula_review = _get_review_item(form_id, submission_id, "cedula")
    if cedula_review is None:
        return []
    updated_items: list[dict[str, Any]] = []
    for item in _query_submission_review_items(submission_id):
        document_kind = str(item.get("document_kind") or "").strip()
        if document_kind not in {"antecedentes_judiciales", "antecedentes_inhabilidades"}:
            continue
        validation_result = _certificate_validation_result(document_kind, item.get("review_text"), cedula_review)
        updated_item = _update_review_validation(item, validation_result)
        _store_review(updated_item)
        updated_items.append(updated_item)
    return updated_items


def _process_job(job: dict[str, Any]) -> dict[str, Any]:
    if str(job.get("form_id") or "").strip() != _background_check_form_id():
        return {
            "submission_id": job.get("submission_id"),
            "status": "ignored",
            "reason": "form_id_mismatch",
        }
    document_kind = str(job.get("document_kind") or "").strip()
    if document_kind not in {"cedula", "antecedentes_judiciales", "antecedentes_inhabilidades"}:
        return {
            "submission_id": job.get("submission_id"),
            "status": "ignored",
            "reason": "unsupported_document_kind",
        }

    submission = _source_submission(job)
    pdf_bytes = _download_pdf(str(job["s3_bucket"]), str(job["s3_key"]))
    # Bedrock is reserved strictly for identity-document extraction.
    # Certificates follow a separate Textract path to keep responsibilities split.
    if document_kind == "cedula":
        max_pages = int(os.getenv("BACKGROUND_CHECK_REVIEW_MAX_PAGES", "2"))
        images = _render_pdf_pages(pdf_bytes, max_pages=max_pages)
        if not images:
            raise RuntimeError("No rendered images were produced from the PDF.")
        extraction = _extract_document_with_bedrock(images)
        cedula_snapshot = _cedula_identity_snapshot({"review_payload": extraction.get("tool_input")})
        cedula_document_validation = _cedula_document_validation(extraction.get("tool_input"), len(images))
        review_payload = {
            "review_engine": "bedrock",
            "review_payload": extraction.get("tool_input"),
            "review_usage": extraction.get("usage"),
            "review_stop_reason": extraction.get("stop_reason"),
            "page_count_processed": len(images),
            "identity_document_number": cedula_snapshot.get("document_number"),
            "identity_last_names": cedula_snapshot.get("last_names"),
            "identity_first_names": cedula_snapshot.get("first_names"),
            "identity_full_name": cedula_snapshot.get("full_name"),
            **cedula_document_validation,
        }
    else:
        extraction = _extract_text_with_textract(pdf_bytes)
        review_payload = {
            "review_engine": "textract_detect_document_text",
            "review_text_lines": extraction.get("lines"),
            "review_text": extraction.get("text"),
            "page_count_processed": extraction.get("page_count_detected"),
        }

    review_item = _review_item(job, submission, review_payload, "completed")
    if document_kind in {"antecedentes_judiciales", "antecedentes_inhabilidades"}:
        cedula_review = _get_review_item(job.get("form_id"), job.get("submission_id"), "cedula")
        review_item = _update_review_validation(
            review_item,
            _certificate_validation_result(document_kind, review_item.get("review_text"), cedula_review),
        )
    _store_review(review_item)
    reconciled_items: list[dict[str, Any]] = []
    if document_kind == "cedula":
        if review_item.get("validation_status") == "valid" and (os.getenv("BACKGROUND_CHECK_REVIEWS_TABLE_NAME") or "").strip():
            reconciled_items = _reconcile_certificate_reviews(job.get("form_id"), job.get("submission_id"))
    logger.info("Stored background check review: %s", json.dumps(review_item, ensure_ascii=False, default=str))
    if reconciled_items:
        logger.info(
            "Reconciled certificate reviews after cedula processing: %s",
            json.dumps(reconciled_items, ensure_ascii=False, default=str),
        )
    return {
        "submission_id": job.get("submission_id"),
        "status": "completed",
        "document_kind": document_kind,
        "reconciled_documents": [item.get("document_kind") for item in reconciled_items],
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    records = event.get("Records") or []
    processed: list[dict[str, Any]] = []
    for record in records:
        body = record.get("body") or "{}"
        job = json.loads(body)
        try:
            processed.append(_process_job(job))
        except Exception as exc:
            failure_item = _review_item(
                job,
                _source_submission(job),
                {
                    "review_error": str(exc),
                },
                "failed",
            )
            _store_review(failure_item)
            logger.exception(
                "Failed background check review for submission %s.",
                job.get("submission_id"),
            )
            raise

    logger.info(
        "Processed background check review batch: %s",
        json.dumps(
            {
                "record_count": len(records),
                "reviews_table": os.getenv("BACKGROUND_CHECK_REVIEWS_TABLE_NAME"),
                "processed": processed,
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    return {
        "statusCode": 200,
        "body": json.dumps({"ok": True, "processed": processed}),
    }
