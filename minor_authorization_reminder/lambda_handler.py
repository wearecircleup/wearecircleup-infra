import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import urlencode
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


def _event_summary_text(item: dict[str, Any]) -> str | None:
    event_name = item.get("event_name")
    event_date = item.get("event_date")
    event_time = item.get("event_time")
    event_timezone = item.get("event_timezone")
    venue_parts = [item.get("venue_name"), item.get("venue_city"), item.get("venue_region")]
    venue_parts = [str(part) for part in venue_parts if part]

    when_text = None
    if event_date:
        try:
            event_date_obj = datetime.fromisoformat(str(event_date)).date()
            months = {
                1: "enero",
                2: "febrero",
                3: "marzo",
                4: "abril",
                5: "mayo",
                6: "junio",
                7: "julio",
                8: "agosto",
                9: "septiembre",
                10: "octubre",
                11: "noviembre",
                12: "diciembre",
            }
            when_text = f"{event_date_obj.day} de {months[event_date_obj.month]} de {event_date_obj.year}"
        except ValueError:
            when_text = str(event_date)

    time_text = None
    if event_time:
        time_text = str(event_time)[:5]

    schedule_parts: list[str] = []
    if when_text:
        schedule_parts.append(when_text)
    if time_text:
        schedule_parts.append(f"a las {time_text}")
    if event_timezone:
        schedule_parts.append(f"({event_timezone})")

    schedule_text = " ".join(schedule_parts).strip()
    venue_text = ", ".join(venue_parts)

    if not any([event_name, schedule_text, venue_text]):
        return None

    summary = (
        "Te escribimos porque todavia nos falta un paso importante para el check-in si quieres participar siendo menor de edad: "
        "necesitas la autorizacion de tu representante legal"
    )
    if schedule_text:
        summary += f" para el {schedule_text}"
    if venue_text:
        summary += f" en {venue_text}"
    summary += "."
    if event_name:
        summary += f" Te estaremos esperando en {event_name}, tu participacion es importante."
    return summary


def _support_email() -> str:
    return os.getenv("REMINDER_SUPPORT_EMAIL", "hola@circleup.com.co")


def _support_url() -> str:
    return os.getenv("REMINDER_SUPPORT_URL", "https://circleup.com.co")


def _hero_image_url() -> str | None:
    value = os.getenv("REMINDER_HERO_IMAGE_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _slugify_event_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = ascii_only.lower()
    ascii_only = re.sub(r"[^a-z0-9]+", "-", ascii_only)
    return ascii_only.strip("-")


def _build_eventbrite_event_url(item: dict[str, Any]) -> str | None:
    existing_url = item.get("event_url")
    if isinstance(existing_url, str) and existing_url.strip():
        return existing_url.strip()

    event_id = item.get("event_id")
    event_name = item.get("event_name")
    if not event_id or not isinstance(event_name, str) or not event_name.strip():
        return None

    slug = _slugify_event_name(event_name)
    if not slug:
        return None
    return f"https://www.eventbrite.co/e/{slug}-tickets-{event_id}"


def _build_form_url(item: dict[str, Any]) -> str:
    base_url = os.getenv("MINOR_AUTHORIZATION_FORM_URL", "https://app.youform.com/forms/iamr7tnj")
    params: dict[str, str] = {}
    event_url = _build_eventbrite_event_url(item)
    if event_url:
        params["event_url"] = event_url
    if item.get("event_date"):
        params["event_date"] = str(item["event_date"])
    if not params:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(params)}"


