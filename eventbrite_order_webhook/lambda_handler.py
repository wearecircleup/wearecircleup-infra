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


def _answer_value(answer: dict[str, Any]) -> Any:
    if "answer" in answer:
        return answer.get("answer")
    if "answer_text" in answer:
        return answer.get("answer_text")
    return answer.get("value")


def _normalize_profile_answers(profile: dict[str, Any]) -> list[dict[str, Any]]:
    profile_fields = [
        ("Nombre completo", profile.get("name")),
        ("Nombre", profile.get("first_name")),
        ("Apellido", profile.get("last_name")),
        ("Correo", profile.get("email")),
    ]
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for question, answer in profile_fields:
        if answer in (None, ""):
            continue
        key = (question, answer)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"question": question, "answer": answer, "source": "profile"})
    return normalized


def _normalize_custom_answers(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for answer in answers:
        question = answer.get("question")
        value = _answer_value(answer)
        if not question or value in (None, ""):
            continue
        normalized.append({"question": str(question), "answer": value, "source": "custom"})
    return normalized


def _normalize_attendee(attendee: dict[str, Any]) -> dict[str, Any]:
    profile = attendee.get("profile") or {}
    custom_answers = attendee.get("answers") or []
    return {
        "attendee_id": attendee.get("id"),
        "event_id": attendee.get("event_id"),
        "order_id": attendee.get("order_id"),
        "ticket_class_id": attendee.get("ticket_class_id"),
        "ticket_class_name": attendee.get("ticket_class_name"),
        "checked_in": attendee.get("checked_in", False),
        "cancelled": attendee.get("cancelled", False),
        "refunded": attendee.get("refunded", False),
        "status": attendee.get("status"),
        "profile": {
            "name": profile.get("name"),
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "email": profile.get("email"),
        },
        "answers": _normalize_profile_answers(profile) + _normalize_custom_answers(custom_answers),
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
        "purchaser_name": order.get("name"),
        "purchaser_first_name": order.get("first_name"),
        "purchaser_last_name": order.get("last_name"),
        "purchaser_email": order.get("email"),
        "webhook_object": "order",
        "webhook_action": "place",
        "webhook_api_url": webhook_payload.get("api_url"),
        "webhook_received_at": received_at,
        "attendee_count": len(attendees),
        "attendees": [_normalize_attendee(attendee) for attendee in attendees],
        "raw_webhook": webhook_payload,
    }


def _store_order_submission(webhook_payload: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
    api_url = webhook_payload.get("api_url")
    if not api_url:
        logger.info("Skipping Eventbrite webhook persistence because api_url is missing.")
        return {"stored": False, "reason": "missing_api_url"}

    order_id = _extract_order_id(str(api_url))
    if not order_id:
        logger.info("Skipping Eventbrite webhook persistence because api_url is not an order URL: %s", api_url)
        return {"stored": False, "reason": "unsupported_api_url"}

    table_name = os.getenv("SUBMISSIONS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("SUBMISSIONS_TABLE_NAME is not configured.")

    token = _eventbrite_private_token()
    order = _request_json(str(api_url), token)
    attendees = _fetch_all_order_attendees(order_id, token)
    received_at = (
        (request_context or {}).get("time")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    item = _build_submission_item(webhook_payload, order, attendees, received_at)
    _dynamodb_table(table_name).put_item(Item=item)
    logger.info("Stored Eventbrite order %s in DynamoDB table %s.", order_id, table_name)
    return {"stored": True, "order_id": order_id, "attendee_count": len(attendees)}


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

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

    logger.info(
        "Received Eventbrite order webhook: %s",
        json.dumps(
            {
                "request_context": event.get("requestContext"),
                "headers": event.get("headers"),
                "query_string_parameters": event.get("queryStringParameters"),
                "parsed_body": webhook_payload,
                "result": result,
            },
            ensure_ascii=False,
            default=str,
        ),
    )

    return _json_response(200, {"ok": True, **result})
