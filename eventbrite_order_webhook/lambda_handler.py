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


def _extract_attendee_target(api_url: str) -> tuple[str, str] | None:
    parsed = urlparse(api_url)
    if parsed.netloc not in {"www.eventbriteapi.com", "eventbriteapi.com"}:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 5 or segments[0] != "v3" or segments[1] != "events" or segments[3] != "attendees":
        return None
    return segments[2], segments[4]


def _answer_value(answer: dict[str, Any]) -> Any:
    if "answer" in answer:
        return answer.get("answer")
    if "answer_text" in answer:
        return answer.get("answer_text")
    return answer.get("value")


def _question_text(question: Any) -> str | None:
    if isinstance(question, str):
        text = question.strip()
        return text or None
    if isinstance(question, dict):
        for key in ("html", "text", "label"):
            value = question.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _stringify_answer_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [item for item in (_stringify_answer_value(item) for item in value) if item]
        return ", ".join(parts) or None
    if isinstance(value, dict):
        for key in ("html", "text", "name", "email", "value"):
            candidate = _stringify_answer_value(value.get(key))
            if candidate:
                return candidate
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _normalize_custom_answers(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for answer in answers:
        question = _question_text(answer.get("question"))
        value = _stringify_answer_value(_answer_value(answer))
        if not question or not value:
            continue
        key = (question, value)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"question": question, "answer": value})
    return normalized


def _normalize_attendee(attendee: dict[str, Any]) -> dict[str, Any]:
    profile = attendee.get("profile") or {}
    return {
        "attendee_id": attendee.get("id"),
        "ticket_class_name": attendee.get("ticket_class_name"),
        "email": profile.get("email"),
        "answers": _normalize_custom_answers(attendee.get("answers") or []),
    }


def _summarize_attendee(attendee: dict[str, Any]) -> dict[str, Any]:
    profile = attendee.get("profile") or {}
    answers = attendee.get("answers") or []
    return {
        "id": attendee.get("id"),
        "event_id": attendee.get("event_id"),
        "order_id": attendee.get("order_id"),
        "status": attendee.get("status"),
        "ticket_class_name": attendee.get("ticket_class_name"),
        "email": profile.get("email"),
        "answers_count": len(answers),
        "answers": [
            {
                "question": _question_text(answer.get("question")),
                "value": _stringify_answer_value(_answer_value(answer)),
            }
            for answer in answers
        ],
    }


def _summarize_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": question.get("id"),
        "type": question.get("type"),
        "required": question.get("required"),
        "respondent": question.get("respondent"),
        "question": _question_text(question.get("question")),
    }


def _fetch_all_order_attendees(order_id: str, token: str) -> list[dict[str, Any]]:
    base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
    attendees: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _request_json(f"{base_url}/orders/{order_id}/attendees/?page={page}", token)
        page_attendees = response.get("attendees", [])
        attendees.extend(page_attendees)
        _log_json(
            "Eventbrite order attendees page fetched",
            {
                "order_id": order_id,
                "page": page,
                "attendees_count": len(page_attendees),
                "attendees": [_summarize_attendee(attendee) for attendee in page_attendees],
            },
        )
        if not (response.get("pagination") or {}).get("has_more_items"):
            return attendees
        page += 1


def _fetch_attendee_detail(event_id: str, attendee_id: str, token: str) -> dict[str, Any]:
    base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
    attendee = _request_json(f"{base_url}/events/{event_id}/attendees/{attendee_id}/", token)
    _log_json(
        "Eventbrite attendee detail fetched",
        {
            "event_id": event_id,
            "attendee_id": attendee_id,
            "attendee": _summarize_attendee(attendee),
        },
    )
    return attendee


def _fetch_event_questions(event_id: str, token: str) -> list[dict[str, Any]]:
    base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
    response = _request_json(f"{base_url}/events/{event_id}/questions/", token)
    questions = response.get("questions", [])
    _log_json(
        "Eventbrite event questions fetched",
        {
            "event_id": event_id,
            "questions_count": len(questions),
            "questions": [_summarize_question(question) for question in questions],
        },
    )
    return questions


def _fetch_detailed_attendees(order_id: str, event_id: str | None, token: str) -> list[dict[str, Any]]:
    attendees = _fetch_all_order_attendees(order_id, token)
    detailed_attendees: list[dict[str, Any]] = []
    for attendee in attendees:
        attendee_id = attendee.get("id")
        attendee_event_id = attendee.get("event_id") or event_id
        if not attendee_id or not attendee_event_id:
            detailed_attendees.append(attendee)
            continue
        try:
            attendee_detail = _fetch_attendee_detail(str(attendee_event_id), str(attendee_id), token)
        except RuntimeError:
            logger.warning(
                "Falling back to order attendee payload for attendee %s on event %s.",
                attendee_id,
                attendee_event_id,
            )
            detailed_attendees.append(attendee)
            continue
        merged_attendee = dict(attendee)
        merged_attendee.update(attendee_detail)
        detailed_attendees.append(merged_attendee)
    _log_json(
        "Eventbrite detailed attendees ready",
        {
            "order_id": order_id,
            "event_id": event_id,
            "attendees_count": len(detailed_attendees),
            "attendees": [_summarize_attendee(attendee) for attendee in detailed_attendees],
        },
    )
    return detailed_attendees


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


def _resolve_order_context(api_url: str, token: str) -> tuple[dict[str, Any], str]:
    order_id = _extract_order_id(api_url)
    if order_id:
        order = _request_json(api_url, token)
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
        return order, str(order["id"])

    attendee_target = _extract_attendee_target(api_url)
    if attendee_target:
        event_id, attendee_id = attendee_target
        attendee = _fetch_attendee_detail(event_id, attendee_id, token)
        derived_order_id = attendee.get("order_id")
        if not derived_order_id:
            raise RuntimeError("Eventbrite attendee payload did not include order_id.")
        base_url = os.getenv("EVENTBRITE_API_BASE_URL", "https://www.eventbriteapi.com/v3").rstrip("/")
        order = _request_json(f"{base_url}/orders/{derived_order_id}/", token)
        _log_json(
            "Eventbrite order fetched from attendee webhook",
            {
                "api_url": api_url,
                "event_id": event_id,
                "attendee_id": attendee_id,
                "order_id": order.get("id"),
                "status": order.get("status"),
                "email": order.get("email"),
                "changed": order.get("changed"),
            },
        )
        return order, str(order["id"])

    raise RuntimeError(f"unsupported_api_url: {api_url}")


def _store_order_submission(webhook_payload: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
    api_url = webhook_payload.get("api_url")
    if not api_url:
        logger.info("Skipping Eventbrite webhook persistence because api_url is missing.")
        return {"stored": False, "reason": "missing_api_url"}

    table_name = os.getenv("SUBMISSIONS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("SUBMISSIONS_TABLE_NAME is not configured.")

    token = _eventbrite_private_token()
    order, order_id = _resolve_order_context(str(api_url), token)
    event_id = order.get("event_id")
    if event_id:
        try:
            _fetch_event_questions(str(event_id), token)
        except RuntimeError:
            logger.warning("Failed to fetch Eventbrite event questions for event %s.", event_id)
    attendees = _fetch_detailed_attendees(order_id, event_id, token)
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
            "event_id": event_id,
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

    _log_json(
        "Received Eventbrite webhook",
        {
            "request_context": event.get("requestContext"),
            "headers": event.get("headers"),
            "query_string_parameters": event.get("queryStringParameters"),
            "parsed_body": webhook_payload,
            "result": result,
        },
    )

    return _json_response(200, {"ok": True, **result})