def _build_email(item: dict[str, Any]) -> tuple[str, str, str]:
    form_url = _build_form_url(item)
    subject_prefix = os.getenv("REMINDER_EMAIL_SUBJECT_PREFIX", "Pendiente autorizacion para menor de edad")
    event_name = item.get("event_name") or item.get("event_id") or "tu evento"
    subject = f"{subject_prefix}: {event_name}"
    support_email = _support_email()
    support_url = _support_url()
    hero_image_url = _hero_image_url()
    details_colspan = "2" if hero_image_url else "1"

    detail_text = _event_summary_text(item)

    text_body = (
        "Hola,\n\n"
        f"{detail_text or 'Te escribimos porque todavia nos falta un paso importante para el check-in si quieres participar siendo menor de edad.'}"
    )
    if detail_text:
        text_body += "\n\n"
    else:
        text_body += "\n\n"
    text_body += (
        "Cuando quieras, puedes completar este formulario:\n"
        f"{form_url}\n\n"
    )
    text_body += (
        "Es un requisito para poder hacer check-in el dia del evento. Idealmente, dejalo listo al menos 3 horas antes de que empiece, "
        "antes de que el sistema saque la lista final de participantes.\n\n"
        "Si ya no vas a participar, puedes cancelar tu orden desde el correo de Eventbrite, en la seccion de tickets. "
        "Mientras la orden siga activa, este recordatorio puede volver a llegar diariamente.\n\n"
        "Si ya diligenciaste el formulario y aun recibes este mensaje, normalmente significa que el correo usado en Eventbrite "
        f"y el correo usado en el formulario no coinciden. En ese caso, escribenos a {support_email}.\n\n"
        f"Circle Up Community\ncircleup.com.co"
    )

    html_body = (
        "<html>"
        "<head>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        "<style>"
        "@media screen and (max-width: 720px) {"
        "  .reminder-shell { width: 100% !important; }"
        "  .stack-col { display: block !important; width: 100% !important; }"
        "  .content-col { padding: 32px 24px 24px !important; }"
        "  .details-col { padding: 24px !important; }"
        "  .hero-cell { padding: 0 !important; }"
        "  .hero-image { width: 100% !important; max-width: 100% !important; height: auto !important; }"
        "  .title-text { font-size: 34px !important; line-height: 1.1 !important; }"
        "  .body-text { font-size: 15px !important; line-height: 1.7 !important; max-width: 100% !important; word-break: break-word !important; overflow-wrap: anywhere !important; }"
        "}"
        "</style>"
        "</head>"
        "<body style=\"margin: 0; padding: 0; background-color: #f7f7f4; font-family: Arial, Helvetica, sans-serif; color: #153f69;\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background-color: #f7f7f4; padding: 40px 20px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" class=\"reminder-shell\" style=\"max-width: 980px; background-color: #ffffff;\">"
        "<tr>"
    )
    html_body += (
        "<td class=\"stack-col content-col\" style=\"width: 58%; vertical-align: top; padding: 40px 40px 36px;\">"
        "<div style=\"margin: 0 0 16px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        "<h1 class=\"title-text\" style=\"margin: 0 0 18px; font-size: 42px; line-height: 1.06; font-weight: 500; color: #0f4978;\">Tu autorizacion sigue pendiente</h1>"
        f"<p class=\"body-text\" style=\"margin: 0 0 26px; font-size: 14px; line-height: 1.72; color: #5e7f9c; max-width: 620px; word-break: break-word; overflow-wrap: anywhere;\">{escape(detail_text or 'Te escribimos porque todavia nos falta un paso importante para el check-in si quieres participar siendo menor de edad.')}</p>"
    )
    html_body += (
        "<p class=\"body-text\" style=\"margin: 0 0 26px; font-size: 14px; line-height: 1.72; color: #5e7f9c; max-width: 620px; word-break: break-word; overflow-wrap: anywhere;\">"
        "Cuando quieras, puedes completar el formulario en este enlace."
        "</p>"
        "<p style=\"margin: 0 0 30px;\">"
        f'<a href="{escape(form_url, quote=True)}" '
        'style="display: inline-block; padding: 16px 28px; background-color: #4da3f5; color: #ffffff; text-decoration: none; border-radius: 0; font-size: 16px; font-weight: 700;">'
        "Completar formulario"
        "</a>"
        "</p>"
        "</td>"
    )
    if hero_image_url:
        html_body += (
            f'<td class="stack-col hero-cell" style="width: 42%; vertical-align: top; padding: 0;"><img class="hero-image" src="{escape(hero_image_url, quote=True)}" alt="Circle Up Community" width="412" style="display: block; width: 100%; max-width: 412px; height: auto; border: 0; outline: none; text-decoration: none;"></td>'
        )
    html_body += (
        "</tr>"
        "<tr>"
        f"<td class=\"details-col\" colspan=\"{details_colspan}\" style=\"padding: 0 40px 40px;\">"
        "<div style=\"margin: 4px 0 0; font-size: 12px; line-height: 1.7; color: #88a0b6; max-width: 100%;\">"
        "<p style=\"margin: 0 0 10px; font-size: 12px; line-height: 1.7; color: #88a0b6;\">"
        "Este formulario es un requisito para poder hacer check-in el dia del evento. Si quieres, puedes completarlo con calma, "
        "pero idealmente al menos 3 horas antes de que empiece, antes de que el sistema saque la lista final de participantes."
        "</p>"
        "<p style=\"margin: 0 0 10px; font-size: 12px; line-height: 1.7; color: #88a0b6;\">"
        "Si ya no vas a participar, puedes cancelar tu orden desde el correo de Eventbrite, en la seccion de tickets. "
        "Mientras la orden siga activa, este recordatorio puede volver a llegar diariamente."
        "</p>"
        "<p style=\"margin: 0 0 18px; font-size: 12px; line-height: 1.7; color: #88a0b6;\">"
        "Si ya diligenciaste el formulario y aun recibes este mensaje, normalmente significa que el correo usado en Eventbrite "
        f'y el correo usado en el formulario no coinciden. En ese caso, escribenos a <a href="mailto:{escape(support_email, quote=True)}" style="color: #0f4978; text-decoration: none;">{escape(support_email)}</a>.'
        "</p>"
        "</div>"
        "<div style=\"padding-top: 20px; border-top: 1px solid #d7e2ec;\">"
        "<div style=\"margin: 0 0 4px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        '<div style="font-size: 12px; line-height: 18px; color: #0f4978;">circleup.com.co</div>'
        "</div>"
        "</td>"
        "</tr>"
        "</table></td></tr></table></body></html>"
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
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
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
    expression_attribute_names: dict[str, str] | None = None
    expression_values: dict[str, Any] = {
        ":last_reminder_at": now,
        ":last_reminder_status": result["status"],
        ":one": 1,
        ":zero": 0,
        ":last_reminder_message_id": result.get("message_id"),
        ":last_reminder_error": error_detail,
    }
    update_expression = (
        "SET last_reminder_at = :last_reminder_at, "
        "last_reminder_status = :last_reminder_status, "
        "last_reminder_message_id = :last_reminder_message_id, "
        "last_reminder_error = :last_reminder_error, "
        "reminder_count = if_not_exists(reminder_count, :zero) + :one"
    )
    if result.get("sent") and result.get("recipient"):
        expression_values[":empty_list"] = []
        expression_values[":reminder_history_entry"] = [
            {
                "email": result["recipient"],
                "sent_at": now,
            }
        ]
        update_expression += (
            ", reminder_history = list_append(if_not_exists(reminder_history, :empty_list), :reminder_history_entry)"
        )
    if refreshed_order_status is not None:
        expression_values[":order_status"] = refreshed_order_status
        update_expression += ", order_status = :order_status"
    if status_override is not None:
        expression_attribute_names = {"#status": "status"}
        expression_values[":status_override"] = status_override
        expression_values[":gsi1pk"] = f"STATUS#{status_override}"
        expression_values[":gsi1sk"] = (
            f"UPDATED_AT#{now}#EVENT#{item.get('event_id') or 'UNKNOWN_EVENT'}#ATTENDEE#{item.get('attendee_id') or 'UNKNOWN_ATTENDEE'}"
        )
        update_expression += ", #status = :status_override, gsi1pk = :gsi1pk, gsi1sk = :gsi1sk"
    if validation_result_override is not None:
        expression_values[":validation_result_override"] = validation_result_override
        update_expression += ", validation_result = :validation_result_override"
    update_kwargs = {
        "Key": {"pk": item["pk"], "sk": item["sk"]},
        "UpdateExpression": update_expression,
        "ExpressionAttributeValues": expression_values,
    }
    if expression_attribute_names is not None:
        update_kwargs["ExpressionAttributeNames"] = expression_attribute_names
    _jobs_table().update_item(**update_kwargs)


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
