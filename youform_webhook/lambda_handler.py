import base64
import json
import logging
import mimetypes
import os
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}

SIGNATURE_QUESTION = "Firma para autorizar"
EVENT_URL_QUESTION = "¿A qué evento asiste?"
EVENT_DATE_QUESTION = "¿Qué día es el evento?"
REGISTRATION_EMAIL_QUESTION = "¿Con qué correo vas a realizar la inscripción?"
UNKNOWN_EVENT_ID = "UNKNOWN_EVENT"


def _clean_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if not any(marker in value for marker in ("Ã", "Â", "â", "Ð")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _normalized_question_key(value: str) -> str:
    cleaned = _clean_text(value)
    return " ".join(str(cleaned).strip().lower().split())


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


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


def _authorized_minor_form_id() -> str:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret = _load_secret(secret_id)
        value = (secret.get("AUTHORIZED_MINOR_FORM_ID") or "").strip()
        if value:
            return value
        raise RuntimeError(f"AUTHORIZED_MINOR_FORM_ID is missing in secret {secret_id}.")
    value = (os.getenv("AUTHORIZED_MINOR_FORM_ID") or "").strip()
    if value:
        return value
    raise RuntimeError("AUTHORIZED_MINOR_FORM_ID is not configured.")


def _minor_authorization_jobs_table():
    table_name = os.getenv("MINOR_AUTHORIZATION_JOBS_TABLE_NAME")
    if not table_name:
        return None
    return _dynamodb_table(table_name)


def _s3_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("s3", region_name=region)


def _decoded_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body).decode("utf-8")
        except Exception:
            logger.exception("Failed to decode base64 webhook body.")
            return body
    return body


def _signature_storage_location(parsed_body: dict[str, Any], signature_url: str) -> tuple[str, str] | None:
    bucket_name = os.getenv("SIGNATURES_BUCKET_NAME")
    submission_id = parsed_body.get("submission_id")
    if not bucket_name or not submission_id:
        return None
    parsed = urlparse(signature_url)
    extension = os.path.splitext(parsed.path)[1].lower()
    if not extension:
        extension = ".png"
    key = f"youform-signatures/{submission_id}/signature{extension}"
    return bucket_name, key


