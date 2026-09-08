import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}


class ProcessingError(RuntimeError):
    def __init__(self, error_type: str, detail: str, retryable: bool = True):
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail
        self.retryable = retryable


def _jobs_table():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    table_name = os.getenv("AUTHORIZATION_JOBS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("AUTHORIZATION_JOBS_TABLE_NAME is not configured.")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _youform_table():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    table_name = os.getenv("YOUFORM_SUBMISSIONS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("YOUFORM_SUBMISSIONS_TABLE_NAME is not configured.")
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _log_json(message: str, payload: dict[str, Any]) -> None:
    logger.info("%s: %s", message, json.dumps(payload, ensure_ascii=False, default=str))


def _normalized_email(attendee_email: Any, buyer_email: Any) -> str | None:
    for value in (attendee_email, buyer_email):
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _required_job_value(job: dict[str, Any], field_name: str) -> str:
    value = job.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ProcessingError("missing_job_field", f"Missing required job field: {field_name}", retryable=False)


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": record.get("messageId"),
        "body_present": isinstance(record.get("body"), str),
    }


def _parse_record_job(record: dict[str, Any]) -> dict[str, Any]:
    body = record.get("body") or "{}"
    try:
        job = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProcessingError("invalid_record_body", "Record body is not valid JSON.", retryable=False) from exc
    if not isinstance(job, dict):
        raise ProcessingError("invalid_record_body", "Record body must decode to a JSON object.", retryable=False)
    return job


def _validate_job(job: dict[str, Any]) -> dict[str, Any]:
    _required_job_value(job, "event_id")
    _required_job_value(job, "attendee_id")
    return job


def _job_keys(job: dict[str, Any]) -> tuple[str, str]:
    return (
        f"EVENT#{job.get('event_id') or 'UNKNOWN_EVENT'}",
        f"ATTENDEE#{job.get('attendee_id') or 'UNKNOWN_ATTENDEE'}",
    )


def _build_job_item(job: dict[str, Any]) -> dict[str, Any]:
    event_id = str(job.get("event_id") or "UNKNOWN_EVENT")
    attendee_id = str(job.get("attendee_id") or "UNKNOWN_ATTENDEE")
    first_seen_at = str(job.get("detected_at") or _utc_now())
    normalized_email = _normalized_email(job.get("attendee_email"), job.get("buyer_email"))
    item = {
        "pk": f"EVENT#{event_id}",
        "sk": f"ATTENDEE#{attendee_id}",
        "entity_type": "minor_authorization_validation",
        "event_id": event_id,
        "event_name": job.get("event_name"),
        "event_url": job.get("event_url"),
        "event_date": job.get("event_date"),
        "event_time": job.get("event_time"),
        "event_timezone": job.get("event_timezone"),
        "venue_name": job.get("venue_name"),
        "venue_city": job.get("venue_city"),
        "venue_region": job.get("venue_region"),
        "order_id": job.get("order_id"),
        "order_created": job.get("order_created"),
        "order_status": job.get("order_status"),
        "attendee_id": attendee_id,
        "attendee_email": job.get("attendee_email"),
        "buyer_email": job.get("buyer_email"),
        "age_range": job.get("age_range"),
        "status": "pending",
        "validation_result": "unknown",
        "action_taken": "none",
        "attempt_count": 0,
        "max_attempts": int(os.getenv("AUTHORIZATION_MAX_ATTEMPTS", "5")),
        "first_seen_at": first_seen_at,
        "authorization_found": False,
        "delete_attempted": False,
        "delete_succeeded": False,
        "request_id": job.get("request_id"),
        "source": job.get("source") or "eventbrite_order_webhook",
        "gsi1pk": "STATUS#pending",
        "gsi1sk": f"FIRST_SEEN_AT#{first_seen_at}#EVENT#{event_id}#ATTENDEE#{attendee_id}",
    }
    if normalized_email:
        item["gsi2pk"] = f"EMAIL#{normalized_email}"
        item["gsi2sk"] = f"EVENT#{event_id}#ATTENDEE#{attendee_id}"
    return {key: value for key, value in item.items() if value is not None}


def _job_exists(table, pk: str, sk: str) -> bool:
    response = table.get_item(Key={"pk": pk, "sk": sk})
    return bool(response.get("Item"))


def _find_matching_youform_submission(job: dict[str, Any]) -> dict[str, Any] | None:
    normalized_email = _normalized_email(job.get("attendee_email"), job.get("buyer_email"))
    event_id = str(job.get("event_id") or "").strip()
    authorized_form_id = _authorized_minor_form_id()
    if not normalized_email or not event_id:
        return None

    response = _youform_table().query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"EMAIL#{normalized_email}"),
    )
    items = response.get("Items") or []
    for item in items:
        # Email + event_id is not enough once the webhook stores multiple forms in
        # the same table; we must require the configured authorization form_id.
        if (
            item.get("form_id") == authorized_form_id
            and item.get("eventbrite_event_id") == event_id
            and item.get("completed_at")
            and item.get("submission_id")
        ):
            return item
    return None


def _validation_outcome(
    job: dict[str, Any],
    matched_submission: dict[str, Any] | None,
    processed_at: str,
) -> dict[str, Any]:
    status = "authorized" if matched_submission else "missing_form"
    validation_result = "form_found" if matched_submission else "form_missing"
    return {
        "status": status,
        "validation_result": validation_result,
        "authorization_found": bool(matched_submission),
        "matched_submission_id": matched_submission.get("submission_id") if matched_submission else None,
        "processed_at": processed_at,
        "gsi1pk": f"STATUS#{status}",
        "gsi1sk": (
            f"COMPLETED_AT#{processed_at}#EVENT#{job.get('event_id') or 'UNKNOWN_EVENT'}"
            f"#ATTENDEE#{job.get('attendee_id') or 'UNKNOWN_ATTENDEE'}"
        ),
    }


