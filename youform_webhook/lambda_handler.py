import base64
import json
import logging
import mimetypes
import os
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

SIGNATURE_QUESTION = "Firma para autorizar"


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


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
    request = Request(signature_url, headers={"Accept": "*/*"}, method="GET")
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
            normalized_answer = _store_signature(parsed_body, answer.strip())
        normalized.append({"question": str(question), "answer": normalized_answer})
    return normalized


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
                "raw_body": raw_body,
                "parsed_body": parsed_body,
                "stored": stored,
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
