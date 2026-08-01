import base64
import json
import logging
from typing import Any


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _decoded_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body).decode("utf-8")
        except Exception:
            logger.exception("Failed to decode base64 webhook body.")
            return body
    return body


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    raw_body = _decoded_body(event)
    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_body = None

    logger.info(
        "Received YouForm webhook: %s",
        json.dumps(
            {
                "request_context": event.get("requestContext"),
                "headers": event.get("headers"),
                "query_string_parameters": event.get("queryStringParameters"),
                "raw_body": raw_body,
                "parsed_body": parsed_body,
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
                "message": "YouForm webhook received and logged.",
            }
        ),
    }
