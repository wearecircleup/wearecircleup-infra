import base64
import json
import logging
import os
from typing import Any

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _decoded_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body).decode("utf-8")
        except Exception:
            logger.exception("Failed to decode base64 webhook body.")
            return body
    return body


def _normalize_answers(parsed_body: dict[str, Any]) -> list[dict[str, Any]]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return []
    return [{"question": str(question), "answer": answer} for question, answer in answers.items()]


def _build_submission_item(parsed_body: dict[str, Any]) -> dict[str, Any] | None:
    submission_id = parsed_body.get("submission_id")
    if not submission_id:
        return None
    return {
        "pk": f"SUBMISSION#{submission_id}",
        "sk": f"SUBMISSION#{submission_id}",
        "submission_id": submission_id,
        "form_id": parsed_body.get("form_id"),
        "form_name": parsed_body.get("form_name"),
        "event_id": parsed_body.get("event_id"),
        "event_type": parsed_body.get("event_type"),
        "started_at": parsed_body.get("started_at"),
        "completed_at": parsed_body.get("completed_at"),
        "answers": _normalize_answers(parsed_body),
    }


def _store_submission(parsed_body: dict[str, Any]) -> bool:
    table_name = os.getenv("SUBMISSIONS_TABLE_NAME")
    if not table_name:
        logger.warning("SUBMISSIONS_TABLE_NAME is not configured; skipping persistence.")
        return False
    item = _build_submission_item(parsed_body)
    if item is None:
        logger.info("Skipping persistence because submission_id is missing.")
        return False
    _dynamodb_table(table_name).put_item(Item=item)
    logger.info("Stored YouForm submission %s in DynamoDB table %s.", item["submission_id"], table_name)
    return True


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    raw_body = _decoded_body(event)
    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_body = None

    stored = False
    if isinstance(parsed_body, dict):
        stored = _store_submission(parsed_body)

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
                "message": "YouForm webhook received.",
                "stored": stored,
            }
        ),
    }
