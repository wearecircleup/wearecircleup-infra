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


def _log_json(message: str, payload: dict[str, Any]) -> None:
    logger.info("%s: %s", message, json.dumps(payload, ensure_ascii=False, default=str))


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


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
    return {
        "attendee_id": attendee.get("id"),
        "ticket_class_name": attendee.get("ticket_class_name"),
        "email": profile.get("email"),
        "answers": [],
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


def _build_submission_item(
    webhook_payload: dict[str, Any],
    order: dict[str, Any],
    attendees: list[dict[str, Any]],
    received_at: str,
) -> dict[str, Any]:
    order_id = str(order["id"])
    return {
        "pk": f"ORDER#{order_id}",
        "sk": f"ORDER#{order_id}",
        "order_id": order_id,
        "event_id": order.get("event_id"),
        "order_status": order.get("status"),
        "order_created": order.get("created"),
        "order_changed": order.get("changed"),
        "buyer": {
            "name": order.get("name"),
            "email": order.get("email"),
        },
        "attendees": [_normalize_attendee(attendee) for attendee in attendees],
        "webhook": {
            "api_url": webhook_payload.get("api_url"),
            "received_at": received_at,
            "action": ((webhook_payload.get("config") or {}).get("action")),
        },
    }


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
    attendees = _fetch_all_order_attendees(order_id, token)
    received_at = (
        (request_context or {}).get("time")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    item = _build_submission_item(webhook_payload, order, attendees, received_at)
    _dynamodb_table(table_name).put_item(Item=item)
    _log_json(
        "Stored Eventbrite submission in DynamoDB",
        {
            "table_name": table_name,
            "order_id": order_id,
            "event_id": order.get("event_id"),
            "attendee_count": len(attendees),
            "webhook_action": (webhook_payload.get("config") or {}).get("action"),
            "stored_item": item,
        },
    )
    return {
        "stored": True,
        "order_id": order_id,
        "attendee_count": len(attendees),
        "webhook_action": (webhook_payload.get("config") or {}).get("action"),
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
