import json
import logging
import os
import re
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import quote

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dynamodb_table():
    table_name = (os.getenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME") or "").strip()
    if not table_name:
        raise RuntimeError("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME is not configured.")
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _ses_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sesv2", region_name=region)


def _volunteer_intent_from_email() -> str:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError("VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL is not configured.")


def _volunteer_intent_allowed_admin_emails() -> set[str]:
    return {"wearecircleup@gmail.com", "hola@circleup.com.co"}


def _volunteer_intent_to_emails() -> list[str]:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL is not configured.")
    parsed = [email.strip().lower() for email in value.split(",") if email.strip()]
    if not parsed:
        raise RuntimeError("VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL must contain at least one email.")
    unauthorized = [email for email in parsed if email not in _volunteer_intent_allowed_admin_emails()]
    if unauthorized:
        raise RuntimeError(
            "VOLUNTEER_INTENT_NOTIFICATION_TO_EMAIL contains unauthorized recipients: "
            + ", ".join(unauthorized)
        )
    return parsed


def _volunteer_intent_reply_to_email() -> str:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_REPLY_TO_EMAIL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _volunteer_intent_from_email()


def _volunteer_intent_logo_url() -> str | None:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_LOGO_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _volunteer_intent_admin_subject_prefix() -> str:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_SUBJECT_PREFIX")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "Propuesta voluntario"


def _normalized_whatsapp_phone(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    digits = re.sub(r"\D+", "", value)
    return digits or None


def _format_date_long_es(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value).date()
    except ValueError:
        return value
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
    return f"{parsed.day} de {months[parsed.month]} de {parsed.year}"


def _build_volunteer_intent_whatsapp_url(item: dict[str, Any]) -> str | None:
    phone = _normalized_whatsapp_phone(item.get("contact_phone"))
    if not phone:
        return None
    contact_name = item.get("contact_name") or "hola"
    event_name = item.get("proposal_event_name") or "tu evento"
    requested_date = _format_date_long_es(item.get("proposal_requested_date")) or str(
        item.get("proposal_requested_date") or "la fecha tentativa"
    )
    message = (
        f"Hola {contact_name}, recibi tu propuesta sobre *{event_name}*, con fecha tentativa {requested_date}. "
        "Gracias por compartirla. Mi nombre es Napoleon, no soy un bot respondiendo automaticamente. "
        "Me gustaria saber si ya tienes un lugar pensado y un aforo. La idea es empezar con 3-4 personas y, "
        "si es posible, tener una llamada de 15 min o menos, para resolver dudas o explicar algunos detalles. "
        "No dudes en escribir a este numero cualquier duda; un mensaje de voz tambien esta perfecto."
    )
    return f"https://wa.me/{phone}?text={quote(message)}"


def _build_volunteer_intent_admin_email(item: dict[str, Any]) -> tuple[str, str, str]:
    event_name = item.get("proposal_event_name") or "Nueva propuesta"
    subject = f"{_volunteer_intent_admin_subject_prefix()}: {event_name}"
    support_url = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_SUPPORT_URL", "https://circleup.com.co")
    logo_url = _volunteer_intent_logo_url()
    whatsapp_url = _build_volunteer_intent_whatsapp_url(item)

    summary = (
        f"{item.get('contact_name') or 'Alguien'} compartio una nueva propuesta para Circle Up. "
        "Te dejamos aqui los datos clave para revisarla rapido."
    )

    field_rows = [
        ("PK", item.get("pk")),
        ("Email", item.get("contact_email") or item.get("registration_email")),
        ("Telefono", item.get("contact_phone")),
        ("Nombre del evento", item.get("proposal_event_name")),
        ("Tema", item.get("proposal_topic")),
        ("Fecha tentativa", item.get("proposal_requested_date")),
        ("Hora tentativa", item.get("proposal_requested_time")),
        ("Pregunta para Circle Up", item.get("proposal_admin_question")),
    ]
    field_rows = [(label, str(value)) for label, value in field_rows if value]

    text_lines = ["Hola,", "", summary, ""]
    for label, value in field_rows:
        text_lines.append(f"{label}: {value}")
    if whatsapp_url:
        text_lines.extend(["", f"WhatsApp: {whatsapp_url}"])
    text_lines.extend(["", "Circle Up Community", "circleup.com.co"])
    text_body = "\n".join(text_lines)

    html_rows = "".join(
        (
            "<tr>"
            f"<td style=\"padding: 0 0 8px; width: 220px; vertical-align: top; color: #7d95ad; font-size: 12px; line-height: 1.6;\">{escape(label)}</td>"
            f"<td style=\"padding: 0 0 8px; vertical-align: top; color: #153f69; font-size: 12px; line-height: 1.6;\">{escape(value)}</td>"
            "</tr>"
        )
        for label, value in field_rows
    )

    html_body = (
        "<html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"></head>"
        "<body style=\"margin: 0; padding: 0; background-color: #f7f7f4; font-family: Arial, Helvetica, sans-serif; color: #153f69;\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background-color: #f7f7f4; padding: 40px 20px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width: 760px; background-color: #ffffff;\">"
        "<tr><td style=\"padding: 32px 28px 28px;\">"
        "<div style=\"margin: 0 0 16px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        "<h1 style=\"margin: 0 0 18px; font-size: 30px; line-height: 1.1; font-weight: 500; color: #0f4978;\">Nueva propuesta de voluntariado</h1>"
        f"<p style=\"margin: 0 0 22px; font-size: 12px; line-height: 1.7; color: #5e7f9c;\">{escape(summary)}</p>"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin: 0 0 18px;\">"
        f"{html_rows}"
        "</table>"
    )
    if whatsapp_url:
        html_body += (
            "<p style=\"margin: 8px 0 24px;\">"
            f"<a href=\"{escape(whatsapp_url, quote=True)}\" "
            "style=\"display: inline-block; padding: 16px 28px; background-color: #4da3f5; color: #ffffff; text-decoration: none; border-radius: 0; font-size: 16px; font-weight: 700;\">"
            "Escribir por WhatsApp"
            "</a>"
            "</p>"
        )
    html_body += (
        "<div style=\"padding-top: 20px; border-top: 1px solid #d7e2ec;\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\"><tr>"
        "<td style=\"vertical-align: bottom; text-align: left;\">"
        "<div style=\"margin: 0 0 4px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        f"<div style=\"font-size: 12px; line-height: 18px; color: #0f4978;\"><a href=\"{escape(support_url, quote=True)}\" style=\"color: #0f4978; text-decoration: none;\">circleup.com.co</a></div>"
        "</td><td style=\"vertical-align: bottom; text-align: right;\">"
    )
    if logo_url:
        html_body += (
            f"<img src=\"{escape(logo_url, quote=True)}\" alt=\"Circle Up Community\" width=\"42\" style=\"display: inline-block; width: 42px; height: auto; border: 0; outline: none; text-decoration: none;\">"
        )
    html_body += "</td></tr></table></div></td></tr></table></td></tr></table></body></html>"
    return subject, text_body, html_body


def _existing_notification_status(item: dict[str, Any]) -> str | None:
    response = _dynamodb_table().get_item(Key={"pk": item["pk"], "sk": item["sk"]})
    stored_item = response.get("Item") or {}
    status = stored_item.get("admin_notification_status")
    return str(status) if status is not None else None


def _record_admin_notification_result(
    item: dict[str, Any],
    result: dict[str, Any],
    error_detail: str | None = None,
) -> None:
    expression_values: dict[str, Any] = {
        ":status": result["status"],
        ":message_id": result.get("message_id"),
        ":recipient": result.get("recipient"),
        ":error": error_detail,
    }
    update_expression = (
        "SET admin_notification_status = :status, "
        "admin_notification_message_id = :message_id, "
        "admin_notification_recipient = :recipient, "
        "admin_notification_error = :error"
    )
    if result.get("sent"):
        expression_values[":sent_at"] = _utc_now()
        update_expression += ", admin_notification_sent_at = :sent_at"
    _dynamodb_table().update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_values,
    )


def _send_notification(item: dict[str, Any]) -> dict[str, Any]:
    if _existing_notification_status(item) == "sent":
        return {"sent": False, "status": "already_sent", "message_id": None, "recipient": None}

    subject, text_body, html_body = _build_volunteer_intent_admin_email(item)
    recipients = _volunteer_intent_to_emails()
    response = _ses_client().send_email(
        FromEmailAddress=_volunteer_intent_from_email(),
        Destination={"ToAddresses": recipients},
        ReplyToAddresses=[_volunteer_intent_reply_to_email()],
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
        "recipient": ", ".join(recipients),
    }


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    item = event if isinstance(event, dict) else {}
    try:
        result = _send_notification(item)
        _record_admin_notification_result(item, result)
    except Exception as exc:
        logger.exception("Failed to send volunteer intent admin notification for submission %s.", item.get("submission_id"))
        failure = {"sent": False, "status": "failed", "message_id": None, "recipient": None}
        if item.get("pk") and item.get("sk"):
            _record_admin_notification_result(item, failure, str(exc))
        return _json_response(500, {"ok": False, "detail": str(exc)})

    logger.info(
        "Processed volunteer intent notification: %s",
        json.dumps(
            {
                "submission_id": item.get("submission_id"),
                "status": result.get("status"),
                "has_message_id": bool(result.get("message_id")),
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    return _json_response(200, result)
