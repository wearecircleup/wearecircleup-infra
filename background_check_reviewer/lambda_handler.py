import io
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import urlencode

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}
SUPPORTED_DOCUMENT_KINDS = {"cedula", "antecedentes_judiciales", "antecedentes_inhabilidades"}


class ReviewProcessingError(RuntimeError):
    def __init__(self, error_type: str, detail: str):
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail

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


def _log_json(message: str, payload: dict[str, Any]) -> None:
    logger.info("%s: %s", message, json.dumps(payload, ensure_ascii=False, default=str))


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


def _ses_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sesv2", region_name=region)


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


def _normalize_iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", cleaned)
    if iso_match:
        return cleaned
    slash_match = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", cleaned)
    if slash_match:
        day, month, year = slash_match.groups()
        return f"{year}-{month}-{day}"
    return None


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            substitution = previous[right_index - 1] + (0 if left_char == right_char else 1)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def _name_match_result(extracted_full_name: Any, expected_full_name: Any) -> dict[str, Any]:
    normalized_extracted = _normalized_ascii_upper(extracted_full_name)
    normalized_expected = _normalized_ascii_upper(expected_full_name)
    if not normalized_extracted or not normalized_expected:
        return {
            "matches": False,
            "distance": None,
            "strategy": "missing",
        }
    if normalized_extracted == normalized_expected:
        return {
            "matches": True,
            "distance": 0,
            "strategy": "exact",
        }

    distance = _levenshtein_distance(normalized_extracted, normalized_expected)
    if distance <= 2:
        return {
            "matches": True,
            "distance": distance,
            "strategy": "fuzzy_minor_ocr",
        }
    return {
        "matches": False,
        "distance": distance,
        "strategy": "mismatch",
    }


def _review_item_key(form_id: Any, submission_id: Any, document_kind: str) -> dict[str, str]:
    safe_form_id = str(form_id or "UNKNOWN_FORM")
    safe_submission_id = str(submission_id or "UNKNOWN_SUBMISSION")
    return {
        "pk": f"FORM#{safe_form_id}",
        "sk": f"SUBMISSION#{safe_submission_id}#DOCUMENT#{document_kind}",
    }


def _background_check_partition_key(form_id: Any, submission_id: Any, document_number: Any) -> str | None:
    normalized_form_id = str(form_id or "").strip()
    normalized_submission_id = str(submission_id or "").strip()
    normalized_document_number = _normalized_digits(document_number)
    if not normalized_form_id or not normalized_submission_id or not normalized_document_number:
        return None
    return f"FORM#{normalized_form_id}#SUBMISSION#{normalized_submission_id}#DOCUMENT#{normalized_document_number}"


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

    # The document number is the hard identity anchor across all three files.
    # Names may carry minor OCR noise, so we allow a tiny reconciliation window there.
    number_matches = _normalized_digits(extracted_number) == _normalized_digits(expected_number)
    name_match = _name_match_result(extracted_full_name, expected_full_name)
    full_name_matches = bool(name_match.get("matches"))
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
        "matched_full_name_strategy": name_match.get("strategy"),
        "matched_full_name_distance": name_match.get("distance"),
        "matched_required_phrase": required_phrase_matches,
        "consultation_datetime_found": consultation_datetime_found,
        "extracted_document_number": extracted_number,
        "extracted_full_name": extracted_full_name,
        "consultation_datetime_text": consultation_datetime_text,
        "expected_document_number": expected_number,
        "expected_full_name": expected_full_name,
    }


def _review_details_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "document_kind": item.get("document_kind"),
        "status": item.get("status"),
        "validation_status": item.get("validation_status"),
        "validation_errors": item.get("validation_errors") or [],
    }
    for key in (
        "identity_document_number",
        "identity_last_names",
        "identity_first_names",
        "identity_full_name",
        "extracted_document_number",
        "extracted_full_name",
        "required_phrase",
        "matched_document_number",
        "matched_full_name",
        "matched_full_name_strategy",
        "matched_full_name_distance",
        "matched_required_phrase",
        "consultation_datetime_text",
        "document_country",
        "both_sides_present",
    ):
        value = item.get(key)
        if value is not None:
            snapshot[key] = value
    return snapshot


