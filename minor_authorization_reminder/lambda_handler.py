import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _jobs_table():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    table_name = os.getenv("AUTHORIZATION_JOBS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("AUTHORIZATION_JOBS_TABLE_NAME is not configured.")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _ses_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sesv2", region_name=region)


def _order_submissions_table():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    table_name = os.getenv("EVENTBRITE_ORDER_SUBMISSIONS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("EVENTBRITE_ORDER_SUBMISSIONS_TABLE_NAME is not configured.")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _query_missing_form_jobs() -> list[dict[str, Any]]:
    table = _jobs_table()
    items: list[dict[str, Any]] = []
    last_evaluated_key = None

    while True:
        query_args = {
            "IndexName": "gsi1",
            "KeyConditionExpression": Key("gsi1pk").eq("STATUS#missing_form"),
        }
        if last_evaluated_key:
            query_args["ExclusiveStartKey"] = last_evaluated_key

        response = table.query(**query_args)
        items.extend(response.get("Items") or [])
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            return items


def _recipient_email(item: dict[str, Any]) -> str | None:
    for key in ("buyer_email", "attendee_email"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _event_has_passed(item: dict[str, Any]) -> bool:
    event_date = item.get("event_date")
    if not event_date:
        return False

    event_time = item.get("event_time") or "00:00:00"
    event_timezone = item.get("event_timezone") or "UTC"
    try:
        event_dt = datetime.fromisoformat(f"{event_date}T{event_time}").replace(
            tzinfo=ZoneInfo(str(event_timezone))
        )
    except Exception:
        logger.warning(
            "Could not parse event datetime for reminder job %s / %s",
            item.get("pk"),
            item.get("sk"),
        )
        return False
    return datetime.now(ZoneInfo(str(event_timezone))) >= event_dt


def _refresh_order_details(item: dict[str, Any]) -> dict[str, Any]:
    order_id = item.get("order_id")
    if not order_id:
        return {}
    response = _order_submissions_table().get_item(
        Key={
            "pk": f"ORDER#{order_id}",
            "sk": f"ORDER#{order_id}",
        }
    )
    return response.get("Item") or {}


def _event_details_lines(item: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if item.get("event_name"):
        lines.append(f"Evento: {item['event_name']}")
    if item.get("event_date"):
        schedule = str(item["event_date"])
        if item.get("event_time"):
            schedule = f"{schedule} {item['event_time']}"
        if item.get("event_timezone"):
            schedule = f"{schedule} ({item['event_timezone']})"
        lines.append(f"Fecha y hora: {schedule}")
    venue_parts = [item.get("venue_name"), item.get("venue_city"), item.get("venue_region")]
    venue_parts = [str(part) for part in venue_parts if part]
    if venue_parts:
        lines.append(f"Lugar: {', '.join(venue_parts)}")
    return lines


def _build_email(item: dict[str, Any]) -> tuple[str, str, str]:
    form_url = os.getenv("MINOR_AUTHORIZATION_FORM_URL", "https://app.youform.com/forms/iamr7tnj")
    subject_prefix = os.getenv("REMINDER_EMAIL_SUBJECT_PREFIX", "Pendiente autorización para menor de edad")
    event_name = item.get("event_name") or item.get("event_id") or "tu evento"
    subject = f"{subject_prefix}: {event_name}"

    details = _event_details_lines(item)
    detail_text = "\n".join(details)
    detail_html = "".join(f"<li>{line}</li>" for line in details)

    text_body = (
        "Hola,\n\n"
        "Vemos que la autorización para menor de edad sigue pendiente. Para mantener la inscripción activa, "
        f"por favor diligencia el formulario cuanto antes:\n{form_url}\n\n"
    )
    if detail_text:
        text_body += f"{detail_text}\n\n"
    text_body += (
        "Si el formulario no se completa a tiempo, la inscripción podría verse afectada.\n\n"
        "Gracias,\nCircle Up Community"
    )

    html_body = (
        "<html><body>"
        "<p>Hola,</p>"
        "<p>Vemos que la autorización para menor de edad sigue pendiente. "
        "Para mantener la inscripción activa, por favor diligencia el formulario cuanto antes:</p>"
        f'<p><a href="{form_url}">{form_url}</a></p>'
    )
    if detail_html:
        html_body += f"<ul>{detail_html}</ul>"
    html_body += (
        "<p>Si el formulario no se completa a tiempo, la inscripción podría verse afectada.</p>"
        "<p>Gracias,<br>Circle Up Community</p>"
        "</body></html>"
    )

    return subject, text_body, html_body


def _send_reminder(item: dict[str, Any]) -> dict[str, Any]:
    recipient = _recipient_email(item)
    if not recipient:
        return {"sent": False, "status": "skipped_missing_email", "message_id": None}

    from_email = os.getenv("REMINDER_FROM_EMAIL")
    if not from_email:
        raise RuntimeError("REMINDER_FROM_EMAIL is not configured.")

    reply_to_email = os.getenv("REMINDER_REPLY_TO_EMAIL") or from_email
    subject, text_body, html_body = _build_email(item)
    response = _ses_client().send_email(
        FromEmailAddress=from_email,
        Destination={"ToAddresses": [recipient]},
        ReplyToAddresses=[reply_to_email],
        Content={
            "Simple": {
                "Subject": {"Data": subject},
                "Body": {
                    "Text": {"Data": text_body},
                    "Html": {"Data": html_body},
                },
            }
        },
    )
    return {
        "sent": True,
        "status": "sent",
        "message_id": response.get("MessageId"),
        "recipient": recipient,
    }


def _mark_reminder_result(
    item: dict[str, Any],
    result: dict[str, Any],
    error_detail: str | None = None,
    status_override: str | None = None,
    validation_result_override: str | None = None,
    refreshed_order_status: str | None = None,
) -> None:
    now = _utc_now()
    expression_values: dict[str, Any] = {
        ":last_reminder_at": now,
        ":last_reminder_status": result["status"],
        ":one": 1,
        ":zero": 0,
        ":last_reminder_message_id": result.get("message_id"),
        ":last_reminder_error": error_detail,
        ":order_status": refreshed_order_status,
        ":status_override": status_override,
        ":validation_result_override": validation_result_override,
    }
    update_expression = (
        "SET last_reminder_at = :last_reminder_at, "
        "last_reminder_status = :last_reminder_status, "
        "last_reminder_message_id = :last_reminder_message_id, "
        "last_reminder_error = :last_reminder_error, "
        "reminder_count = if_not_exists(reminder_count, :zero) + :one"
    )
    if refreshed_order_status is not None:
        update_expression += ", order_status = :order_status"
    if status_override is not None:
        expression_values[":gsi1pk"] = f"STATUS#{status_override}"
        expression_values[":gsi1sk"] = (
            f"UPDATED_AT#{now}#EVENT#{item.get('event_id') or 'UNKNOWN_EVENT'}#ATTENDEE#{item.get('attendee_id') or 'UNKNOWN_ATTENDEE'}"
        )
        update_expression += ", #status = :status_override, gsi1pk = :gsi1pk, gsi1sk = :gsi1sk"
    if validation_result_override is not None:
        update_expression += ", validation_result = :validation_result_override"
    _jobs_table().update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression=update_expression,
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=expression_values,
    )


def handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    jobs = _query_missing_form_jobs()
    processed: list[dict[str, Any]] = []

    for item in jobs:
        try:
            latest_order = _refresh_order_details(item)
            latest_order_status = latest_order.get("order_status") or item.get("order_status")
            if latest_order_status != "placed":
                skip_result = {"status": "skipped_order_not_placed", "message_id": None}
                _mark_reminder_result(
                    item,
                    skip_result,
                    status_override="closed_order",
                    validation_result_override="order_not_placed",
                    refreshed_order_status=latest_order_status,
                )
                processed.append(
                    {
                        "pk": item["pk"],
                        "sk": item["sk"],
                        "status": "skipped_order_not_placed",
                        "order_status": latest_order_status,
                    }
                )
                continue

            if _event_has_passed(item):
                skip_result = {"status": "skipped_event_passed", "message_id": None}
                _mark_reminder_result(
                    item,
                    skip_result,
                    status_override="event_passed",
                    validation_result_override="event_passed",
                    refreshed_order_status=latest_order_status,
                )
                processed.append(
                    {
                        "pk": item["pk"],
                        "sk": item["sk"],
                        "status": "skipped_event_passed",
                        "order_status": latest_order_status,
                    }
                )
                continue

            send_result = _send_reminder(item)
            _mark_reminder_result(item, send_result, refreshed_order_status=latest_order_status)
            processed.append(
                {
                    "pk": item["pk"],
                    "sk": item["sk"],
                    "status": send_result["status"],
                    "recipient": send_result.get("recipient"),
                    "message_id": send_result.get("message_id"),
                    "order_status": latest_order_status,
                }
            )
        except Exception as exc:
            logger.exception("Failed to send reminder for %s / %s", item.get("pk"), item.get("sk"))
            _mark_reminder_result(item, {"status": "failed", "message_id": None}, str(exc))
            processed.append(
                {
                    "pk": item["pk"],
                    "sk": item["sk"],
                    "status": "failed",
                    "error": str(exc),
                }
            )

    summary = {
        "ok": True,
        "jobs_found": len(jobs),
        "processed_count": len(processed),
        "processed": processed,
    }
    logger.info("Processed minor authorization reminders: %s", json.dumps(summary, ensure_ascii=False, default=str))
    return summary
