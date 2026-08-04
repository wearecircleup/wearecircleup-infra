import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGE_RANGE_QUESTION = "¿Cuál es tu rango de edad?"
MINOR_AGE_RANGE_ANSWER = "14 a 17 años"


def _log_json(message: str, payload: dict[str, Any]) -> None:
    logger.info("%s: %s", message, json.dumps(payload, ensure_ascii=False, default=str))


def _clean_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if not any(marker in value for marker in ("Ã", "Â", "â", "Ð")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _sqs_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sqs", region_name=region)


def _load_secret(secret_id: str) -> dict[str, str]:
    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    payload = response.get("SecretString")
    if not payload:
        raise RuntimeError(f"Secret {secret_id} does not contain SecretString.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"Secret {secret_id} must contain a JSON object.")
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _eventbrite_private_token() -> str:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret = _load_secret(secret_id)
        private_token = secret.get("EVENTBRITE_PRIVATE_TOKEN")
        if private_token:
            return private_token
    private_token = os.getenv("EVENTBRITE_PRIVATE_TOKEN")
    if not private_token:
        raise RuntimeError("EVENTBRITE_PRIVATE_TOKEN is not configured.")
    return private_token


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _request_json(url: str, token: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.exception("Eventbrite request failed for %s with status %s: %s", url, exc.code, detail)
        raise RuntimeError(f"Eventbrite request failed with status {exc.code}.") from exc
    except URLError as exc:
        logger.exception("Eventbrite request failed for %s", url)
        raise RuntimeError("Eventbrite request failed.") from exc


def _extract_order_id(api_url: str) -> str | None:
    parsed = urlparse(api_url)
    if parsed.netloc not in {"www.eventbriteapi.com", "eventbriteapi.com"}:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 3 or segments[0] != "v3" or segments[1] != "orders":
        return None
    return segments[2]


def _normalize_attendee(attendee: dict[str, Any]) -> dict[str, Any]:
    profile = attendee.get("profile") or {}
    answers = attendee.get("answers") or []
    barcodes = attendee.get("barcodes") or []
    return {
        "attendee_id": str(attendee.get("id") or ""),
        "event_id": attendee.get("event_id"),
        "order_id": attendee.get("order_id"),
        "created": attendee.get("created"),
        "changed": attendee.get("changed"),
        "status": attendee.get("status"),
        "checked_in": bool(attendee.get("checked_in")),
        "cancelled": bool(attendee.get("cancelled")),
        "refunded": bool(attendee.get("refunded")),
        "ticket_class_id": attendee.get("ticket_class_id"),
        "ticket_class_name": _clean_text(attendee.get("ticket_class_name")),
        "quantity": attendee.get("quantity"),
        "delivery_method": attendee.get("delivery_method"),
        "profile": {
            "name": _clean_text(profile.get("name")),
            "first_name": _clean_text(profile.get("first_name")),
            "last_name": _clean_text(profile.get("last_name")),
            "email": profile.get("email"),
        },
        "barcodes": [
            {
                "barcode": barcode.get("barcode"),
                "status": barcode.get("status"),
                "qr_code_url": barcode.get("qr_code_url"),
            }
            for barcode in barcodes
        ],
        "answers": [
            {
                "question_id": str(answer.get("question_id") or ""),
                "question": _clean_text(answer.get("question")),
                "answer": _clean_text(answer.get("answer")),
                "type": answer.get("type"),
            }
            for answer in answers
        ],
    }


def _fetch_all_order_attendees(order_id: str, token: str) -> list[dict[str, Any]]:
    base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
    attendees: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _request_json(f"{base_url}/orders/{order_id}/attendees/?page={page}", token)
        attendees.extend(response.get("attendees", []))
        if not (response.get("pagination") or {}).get("has_more_items"):
            return attendees
        page += 1


def _fetch_event(event_id: str, token: str) -> dict[str, Any]:
    base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
    return _request_json(f"{base_url}/events/{event_id}/", token)


def _fetch_venue(venue_id: str, token: str) -> dict[str, Any]:
    base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
    return _request_json(f"{base_url}/venues/{venue_id}/", token)


def _event_datetime_parts(event: dict[str, Any]) -> tuple[str | None, str | None]:
    start_local = ((event.get("start") or {}).get("local")) or ""
    if "T" not in start_local:
        return None, None
    event_date, event_time = start_local.split("T", 1)
    return event_date or None, event_time or None


def _build_submission_item(
    webhook_payload: dict[str, Any],
    order: dict[str, Any],
    event_details: dict[str, Any],
    venue_details: dict[str, Any],
    attendees: list[dict[str, Any]],
    received_at: str,
) -> dict[str, Any]:
    order_id = str(order["id"])
    event_date, event_time = _event_datetime_parts(event_details)
    venue_address = venue_details.get("address") or {}
    return {
        "pk": f"ORDER#{order_id}",
        "sk": f"ORDER#{order_id}",
        "entity_type": "eventbrite_order",
        "order_id": order_id,
        "event_id": order.get("event_id"),
        "event_name": _clean_text(((event_details.get("name") or {}).get("text"))),
        "event_date": event_date,
        "event_time": event_time,
        "event_timezone": ((event_details.get("start") or {}).get("timezone")),
        "venue_id": event_details.get("venue_id"),
        "venue_name": _clean_text(venue_details.get("name")),
        "venue_address": _clean_text(venue_address.get("localized_address_display")),
        "venue_city": _clean_text(venue_address.get("city")),
        "venue_region": _clean_text(venue_address.get("region")),
        "venue_country": _clean_text(venue_address.get("country")),
        "order_status": order.get("status"),
        "order_created": order.get("created"),
        "order_changed": order.get("changed"),
        "attendee_count": len(attendees),
        "buyer": {
            "name": _clean_text(order.get("name")),
            "first_name": _clean_text(order.get("first_name")),
            "last_name": _clean_text(order.get("last_name")),
            "email": order.get("email"),
        },
        "attendees": [_normalize_attendee(attendee) for attendee in attendees],
        "webhook": {
            "api_url": webhook_payload.get("api_url"),
            "received_at": received_at,
            "action": ((webhook_payload.get("config") or {}).get("action")),
            "webhook_id": ((webhook_payload.get("config") or {}).get("webhook_id")),
        },
    }


def _is_minor_attendee(attendee: dict[str, Any]) -> tuple[bool, str | None]:
    for answer in attendee.get("answers") or []:
        question = _clean_text(answer.get("question"))
        value = _clean_text(answer.get("answer"))
        if question == AGE_RANGE_QUESTION and value == MINOR_AGE_RANGE_ANSWER:
            return True, value
    return False, None


def _build_minor_authorization_jobs(
    item: dict[str, Any],
    request_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    detected_at = (
        (request_context or {}).get("time")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    buyer = item.get("buyer") or {}
    for attendee in item.get("attendees") or []:
        is_minor, age_range = _is_minor_attendee(attendee)
        if not is_minor:
            continue
        profile = attendee.get("profile") or {}
        attendee_email = profile.get("email")
        buyer_email = buyer.get("email")
        jobs.append(
            {
                "event_id": item.get("event_id"),
                "order_id": item.get("order_id"),
                "attendee_id": attendee.get("attendee_id"),
                "attendee_email": attendee_email,
                "buyer_email": buyer_email,
                "age_range": age_range,
                "detected_at": detected_at,
                "request_id": (request_context or {}).get("requestId"),
                "source": "eventbrite_order_webhook",
            }
        )
    return jobs


def _enqueue_minor_authorization_jobs(
    item: dict[str, Any],
    request_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    queue_url = os.getenv("AUTHORIZATION_QUEUE_URL")
    jobs = _build_minor_authorization_jobs(item, request_context)
    if not jobs:
        _log_json(
            "No minor authorization jobs detected for Eventbrite order",
            {
                "order_id": item.get("order_id"),
                "event_id": item.get("event_id"),
                "attendee_count": item.get("attendee_count"),
            },
        )
        return []
    if not queue_url:
        logger.warning(
            "AUTHORIZATION_QUEUE_URL is not configured. Minor authorization jobs were detected but not enqueued."
        )
        _log_json(
            "Minor authorization jobs skipped because queue is not configured",
            {
                "order_id": item.get("order_id"),
                "event_id": item.get("event_id"),
                "jobs": jobs,
            },
        )
        return []

    client = _sqs_client()
    enqueued_jobs: list[dict[str, Any]] = []
    for job in jobs:
        response = client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(job, ensure_ascii=False))
        enqueued_job = {
            **job,
            "message_id": response.get("MessageId"),
        }
        enqueued_jobs.append(enqueued_job)
        _log_json(
            "Enqueued minor authorization validation job",
            {
                "queue_url": queue_url,
                "message_id": response.get("MessageId"),
                "job": job,
            },
        )
    return enqueued_jobs


def _store_order_submission(webhook_payload: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
    api_url = webhook_payload.get("api_url")
    if not api_url:
        logger.info("Skipping Eventbrite webhook persistence because api_url is missing.")
        return {"stored": False, "reason": "missing_api_url"}

    order_id = _extract_order_id(str(api_url))
    if not order_id:
        logger.info("Skipping Eventbrite webhook persistence because api_url is unsupported: %s", api_url)
        return {"stored": False, "reason": "unsupported_api_url"}

    table_name = os.getenv("SUBMISSIONS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("SUBMISSIONS_TABLE_NAME is not configured.")

    token = _eventbrite_private_token()
    order = _request_json(str(api_url), token)
    _log_json(
        "Eventbrite order fetched from webhook api_url",
        {
            "api_url": api_url,
            "order_id": order.get("id"),
            "event_id": order.get("event_id"),
            "status": order.get("status"),
            "email": order.get("email"),
            "changed": order.get("changed"),
        },
    )
    _log_json("Eventbrite raw order payload", order)
    event_id = order.get("event_id")
    event_details = _fetch_event(str(event_id), token) if event_id else {}
    _log_json(
        "Eventbrite event fetched from order event_id",
        {
            "event_id": event_id,
            "event_name": _clean_text(((event_details.get("name") or {}).get("text"))),
            "event_start_local": ((event_details.get("start") or {}).get("local")),
            "event_timezone": ((event_details.get("start") or {}).get("timezone")),
            "venue_id": event_details.get("venue_id"),
        },
    )
    venue_id = event_details.get("venue_id")
    venue_details = _fetch_venue(str(venue_id), token) if venue_id else {}
    _log_json(
        "Eventbrite venue fetched from event venue_id",
        {
            "event_id": event_id,
            "venue_id": venue_id,
            "venue_name": _clean_text(venue_details.get("name")),
            "venue_address": _clean_text(((venue_details.get("address") or {}).get("localized_address_display"))),
        },
    )
    attendees = _fetch_all_order_attendees(order_id, token)
    _log_json(
        "Eventbrite raw order attendees payload",
        {
            "order_id": order_id,
            "attendee_count": len(attendees),
            "attendees": attendees,
        },
    )
    received_at = (
        (request_context or {}).get("time")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    item = _build_submission_item(webhook_payload, order, event_details, venue_details, attendees, received_at)
    _dynamodb_table(table_name).put_item(Item=item)
    enqueued_jobs = _enqueue_minor_authorization_jobs(item, request_context)
    _log_json(
        "Stored Eventbrite submission in DynamoDB",
        {
            "table_name": table_name,
            "order_id": order_id,
            "event_id": order.get("event_id"),
            "attendee_count": len(attendees),
            "webhook_action": (webhook_payload.get("config") or {}).get("action"),
            "minor_authorization_jobs_enqueued": len(enqueued_jobs),
            "stored_item": item,
        },
    )
    return {
        "stored": True,
        "order_id": order_id,
        "attendee_count": len(attendees),
        "webhook_action": (webhook_payload.get("config") or {}).get("action"),
        "minor_authorization_jobs_enqueued": len(enqueued_jobs),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        webhook_payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        logger.exception("Eventbrite webhook body is not valid JSON.")
        return _json_response(400, {"ok": False, "detail": "Invalid JSON body."})

    try:
        result = _store_order_submission(webhook_payload, event.get("requestContext"))
    except Exception as exc:
        logger.exception("Failed to process Eventbrite order webhook.")
        return _json_response(500, {"ok": False, "detail": str(exc)})

    _log_json(
        "Received Eventbrite webhook",
        {
            "request_context": event.get("requestContext"),
            "parsed_body": webhook_payload,
            "result": result,
        },
    )

    return _json_response(200, {"ok": True, **result})