def _resolved_certificate_identity(valid_certificates: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    if not valid_certificates:
        return None, None, None

    valid_numbers = [str(item.get("extracted_document_number")).strip() for item in valid_certificates if item.get("extracted_document_number")]
    valid_names = [str(item.get("extracted_full_name")).strip() for item in valid_certificates if item.get("extracted_full_name")]

    resolved_number = None
    if valid_numbers and len({_normalized_digits(value) for value in valid_numbers}) == 1:
        resolved_number = valid_numbers[0]

    resolved_name = None
    resolved_name_source = None
    if valid_names and len({_normalized_ascii_upper(value) for value in valid_names}) == 1:
        resolved_name = valid_names[0]
        resolved_name_source = "certificates"
    elif len(valid_names) == 1:
        resolved_name = valid_names[0]
        resolved_name_source = str(valid_certificates[0].get("document_kind") or "certificate")

    return resolved_number, resolved_name, resolved_name_source


def _final_review_summary(form_id: Any, submission_id: Any) -> dict[str, Any] | None:
    review_items = _query_submission_review_items(submission_id)
    if not review_items:
        return None

    items_by_kind = {
        str(item.get("document_kind") or "").strip(): item
        for item in review_items
        if isinstance(item, dict) and item.get("document_kind")
    }
    cedula_item = items_by_kind.get("cedula")
    if not cedula_item:
        return None

    judicial_item = items_by_kind.get("antecedentes_judiciales")
    inhabilidades_item = items_by_kind.get("antecedentes_inhabilidades")
    cedula_identity = _cedula_identity_snapshot(cedula_item)
    errors: list[str] = []

    if cedula_item.get("validation_status") != "valid":
        errors.extend(list(cedula_item.get("validation_errors") or []))

    missing_documents: list[str] = []
    invalid_documents: list[str] = []
    valid_certificates: list[dict[str, Any]] = []
    for required_kind in ("antecedentes_judiciales", "antecedentes_inhabilidades"):
        item = items_by_kind.get(required_kind)
        if item is None:
            missing_documents.append(required_kind)
            errors.append(f"missing_{required_kind}")
            continue
        if item.get("validation_status") != "valid":
            invalid_documents.append(required_kind)
            errors.extend(list(item.get("validation_errors") or []))
            continue
        valid_certificates.append(item)

    resolved_number, resolved_name, resolved_name_source = _resolved_certificate_identity(valid_certificates)
    if not resolved_number:
        resolved_number = cedula_identity.get("document_number")
    if not resolved_name:
        resolved_name = cedula_identity.get("full_name")
        resolved_name_source = "cedula" if resolved_name else None

    if cedula_item.get("validation_status") != "valid" or invalid_documents:
        final_review_status = "REJECTED"
    elif missing_documents:
        final_review_status = "PENDING_DOCUMENTS"
    else:
        final_review_status = "PRE_APPROVED"

    partition_key = _background_check_partition_key(
        form_id,
        submission_id,
        resolved_number or cedula_identity.get("document_number"),
    )
    normalized_errors = sorted(set(str(error).upper() for error in errors if error))

    return {
        "pk": f"FORM#{form_id or 'UNKNOWN_FORM'}",
        "sk": f"SUBMISSION#{submission_id or 'UNKNOWN_SUBMISSION'}#DOCUMENT#cedula",
        "final_review_status": final_review_status,
        "final_review_errors": normalized_errors,
        "resolved_document_number": resolved_number,
        "resolved_full_name": resolved_name,
        "resolved_full_name_source": resolved_name_source,
        "partition_key": partition_key,
        "judicial_validation_status": (judicial_item or {}).get("validation_status"),
        "inhabilidades_validation_status": (inhabilidades_item or {}).get("validation_status"),
        "judicial_consultation_datetime_text": (judicial_item or {}).get("consultation_datetime_text"),
        "inhabilidades_consultation_datetime_text": (inhabilidades_item or {}).get("consultation_datetime_text"),
        "gsi4pk": f"PARTITION_KEY#{partition_key}" if partition_key else None,
        "gsi4sk": f"FORM#{form_id or 'UNKNOWN_FORM'}#SUBMISSION#{submission_id or 'UNKNOWN_SUBMISSION'}" if partition_key else None,
        "final_review_details": {
            key: _review_details_snapshot(value)
            for key, value in (
                ("cedula", cedula_item),
                ("antecedentes_judiciales", judicial_item),
                ("antecedentes_inhabilidades", inhabilidades_item),
            )
            if isinstance(value, dict)
        },
    }


def _store_final_review_summary(form_id: Any, submission_id: Any) -> dict[str, Any] | None:
    summary = _final_review_summary(form_id, submission_id)
    if not summary:
        return None
    cedula_item = _get_review_item(form_id, submission_id, "cedula")
    if not cedula_item:
        return None
    updated_cedula_item = dict(cedula_item)
    updated_cedula_item.update(summary)
    _store_review(updated_cedula_item)
    return updated_cedula_item


def _background_check_notification_from_email() -> str:
    value = os.getenv("BACKGROUND_CHECK_NOTIFICATION_FROM_EMAIL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError("BACKGROUND_CHECK_NOTIFICATION_FROM_EMAIL is not configured.")


def _background_check_notification_reply_to_email() -> str:
    value = os.getenv("BACKGROUND_CHECK_NOTIFICATION_REPLY_TO_EMAIL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _background_check_notification_from_email()


def _background_check_notification_logo_url() -> str | None:
    value = os.getenv("BACKGROUND_CHECK_NOTIFICATION_LOGO_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _background_check_notification_support_url() -> str:
    value = os.getenv("BACKGROUND_CHECK_NOTIFICATION_SUPPORT_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "https://circleup.com.co"


def _normalized_whatsapp_phone(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 10:
        return None
    return digits


def _build_background_check_whatsapp_url(summary_item: dict[str, Any], decision: str) -> str | None:
    phone = _normalized_whatsapp_phone(summary_item.get("contact_phone"))
    full_name = str(summary_item.get("resolved_full_name") or "").strip().upper()
    if not phone or not full_name:
        return None

    if decision == "pre_approved":
        message = (
            f"Hola *{full_name}*, luego de revisar los PDF que nos compartiste, nuestra respuesta es que "
            "fuiste *APROBADO*. Este proceso se hace una sola vez, asi que nos emociona que te animes "
            "a crear tantos eventos como quieras con nosotros. Si tienes cualquier duda, no dudes en "
            "escribirnos por este numero. Un mensaje de voz tambien esta perfecto."
        )
    elif decision == "denied":
        message = (
            f"Hola *{full_name}*, luego de revisar los PDF que nos compartiste, nuestra respuesta es "
            "*DENEGADO*. Si tienes dudas sobre esta decision, puedes escribirnos a hola@circleup.com.co "
            "o por este numero. Un mensaje de voz tambien esta perfecto."
        )
    else:
        return None

    return f"https://wa.me/{phone}?{urlencode({'text': message})}"


def _background_check_allowed_admin_emails() -> set[str]:
    return {
        "hola@circleup.com.co",
        "wearecircleup@gmail.com",
    }


def _background_check_notification_to_emails() -> list[str]:
    value = os.getenv("BACKGROUND_CHECK_NOTIFICATION_TO_EMAIL")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("BACKGROUND_CHECK_NOTIFICATION_TO_EMAIL is not configured.")
    parsed = [email.strip().lower() for email in value.split(",") if email.strip()]
    if not parsed:
        raise RuntimeError("BACKGROUND_CHECK_NOTIFICATION_TO_EMAIL must contain at least one email.")
    unauthorized = [email for email in parsed if email not in _background_check_allowed_admin_emails()]
    if unauthorized:
        raise RuntimeError(
            "BACKGROUND_CHECK_NOTIFICATION_TO_EMAIL contains unauthorized recipients: "
            + ", ".join(unauthorized)
        )
    return parsed


def _background_check_internal_review_form_url() -> str:
    value = os.getenv("BACKGROUND_CHECK_INTERNAL_REVIEW_FORM_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError("BACKGROUND_CHECK_INTERNAL_REVIEW_FORM_URL is not configured.")


def _summary_detail(summary_item: dict[str, Any], document_kind: str) -> dict[str, Any]:
    details = summary_item.get("final_review_details")
    if not isinstance(details, dict):
        return {}
    item = details.get(document_kind)
    return item if isinstance(item, dict) else {}


def _background_check_email_status_text(summary_item: dict[str, Any], document_kind: str) -> str:
    detail = _summary_detail(summary_item, document_kind)
    validation_status = str(detail.get("validation_status") or "").upper()
    required_phrase = _normalized_ascii_upper(detail.get("required_phrase"))

    if document_kind == "antecedentes_judiciales":
        if validation_status == "VALID" and required_phrase == "NO TIENE ASUNTOS PENDIENTES CON LAS AUTORIDADES JUDICIALES":
            return "NO CRIMINAL RECORDS"
    if document_kind == "antecedentes_inhabilidades":
        if validation_status == "VALID" and required_phrase == "NO REGISTRA INHABILIDAD":
            return "NO DISQUALIFICATIONS"

    return validation_status or "PENDING"


def _review_payload_field(summary_item: dict[str, Any], field_name: str) -> str | None:
    payload = summary_item.get("review_payload")
    if not isinstance(payload, dict):
        return None
    if field_name == "document_type":
        value = payload.get("document_type")
        return str(value).strip().upper() if isinstance(value, str) and value.strip() else None
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return None
    field = fields.get(field_name)
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _background_check_notification_fingerprint(summary_item: dict[str, Any]) -> str:
    errors = summary_item.get("final_review_errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]
    return "|".join(
        [
            str(summary_item.get("final_review_status") or ""),
            ",".join(sorted(str(error) for error in errors if error)),
            str(summary_item.get("resolved_document_number") or ""),
            str(summary_item.get("resolved_full_name") or ""),
        ]
    )


def _build_background_check_internal_review_url(summary_item: dict[str, Any]) -> str:
    judicial_detail = _summary_detail(summary_item, "antecedentes_judiciales")
    inhabilidades_detail = _summary_detail(summary_item, "antecedentes_inhabilidades")
    errors = summary_item.get("final_review_errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]
    params = {
        "contact.email": summary_item.get("contact_email") or summary_item.get("registration_email"),
        "contact.phone_number": summary_item.get("contact_phone"),
        "document_type": _review_payload_field(summary_item, "document_type"),
        "date_of_birth": _normalize_iso_date(_review_payload_field(summary_item, "fecha_nacimiento")),
        "place_of_birth": _review_payload_field(summary_item, "lugar_nacimiento"),
        "nationality": _review_payload_field(summary_item, "nacionalidad"),
        "full_name": summary_item.get("resolved_full_name") or summary_item.get("identity_full_name"),
        "judicial_result": judicial_detail.get("required_phrase"),
        "judicial_date": _normalize_iso_date(summary_item.get("judicial_consultation_datetime_text")),
        "inhabilidades_result": inhabilidades_detail.get("required_phrase"),
        "inhabilidades_date": _normalize_iso_date(summary_item.get("inhabilidades_consultation_datetime_text")),
        "partition_key": summary_item.get("partition_key"),
        "final_review_status": summary_item.get("final_review_status"),
        "final_review_errors": ",".join(str(error) for error in errors if error),
        "resolved_document_number": summary_item.get("resolved_document_number"),
        "resolved_full_name": summary_item.get("resolved_full_name"),
    }
    normalized_params = {key: str(value) for key, value in params.items() if value not in (None, "")}
    base_url = _background_check_internal_review_form_url()
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(normalized_params)}"


def _build_background_check_admin_email(summary_item: dict[str, Any]) -> tuple[str, str, str]:
    review_url = _build_background_check_internal_review_url(summary_item)
    subject = f"Revision final de antecedentes: {summary_item.get('final_review_status') or 'pendiente'}"
    support_url = _background_check_notification_support_url()
    logo_url = _background_check_notification_logo_url()
    approve_whatsapp_url = _build_background_check_whatsapp_url(summary_item, "pre_approved")
    deny_whatsapp_url = _build_background_check_whatsapp_url(summary_item, "denied")
    final_status = str(summary_item.get("final_review_status") or "PENDING").replace("_", " ")
    judicial_status = _background_check_email_status_text(summary_item, "antecedentes_judiciales")
    inhabilidades_status = _background_check_email_status_text(summary_item, "antecedentes_inhabilidades")

    intro = (
        "Ya esta lista la respuesta final de la verificacion documental de un voluntario. "
        "Este formulario es de uso interno. Contiene la informacion recopilada durante el proceso "
        "de verificacion documental de un voluntario, para su revision y decision final."
    )
    rows = [
        ("Estado final", final_status),
        ("Antecedentes judiciales", judicial_status),
        ("Inhabilidades", inhabilidades_status),
        ("Submission ID", str(summary_item.get("submission_id") or "").upper()),
    ]

    text_lines = [
        "Hola,",
        "",
        intro,
        "",
    ]
    for label, value in rows:
        if value:
            text_lines.append(f"{label}: {value}")
    text_lines.extend(
        [
            "",
            f"Revision interna: {review_url}",
        ]
    )
    if approve_whatsapp_url:
        text_lines.append(f"WhatsApp Aprobado: {approve_whatsapp_url}")
    if deny_whatsapp_url:
        text_lines.append(f"WhatsApp Denegado: {deny_whatsapp_url}")
    text_lines.extend(
        [
            "",
            "Circle Up Community",
            "circleup.com.co",
        ]
    )
    text_body = "\n".join(text_lines)

    html_rows = "".join(
        (
            "<tr>"
            f"<td style=\"padding: 0 0 8px; width: 220px; vertical-align: top; color: #7d95ad; font-size: 12px; line-height: 1.6;\">{escape(label)}</td>"
            f"<td style=\"padding: 0 0 8px; vertical-align: top; color: #153f69; font-size: 12px; line-height: 1.6;\">{escape(value)}</td>"
            "</tr>"
        )
        for label, value in rows
        if value
    )

    html_body = (
        "<html>"
        "<head>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        "<style>"
        "@media screen and (max-width: 720px) {"
        "  .admin-shell { width: 100% !important; }"
        "  .content-col { padding: 28px 20px 22px !important; }"
        "}"
        "</style>"
        "</head>"
        "<body style=\"margin: 0; padding: 0; background-color: #f7f7f4; font-family: Arial, Helvetica, sans-serif; color: #153f69;\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background-color: #f7f7f4; padding: 40px 20px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" class=\"admin-shell\" style=\"max-width: 760px; background-color: #ffffff;\">"
        "<tr><td class=\"content-col\" style=\"padding: 32px 28px 28px;\">"
        "<div style=\"margin: 0 0 16px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        "<h1 style=\"margin: 0 0 18px; font-size: 30px; line-height: 1.1; font-weight: 500; color: #0f4978;\">Revision final de antecedentes</h1>"
        f"<p style=\"margin: 0 0 22px; font-size: 12px; line-height: 1.7; color: #5e7f9c;\">{escape(intro)}</p>"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin: 0 0 18px;\">"
        f"{html_rows}"
        "</table>"
        "<p style=\"margin: 8px 0 24px;\">"
        f"<a href=\"{escape(review_url, quote=True)}\" "
        "style=\"display: inline-block; padding: 16px 28px; background-color: #4da3f5; color: #ffffff; text-decoration: none; border-radius: 0; font-size: 16px; font-weight: 700;\">"
        "Abrir revision interna"
        "</a>"
        "</p>"
    )
    if approve_whatsapp_url or deny_whatsapp_url:
        html_body += "<p style=\"margin: 0 0 24px;\">"
        if approve_whatsapp_url:
            html_body += (
                f"<a href=\"{escape(approve_whatsapp_url, quote=True)}\" "
                "style=\"display: inline-block; margin: 0 12px 12px 0; padding: 14px 22px; background-color: #2fb36f; color: #ffffff; text-decoration: none; border-radius: 0; font-size: 14px; font-weight: 700;\">"
                "WhatsApp: Aprobado"
                "</a>"
            )
        if deny_whatsapp_url:
            html_body += (
                f"<a href=\"{escape(deny_whatsapp_url, quote=True)}\" "
                "style=\"display: inline-block; margin: 0 12px 12px 0; padding: 14px 22px; background-color: #153f69; color: #ffffff; text-decoration: none; border-radius: 0; font-size: 14px; font-weight: 700;\">"
                "WhatsApp: Denegado"
                "</a>"
            )
        html_body += "</p>"
    html_body += (
        "<div style=\"padding-top: 20px; border-top: 1px solid #d7e2ec;\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\">"
        "<tr>"
        "<td style=\"vertical-align: bottom; text-align: left;\">"
        "<div style=\"margin: 0 0 4px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        f"<div style=\"font-size: 12px; line-height: 18px; color: #0f4978;\"><a href=\"{escape(support_url, quote=True)}\" style=\"color: #0f4978; text-decoration: none;\">circleup.com.co</a></div>"
        "</td>"
        "<td style=\"vertical-align: bottom; text-align: right;\">"
    )
    if logo_url:
        html_body += (
            f"<img src=\"{escape(logo_url, quote=True)}\" alt=\"Circle Up Community\" width=\"42\" style=\"display: inline-block; width: 42px; height: auto; border: 0; outline: none; text-decoration: none;\">"
        )
    html_body += (
        "</td>"
        "</tr>"
        "</table>"
        "</div>"
        "</td></tr></table></td></tr></table></body></html>"
    )
    return subject, text_body, html_body


def _should_send_background_check_admin_notification(summary_item: dict[str, Any]) -> bool:
    if summary_item.get("final_review_status") not in {"PRE_APPROVED", "REJECTED"}:
        return False
    fingerprint = _background_check_notification_fingerprint(summary_item)
    return not (
        summary_item.get("internal_review_notification_status") == "sent"
        and summary_item.get("internal_review_notification_fingerprint") == fingerprint
    )


def _record_background_check_admin_notification_result(
    summary_item: dict[str, Any],
    result: dict[str, Any],
    error_detail: str | None = None,
) -> None:
    updated = dict(summary_item)
    updated["internal_review_notification_status"] = result.get("status")
    updated["internal_review_notification_message_id"] = result.get("message_id")
    updated["internal_review_notification_recipient"] = result.get("recipient")
    updated["internal_review_notification_error"] = error_detail
    updated["internal_review_notification_fingerprint"] = _background_check_notification_fingerprint(summary_item)
    if result.get("sent"):
        updated["internal_review_notification_sent_at"] = _utc_now()
    _store_review(updated)


def _send_background_check_admin_notification(summary_item: dict[str, Any]) -> dict[str, Any]:
    subject, text_body, html_body = _build_background_check_admin_email(summary_item)
    recipients = _background_check_notification_to_emails()
    response = _ses_client().send_email(
        FromEmailAddress=_background_check_notification_from_email(),
        Destination={"ToAddresses": recipients},
        ReplyToAddresses=[_background_check_notification_reply_to_email()],
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            }
        },
    )
    return {
        "sent": True,
        "status": "sent",
        "message_id": response.get("MessageId"),
        "recipient": ", ".join(recipients),
    }


def _maybe_send_background_check_admin_notification(summary_item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary_item, dict):
        return None
    if not _should_send_background_check_admin_notification(summary_item):
        return None
    try:
        result = _send_background_check_admin_notification(summary_item)
        _record_background_check_admin_notification_result(summary_item, result)
        return result
    except Exception as exc:
        logger.exception(
            "Failed to send background check admin notification for submission %s.",
            summary_item.get("submission_id"),
        )
        failure = {
            "sent": False,
            "status": "failed",
            "message_id": None,
            "recipient": None,
        }
        _record_background_check_admin_notification_result(summary_item, failure, str(exc))
        return failure


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
    _store_final_review_summary(form_id, submission_id)
    return updated_items


def _ignored_review_result(job: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "submission_id": job.get("submission_id"),
        "status": "ignored",
        "reason": reason,
    }


def _required_job_value(job: dict[str, Any], field_name: str) -> str:
    value = job.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ReviewProcessingError("missing_job_field", f"Missing required job field: {field_name}")


def _parse_record_job(record: dict[str, Any]) -> dict[str, Any]:
    body = record.get("body") or "{}"
    try:
        job = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ReviewProcessingError("invalid_record_body", "Record body is not valid JSON.") from exc
    if not isinstance(job, dict):
        raise ReviewProcessingError("invalid_record_body", "Record body must decode to a JSON object.")
    return job


def _fallback_job_for_record(record: dict[str, Any]) -> dict[str, Any]:
    body = record.get("body")
    return {
        "submission_id": None,
        "form_id": None,
        "document_kind": "unknown",
        "raw_record_body": body if isinstance(body, str) else None,
    }


def _cedula_review_payload(pdf_bytes: bytes) -> dict[str, Any]:
    max_pages = int(os.getenv("BACKGROUND_CHECK_REVIEW_MAX_PAGES", "2"))
    images = _render_pdf_pages(pdf_bytes, max_pages=max_pages)
    if not images:
        raise ReviewProcessingError("pdf_render_error", "No rendered images were produced from the PDF.")
    extraction = _extract_document_with_bedrock(images)
    cedula_snapshot = _cedula_identity_snapshot({"review_payload": extraction.get("tool_input")})
    cedula_document_validation = _cedula_document_validation(extraction.get("tool_input"), len(images))
    return {
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


def _certificate_review_payload(pdf_bytes: bytes) -> dict[str, Any]:
    extraction = _extract_text_with_textract(pdf_bytes)
    return {
        "review_engine": "textract_detect_document_text",
        "review_text_lines": extraction.get("lines"),
        "review_text": extraction.get("text"),
        "page_count_processed": extraction.get("page_count_detected"),
    }


def _review_payload_for_job(document_kind: str, pdf_bytes: bytes) -> dict[str, Any]:
    # Bedrock is reserved strictly for identity-document extraction.
    # Certificates follow a separate Textract path to keep responsibilities split.
    if document_kind == "cedula":
        return _cedula_review_payload(pdf_bytes)
    return _certificate_review_payload(pdf_bytes)


def _validated_review_item(
    job: dict[str, Any],
    submission: dict[str, Any] | None,
    document_kind: str,
    review_payload: dict[str, Any],
) -> dict[str, Any]:
    review_item = _review_item(job, submission, review_payload, "completed")
    if document_kind not in {"antecedentes_judiciales", "antecedentes_inhabilidades"}:
        return review_item

    cedula_review = _get_review_item(job.get("form_id"), job.get("submission_id"), "cedula")
    return _update_review_validation(
        review_item,
        _certificate_validation_result(document_kind, review_item.get("review_text"), cedula_review),
    )


def _load_job_dependencies(job: dict[str, Any]) -> tuple[dict[str, Any] | None, bytes]:
    submission = _source_submission(job)
    bucket_name = _required_job_value(job, "s3_bucket")
    key = _required_job_value(job, "s3_key")
    try:
        pdf_bytes = _download_pdf(bucket_name, key)
    except Exception as exc:
        raise ReviewProcessingError("pdf_download_error", f"Failed to download review PDF: {exc}") from exc
    return submission, pdf_bytes


def _postprocess_completed_review(job: dict[str, Any], review_item: dict[str, Any]) -> dict[str, Any]:
    document_kind = str(review_item.get("document_kind") or "")
    reconciled_items: list[dict[str, Any]] = []
    summary_item: dict[str, Any] | None = None
    admin_notification: dict[str, Any] | None = None

    if document_kind == "cedula":
        if review_item.get("validation_status") == "valid" and (os.getenv("BACKGROUND_CHECK_REVIEWS_TABLE_NAME") or "").strip():
            reconciled_items = _reconcile_certificate_reviews(job.get("form_id"), job.get("submission_id"))
        summary_item = _store_final_review_summary(job.get("form_id"), job.get("submission_id"))
    elif document_kind in {"antecedentes_judiciales", "antecedentes_inhabilidades"}:
        summary_item = _store_final_review_summary(job.get("form_id"), job.get("submission_id"))

    if summary_item:
        admin_notification = _maybe_send_background_check_admin_notification(summary_item)

    _log_json(
        "Stored background check review",
        {
            "pk": review_item.get("pk"),
            "sk": review_item.get("sk"),
            "submission_id": review_item.get("submission_id"),
            "document_kind": review_item.get("document_kind"),
            "status": review_item.get("status"),
            "review_engine": review_item.get("review_engine"),
            "page_count_processed": review_item.get("page_count_processed"),
            "validation_status": review_item.get("validation_status"),
            "validation_error_count": len(review_item.get("validation_errors") or []),
        },
    )
    if reconciled_items:
        _log_json(
            "Reconciled certificate reviews after cedula processing",
            {
                "reconciled_count": len(reconciled_items),
                "document_kinds": [
                    item.get("document_kind") for item in reconciled_items
                    if item.get("document_kind") is not None
                ][:8],
            },
        )
    if summary_item:
        _log_json(
            "Stored background check final summary",
            {
                "pk": summary_item.get("pk"),
                "sk": summary_item.get("sk"),
                "submission_id": summary_item.get("submission_id"),
                "final_review_status": summary_item.get("final_review_status"),
                "approval_status": summary_item.get("approval_status"),
                "document_kinds": sorted((summary_item.get("final_review_details") or {}).keys()),
            },
        )
    if admin_notification:
        _log_json(
            "Processed background check admin notification",
            {
                "sent": admin_notification.get("sent"),
                "status": admin_notification.get("status"),
                "has_message_id": bool(admin_notification.get("message_id")),
            },
        )
    return {
        "submission_id": job.get("submission_id"),
        "status": "completed",
        "document_kind": document_kind,
        "reconciled_documents": [item.get("document_kind") for item in reconciled_items],
        "final_review_status": (summary_item or {}).get("final_review_status"),
        "admin_notification_status": (admin_notification or {}).get("status"),
    }


def _store_failed_review(job: dict[str, Any], exc: Exception) -> None:
    try:
        submission = _source_submission(job)
    except Exception:
        logger.exception(
            "Failed to load source submission while recording review failure for submission %s.",
            job.get("submission_id"),
        )
        submission = None

    error_type = exc.error_type if isinstance(exc, ReviewProcessingError) else type(exc).__name__
    error_detail = exc.detail if isinstance(exc, ReviewProcessingError) else str(exc)
    failure_item = _review_item(
        job,
        submission,
        {
            "review_error": error_detail,
            "review_error_type": error_type,
        },
        "failed",
    )
    try:
        _store_review(failure_item)
    except Exception:
        logger.exception(
            "Failed to persist review failure for submission %s.",
            job.get("submission_id"),
        )


def _process_job(job: dict[str, Any]) -> dict[str, Any]:
    if str(job.get("form_id") or "").strip() != _background_check_form_id():
        return _ignored_review_result(job, "form_id_mismatch")
    document_kind = str(job.get("document_kind") or "").strip()
    if document_kind not in SUPPORTED_DOCUMENT_KINDS:
        return _ignored_review_result(job, "unsupported_document_kind")

    submission, pdf_bytes = _load_job_dependencies(job)
    try:
        review_payload = _review_payload_for_job(document_kind, pdf_bytes)
    except ReviewProcessingError:
        raise
    except Exception as exc:
        raise ReviewProcessingError("review_extraction_error", f"Failed to extract review data: {exc}") from exc
    review_item = _validated_review_item(job, submission, document_kind, review_payload)
    try:
        _store_review(review_item)
    except Exception as exc:
        raise ReviewProcessingError("review_persistence_error", f"Failed to store review item: {exc}") from exc
    return _postprocess_completed_review(job, review_item)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    records = event.get("Records") or []
    processed: list[dict[str, Any]] = []
    for record in records:
        record_dict = record if isinstance(record, dict) else {}
        job = _fallback_job_for_record(record_dict)
        try:
            job = _parse_record_job(record_dict)
            processed.append(_process_job(job))
        except Exception as exc:
            _store_failed_review(job, exc)
            logger.exception(
                "Failed background check review for submission %s.",
                job.get("submission_id"),
            )
            raise

    _log_json(
        "Processed background check review batch",
        {
            "record_count": len(records),
            "reviews_table": os.getenv("BACKGROUND_CHECK_REVIEWS_TABLE_NAME"),
            "processed_count": len(processed),
            "statuses": sorted(
                {
                    str(item.get("status"))
                    for item in processed
                    if item.get("status") is not None
                }
            ),
            "document_kinds": sorted(
                {
                    str(item.get("document_kind"))
                    for item in processed
                    if item.get("document_kind") is not None
                }
            ),
        },
    )
    return {
        "statusCode": 200,
        "body": json.dumps({"ok": True, "processed": processed}),
    }
