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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jobs_table():
    table_name = (os.getenv("AUTHORIZATION_JOBS_TABLE_NAME") or "").strip()
    if not table_name:
        return None
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


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _reconcile(item: dict[str, Any]) -> dict[str, Any]:
    jobs_table = _jobs_table()
    event_id = item.get("eventbrite_event_id")
    registration_email = item.get("registration_email")
    submission_id = item.get("submission_id")
    completed_at = item.get("completed_at") or _utc_now()
    authorized_form_id = _authorized_minor_form_id()

    if item.get("form_id") != authorized_form_id:
        logger.info(
            "Skipping minor authorization reconciliation because form_id %s is not the authorized minor form %s.",
            item.get("form_id"),
            authorized_form_id,
        )
        return {"reconciled": False, "reason": "form_id_not_authorized"}

    if jobs_table is None:
        logger.info("Skipping minor authorization reconciliation because AUTHORIZATION_JOBS_TABLE_NAME is not configured.")
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
        gsi1sk = f"COMPLETED_AT#{completed_at}#EVENT#{event_id}#ATTENDEE#{job.get('attendee_id') or 'UNKNOWN_ATTENDEE'}"
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

    result = {
        "reconciled": True,
        "updated_jobs": updated_jobs,
        "submission_id": submission_id,
    }
    logger.info(
        "Reconciled minor authorization submission: %s",
        json.dumps(
            {
                "submission_id": submission_id,
                "event_id": event_id,
                "updated_job_count": len(updated_jobs),
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    return result


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        result = _reconcile(event if isinstance(event, dict) else {})
    except Exception as exc:
        logger.exception("Failed to process minor authorization submission.")
        return _json_response(500, {"ok": False, "detail": str(exc)})
    return _json_response(200, result)