def _download_signature(signature_url: str) -> tuple[bytes, str | None]:
    request = Request(
        signature_url,
        headers={
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=20) as response:
        content = response.read()
        content_type = response.headers.get_content_type() if response.headers else None
    return content, content_type


def _store_signature(parsed_body: dict[str, Any], signature_url: str) -> str:
    location = _signature_storage_location(parsed_body, signature_url)
    if location is None:
        raise RuntimeError("SIGNATURES_BUCKET_NAME and submission_id are required to store signatures.")
    bucket_name, key = location
    content, content_type = _download_signature(signature_url)
    if not content_type:
        guessed, _ = mimetypes.guess_type(signature_url)
        content_type = guessed or "application/octet-stream"
    _s3_client().put_object(
        Bucket=bucket_name,
        Key=key,
        Body=content,
        ContentType=content_type,
    )
    logger.info("Stored YouForm signature for submission %s at s3://%s/%s", parsed_body.get("submission_id"), bucket_name, key)
    return f"s3://{bucket_name}/{key}"


def _normalize_answers(parsed_body: dict[str, Any]) -> list[dict[str, Any]]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return []
    normalized: list[dict[str, Any]] = []
    for question, answer in answers.items():
        normalized_answer = answer
        if str(question) == SIGNATURE_QUESTION and isinstance(answer, str) and answer.strip():
            try:
                normalized_answer = _store_signature(parsed_body, answer.strip())
            except Exception:
                logger.exception(
                    "Failed to copy YouForm signature for submission %s. Keeping original URL.",
                    parsed_body.get("submission_id"),
                )
        normalized.append({"question": str(question), "answer": normalized_answer})
    return normalized


def _answer_lookup(parsed_body: dict[str, Any]) -> dict[str, Any]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return {}
    return {
        _normalized_question_key(str(question)): answer
        for question, answer in answers.items()
    }


def _extract_eventbrite_event_metadata(event_url: Any) -> dict[str, str | None]:
    if not isinstance(event_url, str) or not event_url.strip():
        return {
            "eventbrite_event_url": None,
            "eventbrite_event_id": None,
            "eventbrite_event_slug": None,
            "eventbrite_event_name": None,
        }
    cleaned_url = event_url.strip()
    match = re.search(r"/e/([^/?#]+)-tickets-(\d+)", cleaned_url)
    if not match:
        return {
            "eventbrite_event_url": cleaned_url,
            "eventbrite_event_id": None,
            "eventbrite_event_slug": None,
            "eventbrite_event_name": None,
        }
    slug = match.group(1)
    return {
        "eventbrite_event_url": cleaned_url,
        "eventbrite_event_id": match.group(2),
        "eventbrite_event_slug": slug,
        "eventbrite_event_name": slug.replace("-", " "),
    }


def _build_keys(
    eventbrite_event_id: str | None,
    form_id: Any,
    submission_id: Any,
    registrant_email: str | None,
    event_date: str | None,
    completed_at: str | None,
) -> dict[str, str]:
    safe_event_id = eventbrite_event_id or UNKNOWN_EVENT_ID
    safe_form_id = str(form_id or "UNKNOWN_FORM")
    safe_submission_id = str(submission_id or "UNKNOWN_SUBMISSION")
    keys = {
        "pk": f"EVENT#{safe_event_id}#FORM#{safe_form_id}",
        "sk": f"SUBMISSION#{safe_submission_id}",
        "gsi1pk": f"EVENT#{safe_event_id}",
        "gsi1sk": f"COMPLETED_AT#{completed_at or 'UNKNOWN'}#SUBMISSION#{safe_submission_id}",
    }
    if registrant_email:
        normalized_email = registrant_email.strip().lower()
        keys["gsi2pk"] = f"EMAIL#{normalized_email}"
        keys["gsi2sk"] = f"EVENT_DATE#{event_date or 'UNKNOWN'}#EVENT#{safe_event_id}#SUBMISSION#{safe_submission_id}"
    if event_date:
        keys["gsi3pk"] = f"EVENT_DATE#{event_date}"
        keys["gsi3sk"] = (
            f"EVENT#{safe_event_id}#EMAIL#{(registrant_email or 'UNKNOWN').strip().lower()}#SUBMISSION#{safe_submission_id}"
        )
    return keys


def _build_submission_item(parsed_body: dict[str, Any]) -> dict[str, Any] | None:
    submission_id = parsed_body.get("submission_id")
    if not submission_id:
        return None
    answer_lookup = _answer_lookup(parsed_body)
    event_metadata = _extract_eventbrite_event_metadata(
        answer_lookup.get(_normalized_question_key(EVENT_URL_QUESTION))
    )
    event_date = answer_lookup.get(_normalized_question_key(EVENT_DATE_QUESTION))
    registrant_email = answer_lookup.get(_normalized_question_key(REGISTRATION_EMAIL_QUESTION))
    completed_at = parsed_body.get("completed_at")
    item = {
        **_build_keys(
            event_metadata["eventbrite_event_id"],
            parsed_body.get("form_id"),
            submission_id,
            registrant_email if isinstance(registrant_email, str) else None,
            event_date if isinstance(event_date, str) else None,
            completed_at if isinstance(completed_at, str) else None,
        ),
        "entity_type": "youform_submission",
        "submission_id": submission_id,
        "form_id": parsed_body.get("form_id"),
        "form_name": parsed_body.get("form_name"),
        "youform_event_id": parsed_body.get("event_id"),
        "event_type": parsed_body.get("event_type"),
        "started_at": parsed_body.get("started_at"),
        "completed_at": completed_at,
        "eventbrite_event_id": event_metadata["eventbrite_event_id"],
        "eventbrite_event_slug": event_metadata["eventbrite_event_slug"],
        "eventbrite_event_name": event_metadata["eventbrite_event_name"],
        "eventbrite_event_url": event_metadata["eventbrite_event_url"],
        "event_date": event_date,
        "registration_email": registrant_email.lower().strip() if isinstance(registrant_email, str) else None,
        "answers": _normalize_answers(parsed_body),
    }
    return {key: value for key, value in item.items() if value is not None}


def _reconcile_minor_authorization_job(item: dict[str, Any]) -> dict[str, Any]:
    jobs_table = _minor_authorization_jobs_table()
    event_id = item.get("eventbrite_event_id")
    registration_email = item.get("registration_email")
    submission_id = item.get("submission_id")
    completed_at = item.get("completed_at")
    authorized_form_id = _authorized_minor_form_id()

    # This webhook can be reused by multiple YouForm forms, but only the legal
    # minor-authorization form is allowed to mark a validation job as authorized.
    if item.get("form_id") != authorized_form_id:
        logger.info(
            "Skipping minor authorization reconciliation because form_id %s is not the authorized minor form %s.",
            item.get("form_id"),
            authorized_form_id,
        )
        return {"reconciled": False, "reason": "form_id_not_authorized"}

    if jobs_table is None:
        logger.info("Skipping minor authorization reconciliation because MINOR_AUTHORIZATION_JOBS_TABLE_NAME is not configured.")
        return {"reconciled": False, "reason": "jobs_table_not_configured"}
    if not event_id or not registration_email:
        logger.info(
            "Skipping minor authorization reconciliation because event_id or registration_email is missing for submission %s.",
            submission_id,
        )
        return {"reconciled": False, "reason": "missing_event_or_email"}

    response = jobs_table.query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"EMAIL#{registration_email}"),
    )
    items = response.get("Items") or []
    matching_jobs = [
        job for job in items
        if job.get("event_id") == event_id and job.get("status") in {"pending", "missing_form"}
    ]
    if not matching_jobs:
        logger.info(
            "No pending minor authorization job matched submission %s for event %s and email %s.",
            submission_id,
            event_id,
            registration_email,
        )
        return {"reconciled": False, "reason": "no_matching_job"}

    updated_jobs: list[dict[str, Any]] = []
    for job in matching_jobs:
        pk = job["pk"]
        sk = job["sk"]
        gsi1sk = f"COMPLETED_AT#{completed_at or 'UNKNOWN'}#EVENT#{event_id}#ATTENDEE#{job.get('attendee_id') or 'UNKNOWN_ATTENDEE'}"
        jobs_table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=(
                "SET #status = :status, "
                "validation_result = :validation_result, "
                "authorization_found = :authorization_found, "
                "matched_submission_id = :matched_submission_id, "
                "completed_at = :completed_at, "
                "last_attempt_at = :last_attempt_at, "
                "gsi1pk = :gsi1pk, "
                "gsi1sk = :gsi1sk"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "authorized",
                ":validation_result": "form_found",
                ":authorization_found": True,
                ":matched_submission_id": submission_id,
                ":completed_at": completed_at,
                ":last_attempt_at": completed_at,
                ":gsi1pk": "STATUS#authorized",
                ":gsi1sk": gsi1sk,
            },
        )
        updated_jobs.append({"pk": pk, "sk": sk})

    logger.info(
        "Reconciled minor authorization jobs from YouForm submission %s: %s",
        submission_id,
        json.dumps(updated_jobs, ensure_ascii=False, default=str),
    )
    return {
        "reconciled": True,
        "updated_jobs": updated_jobs,
        "submission_id": submission_id,
    }