def _update_job_validation_result(table, pk: str, sk: str, job: dict[str, Any]) -> dict[str, Any]:
    matched_submission = _find_matching_youform_submission(job)
    processed_at = _utc_now()
    outcome = _validation_outcome(job, matched_submission, processed_at)
    update_values = {
        ":status": outcome["status"],
        ":validation_result": outcome["validation_result"],
        ":authorization_found": outcome["authorization_found"],
        ":matched_submission_id": outcome["matched_submission_id"],
        ":completed_at": outcome["processed_at"],
        ":last_attempt_at": outcome["processed_at"],
        ":attempt_count": 1,
        ":gsi1pk": outcome["gsi1pk"],
        ":gsi1sk": outcome["gsi1sk"],
    }
    table.update_item(
        Key={"pk": pk, "sk": sk},
        UpdateExpression=(
            "SET #status = :status, "
            "validation_result = :validation_result, "
            "authorization_found = :authorization_found, "
            "matched_submission_id = :matched_submission_id, "
            "completed_at = :completed_at, "
            "last_attempt_at = :last_attempt_at, "
            "attempt_count = :attempt_count, "
            "gsi1pk = :gsi1pk, "
            "gsi1sk = :gsi1sk"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=update_values,
    )
    logger.info(
        "Updated minor authorization job validation result: %s",
        json.dumps(
            {
                "pk": pk,
                "sk": sk,
                "status": outcome["status"],
                "validation_result": outcome["validation_result"],
                "matched_submission_id": outcome["matched_submission_id"],
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    return {
        "status": outcome["status"],
        "validation_result": outcome["validation_result"],
        "authorization_found": outcome["authorization_found"],
        "matched_submission_id": outcome["matched_submission_id"],
    }


def _store_job(job: dict[str, Any]) -> dict[str, Any]:
    table = _jobs_table()
    pk, sk = _job_keys(job)
    if _job_exists(table, pk, sk):
        _log_json(
            "Minor authorization job already exists",
            {
                "pk": pk,
                "sk": sk,
                "event_id": job.get("event_id"),
                "attendee_id": job.get("attendee_id"),
            },
        )
        return {
            "stored": False,
            "reason": "already_exists",
            "pk": pk,
            "sk": sk,
        }
    item = _build_job_item(job)
    table.put_item(Item=item)
    _log_json(
        "Stored minor authorization job",
        {
            "pk": item.get("pk"),
            "sk": item.get("sk"),
            "event_id": item.get("event_id"),
            "attendee_id": item.get("attendee_id"),
            "has_email_index": bool(item.get("gsi2pk")),
        },
    )
    stored_result = {
        "stored": True,
        "pk": item["pk"],
        "sk": item["sk"],
        "status": item["status"],
    }
    stored_result.update(_update_job_validation_result(table, pk, sk, job))
    return stored_result


def _failed_job_result(job: dict[str, Any], exc: Exception) -> dict[str, Any]:
    error_type = exc.error_type if isinstance(exc, ProcessingError) else type(exc).__name__
    detail = exc.detail if isinstance(exc, ProcessingError) else str(exc)
    return {
        "stored": False,
        "reason": "failed",
        "event_id": job.get("event_id"),
        "attendee_id": job.get("attendee_id"),
        "error_type": error_type,
        "detail": detail,
    }


def _log_processing_failure(job: dict[str, Any], record: dict[str, Any], exc: Exception) -> None:
    error_type = exc.error_type if isinstance(exc, ProcessingError) else type(exc).__name__
    detail = exc.detail if isinstance(exc, ProcessingError) else str(exc)
    _log_json(
        "Minor authorization validation failed",
        {
            "record": _record_summary(record),
            "job": {
                "event_id": job.get("event_id"),
                "attendee_id": job.get("attendee_id"),
                "attendee_email": job.get("attendee_email"),
                "buyer_email": job.get("buyer_email"),
            },
            "error_type": error_type,
            "detail": detail,
        },
    )


def _batch_summary(records: list[Any], processed: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(records),
        "jobs_table": os.getenv("AUTHORIZATION_JOBS_TABLE_NAME"),
        "youform_table": os.getenv("YOUFORM_SUBMISSIONS_TABLE_NAME"),
        "eventbrite_table": os.getenv("EVENTBRITE_ORDER_SUBMISSIONS_TABLE_NAME"),
        "processed_count": len(processed),
        "status_counts": {
            status: sum(1 for item in processed if item.get("status") == status)
            for status in sorted({str(item.get("status")) for item in processed if item.get("status") is not None})
        },
        "error_types": sorted(
            {
                str(item.get("error_type"))
                for item in processed
                if item.get("error_type") is not None
            }
        ),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    records = event.get("Records") or []
    processed: list[dict[str, Any]] = []
    for record in records:
        record_dict = record if isinstance(record, dict) else {}
        job = {
            "event_id": None,
            "attendee_id": None,
            "attendee_email": None,
            "buyer_email": None,
        }
        try:
            job = _parse_record_job(record_dict)
            _validate_job(job)
            processed.append(_store_job(job))
        except Exception as exc:
            _log_processing_failure(job, record_dict, exc)
            if isinstance(exc, ProcessingError) and not exc.retryable:
                processed.append(_failed_job_result(job, exc))
                continue
            raise

    _log_json("Received minor authorization validation batch", _batch_summary(records, processed))
    return {
        "ok": True,
        "record_count": len(records),
        "processed": processed,
    }
