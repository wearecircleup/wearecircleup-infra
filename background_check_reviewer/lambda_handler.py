import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}

EXTRACTION_PROMPT = """Eres un extractor de datos de documentos de identidad colombianos (cedula de
ciudadania formato pre-2020, cedula 2020+ con MRZ, cedula de extranjeria) y
certificados de antecedentes judiciales de la Policia.

Reglas:
- Usa SIEMPRE la herramienta extract_id_document. No respondas en texto plano.
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


def _download_pdf(bucket_name: str, key: str) -> bytes:
    response = _s3_client().get_object(Bucket=bucket_name, Key=key)
    return response["Body"].read()


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int) -> list[bytes]:
    import fitz  # type: ignore

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
                    "antecedentes_judiciales",
                ],
            },
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
                    "resultado_antecedentes": field,
                    "codigo_verificacion": field,
                },
                "required": ["numero_documento", "apellidos", "nombres"],
            },
        },
        "required": ["document_type", "side_processed", "fields"],
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
                        "description": "Extrae campos de un documento de identidad colombiano o certificado de antecedentes.",
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
        "processed_at": processed_at,
        "model_id": _bedrock_model_id(),
        "gsi1pk": f"STATUS#{status}",
        "gsi1sk": f"PROCESSED_AT#{processed_at}#SUBMISSION#{submission_id}",
        "gsi2pk": f"SUBMISSION#{submission_id}",
        "gsi2sk": f"DOCUMENT#{document_kind}",
    }
    if isinstance(contact_email, str) and contact_email.strip():
        item["gsi3pk"] = f"EMAIL#{contact_email.strip().lower()}"
        item["gsi3sk"] = f"SUBMISSION#{submission_id}#DOCUMENT#{document_kind}"
    item.update(result)
    return {key: value for key, value in item.items() if value is not None}


def _store_review(item: dict[str, Any]) -> None:
    _reviews_table().put_item(Item=item)


def _process_job(job: dict[str, Any]) -> dict[str, Any]:
    if str(job.get("form_id") or "").strip() != _background_check_form_id():
        return {
            "submission_id": job.get("submission_id"),
            "status": "ignored",
            "reason": "form_id_mismatch",
        }
    if str(job.get("document_kind") or "").strip() != "cedula":
        return {
            "submission_id": job.get("submission_id"),
            "status": "ignored",
            "reason": "unsupported_document_kind",
        }

    submission = _source_submission(job)
    pdf_bytes = _download_pdf(str(job["s3_bucket"]), str(job["s3_key"]))
    max_pages = int(os.getenv("BACKGROUND_CHECK_REVIEW_MAX_PAGES", "1"))
    images = _render_pdf_pages(pdf_bytes, max_pages=max_pages)
    if not images:
        raise RuntimeError("No rendered images were produced from the PDF.")

    extraction = _extract_document_with_bedrock(images)
    review_item = _review_item(
        job,
        submission,
        {
            "review_payload": extraction.get("tool_input"),
            "review_usage": extraction.get("usage"),
            "review_stop_reason": extraction.get("stop_reason"),
            "page_count_processed": len(images),
        },
        "completed",
    )
    _store_review(review_item)
    logger.info("Stored background check review: %s", json.dumps(review_item, ensure_ascii=False, default=str))
    return {
        "submission_id": job.get("submission_id"),
        "status": "completed",
        "document_kind": job.get("document_kind"),
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
