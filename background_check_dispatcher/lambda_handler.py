import json
import logging
import os
import re
import unicodedata
from typing import Any

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}


def _sqs_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sqs", region_name=region)


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


def _background_check_form_id() -> str:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret = _load_secret(secret_id)
        value = (secret.get("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID") or "").strip()
        if value:
            return value
        raise RuntimeError(f"VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID is missing in secret {secret_id}.")
    value = (os.getenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID") or "").strip()
    if value:
        return value
    raise RuntimeError("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID is not configured.")


def _background_check_queue_url() -> str:
    value = os.getenv("BACKGROUND_CHECK_REVIEW_QUEUE_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError("BACKGROUND_CHECK_REVIEW_QUEUE_URL is not configured.")


def _ascii_normalized(value: str) -> str:
    raw = str(value or "")
    cleaned = raw.strip().lower()
    ascii_text = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _parse_s3_uri(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith("s3://"):
        return None
    without_scheme = value[5:]
    bucket_name, _, key = without_scheme.partition("/")
    if not bucket_name or not key:
        return None
    return bucket_name, key


def _background_check_document_kind(question: str, stored_answer: Any) -> str | None:
    parsed = _parse_s3_uri(stored_answer)
    if parsed is None:
        return None
    _, key = parsed
    if not key.lower().endswith(".pdf"):
        return None
    combined = f"{_ascii_normalized(question)} {_ascii_normalized(os.path.basename(key))}"
    if "inhabilidad" in combined or "inhabilidades" in combined:
        return "antecedentes_inhabilidades"
    if "antecedentes judiciales" in combined or ("judicial" in combined and "antecedente" in combined):
        return "antecedentes_judiciales"
    if any(marker in combined for marker in ("cedula", "documento de identidad", "documento identidad", "identificacion")):
        return "cedula"
    return None


def _review_messages(item: dict[str, Any]) -> list[dict[str, Any]]:
    answers = item.get("answers")
    if not isinstance(answers, list):
        return []
    messages: list[dict[str, Any]] = []
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        question = str(answer.get("question") or "").strip()
        stored_answer = answer.get("answer")
        document_kind = _background_check_document_kind(question, stored_answer)
        if not question or not document_kind:
            continue
        parsed = _parse_s3_uri(stored_answer)
        if parsed is None:
            continue
        bucket_name, key = parsed
        messages.append(
            {
                "source": "background_check_dispatcher",
                "document_kind": document_kind,
                "form_id": item.get("form_id"),
                "submission_id": item.get("submission_id"),
                "submission_pk": item.get("pk"),
                "submission_sk": item.get("sk"),
                "question": question,
                "s3_uri": stored_answer,
                "s3_bucket": bucket_name,
                "s3_key": key,
                "contact_name": item.get("contact_name"),
                "contact_email": item.get("contact_email"),
                "contact_phone": item.get("contact_phone"),
                "completed_at": item.get("completed_at"),
            }
        )
    return messages


def _dispatch(item: dict[str, Any]) -> dict[str, Any]:
    if str(item.get("form_id") or "").strip() != _background_check_form_id():
        logger.info(
            "Skipping background check dispatch for submission %s because form_id %s does not match the configured compliance form.",
            item.get("submission_id"),
            item.get("form_id"),
        )
        return {"dispatched": False, "reason": "form_id_mismatch", "submission_id": item.get("submission_id")}

    messages = _review_messages(item)
    if not messages:
        return {"dispatched": False, "reason": "no_documents_detected", "submission_id": item.get("submission_id")}

    published: list[dict[str, Any]] = []
    client = _sqs_client()
    queue_url = _background_check_queue_url()
    for message in messages:
        response = client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message, ensure_ascii=False, default=str),
        )
        published.append(
            {
                "submission_id": message.get("submission_id"),
                "document_kind": message.get("document_kind"),
                "message_id": response.get("MessageId"),
            }
        )

    result = {
        "dispatched": True,
        "submission_id": item.get("submission_id"),
        "job_count": len(published),
        "document_kinds": [job["document_kind"] for job in published],
        "jobs": published,
    }
    logger.info(
        "Dispatched background check jobs: %s",
        json.dumps(
            {
                "submission_id": item.get("submission_id"),
                "job_count": len(published),
                "document_kinds": result["document_kinds"],
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    return result


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        result = _dispatch(event if isinstance(event, dict) else {})
    except Exception as exc:
        logger.exception("Failed to dispatch background check review jobs.")
        return _json_response(500, {"ok": False, "detail": str(exc)})
    return _json_response(200, result)