def _store_submission(parsed_body: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    table_name = os.getenv("SUBMISSIONS_TABLE_NAME")
    if not table_name:
        logger.warning("SUBMISSIONS_TABLE_NAME is not configured; skipping persistence.")
        return False, None
    item = _build_submission_item(parsed_body)
    if item is None:
        logger.info("Skipping persistence because submission_id is missing.")
        return False, None
    _dynamodb_table(table_name).put_item(Item=item)
    logger.info("Stored YouForm submission %s in DynamoDB table %s.", item["submission_id"], table_name)
    return True, item


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    raw_body = _decoded_body(event)
    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_body = None

    stored = False
    reconciliation: dict[str, Any] | None = None
    if isinstance(parsed_body, dict):
        stored, item = _store_submission(parsed_body)
        if stored and item is not None:
            reconciliation = _reconcile_minor_authorization_job(item)

    logger.info(
        "Received YouForm webhook: %s",
        json.dumps(
            {
                "request_context": event.get("requestContext"),
                "raw_body": raw_body,
                "parsed_body": parsed_body,
                "stored": stored,
                "reconciliation": reconciliation,
            },
            ensure_ascii=False,
            default=str,
        ),
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "ok": True,
                "message": "YouForm webhook received.",
                "stored": stored,
                "reconciliation": reconciliation,
            }
        ),
    }
