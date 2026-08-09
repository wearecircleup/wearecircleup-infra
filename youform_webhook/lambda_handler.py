import base64
import json
import logging
import mimetypes
import os
import re
import unicodedata
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}

SIGNATURE_QUESTION = "Firma para autorizar"
EVENT_URL_QUESTION = "¿A qué evento asiste?"
EVENT_DATE_QUESTION = "¿Qué día es el evento?"
REGISTRATION_EMAIL_QUESTION = "¿Con qué correo vas a realizar la inscripción?"
CONTACT_NAME_QUESTION = "Nombre"
CONTACT_EMAIL_QUESTION = "Correo"
CONTACT_PHONE_QUESTION = "Teléfono"
VOLUNTEER_INTENT_EVENT_NAME_QUESTION = "¿Cómo se llama tu evento?"
VOLUNTEER_INTENT_PRESENTATION_QUESTION = "¿Cómo te presentarías?"
VOLUNTEER_INTENT_TOPIC_QUESTION = "¿De qué se tratará tu evento?"
VOLUNTEER_INTENT_REQUESTED_DATE_QUESTION = "¿Qué día te gustaría que fuera el evento?"
VOLUNTEER_INTENT_REQUESTED_TIME_QUESTION = "¿A qué hora?"
VOLUNTEER_INTENT_ADMIN_QUESTION = "¿Tienes alguna pregunta para nosotros?"
UNKNOWN_EVENT_ID = "UNKNOWN_EVENT"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if not any(marker in value for marker in ("Ãƒ", "Ã‚", "Ã¢", "Ã")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _normalized_question_key(value: str) -> str:
    cleaned = _clean_text(value)
    return " ".join(str(cleaned).strip().lower().split())


def _ascii_normalized(value: str) -> str:
    cleaned = str(_clean_text(value) or "").strip().lower()
    return unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _ses_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sesv2", region_name=region)


def _sqs_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("sqs", region_name=region)


def _load_secret(secret_id: str) -> dict[str, str]:
    cached = _SECRET_CACHE.get(secret_id)
    if cached is not None:
        return cached
    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    payload = response.get("SecretString")
    if not payload:
        raise RuntimeError(f"Secret {secret_id} does not contain SecretString.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"Secret {secret_id} must contain a JSON object.")
    secret = {str(key): str(value) for key, value in data.items() if value is not None}
    _SECRET_CACHE[secret_id] = secret
    return secret


def _authorized_minor_form_id() -> str:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret = _load_secret(secret_id)
        value = (secret.get("AUTHORIZED_MINOR_FORM_ID") or "").strip()
        if value:
            return value
        raise RuntimeError(f"AUTHORIZED_MINOR_FORM_ID is missing in secret {secret_id}.")
    value = (os.getenv("AUTHORIZED_MINOR_FORM_ID") or "").strip()
    if value:
        return value
    raise RuntimeError("AUTHORIZED_MINOR_FORM_ID is not configured.")


def _configured_form_id(secret: dict[str, str], secret_key: str, env_key: str) -> str:
    value = (secret.get(secret_key) or "").strip()
    if value:
        return value
    return (os.getenv(env_key) or "").strip()


def _configured_form_routes() -> dict[str, dict[str, Any]]:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    secret = _load_secret(secret_id) if secret_id else {}
    routes: dict[str, dict[str, Any]] = {}

    minor_form_id = _configured_form_id(secret, "AUTHORIZED_MINOR_FORM_ID", "AUTHORIZED_MINOR_FORM_ID")
    if minor_form_id:
        routes[minor_form_id] = {
            "table_name": os.getenv("MINOR_AUTHORIZATION_SUBMISSIONS_TABLE_NAME"),
            "bucket_name": os.getenv("MINOR_AUTHORIZATION_FILES_BUCKET_NAME"),
            "storage_prefix": "youform-signatures",
            "reconcile_minor_authorization": True,
            "preserve_signature_key": True,
            "key_strategy": "eventbrite_event",
            "admin_notification_type": None,
            "background_check_processing": False,
        }

    proposal_form_id = _configured_form_id(
        secret,
        "VOLUNTEER_INTENT_PROPOSAL_FORM_ID",
        "VOLUNTEER_INTENT_PROPOSAL_FORM_ID",
    )
    if proposal_form_id:
        routes[proposal_form_id] = {
            "table_name": os.getenv("VOLUNTEER_INTENT_PROPOSAL_SUBMISSIONS_TABLE_NAME"),
            "bucket_name": None,
            "storage_prefix": None,
            "reconcile_minor_authorization": False,
            "preserve_signature_key": False,
            "key_strategy": "form",
            "admin_notification_type": "volunteer_intent_proposal",
            "background_check_processing": False,
        }

    background_form_id = _configured_form_id(
        secret,
        "VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID",
        "VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID",
    )
    if background_form_id:
        routes[background_form_id] = {
            "table_name": os.getenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME"),
            "bucket_name": os.getenv("VOLUNTEER_BACKGROUND_CHECK_FILES_BUCKET_NAME"),
            "storage_prefix": f"volunteer-background-checks/{background_form_id}",
            "reconcile_minor_authorization": False,
            "preserve_signature_key": False,
            "key_strategy": "form",
            "admin_notification_type": None,
            "background_check_processing": True,
        }

    return routes


def _storage_config_for_form(form_id: Any) -> dict[str, Any] | None:
    normalized_form_id = str(form_id or "").strip()
    if not normalized_form_id:
        return None
    config = _configured_form_routes().get(normalized_form_id)
    if not config:
        return None
    table_name = str(config.get("table_name") or "").strip()
    if not table_name:
        logger.warning("No submission table configured for form_id %s.", normalized_form_id)
        return None
    return config


def _minor_authorization_jobs_table():
    table_name = os.getenv("MINOR_AUTHORIZATION_JOBS_TABLE_NAME")
    if not table_name:
        return None
    return _dynamodb_table(table_name)


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


def _slugify_storage_fragment(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalized_question_key(value))
    slug = slug.strip("-")
    return slug or "file"


def _is_youform_file_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and parsed.netloc == "files.youform.com"


def _file_storage_location(
    parsed_body: dict[str, Any],
    question: str,
    file_url: str,
    storage_config: dict[str, Any],
) -> tuple[str, str] | None:
    bucket_name = str(storage_config.get("bucket_name") or "").strip()
    submission_id = parsed_body.get("submission_id")
    form_id = str(parsed_body.get("form_id") or "UNKNOWN_FORM")
    if not bucket_name or not submission_id:
        return None
    parsed = urlparse(file_url)
    extension = os.path.splitext(parsed.path)[1].lower()
    if not extension:
        extension = ".bin"
    if storage_config.get("preserve_signature_key") and question == SIGNATURE_QUESTION:
        key = f"youform-signatures/{submission_id}/signature{extension}"
        return bucket_name, key
    storage_prefix = str(storage_config.get("storage_prefix") or f"youform-files/{form_id}").strip("/")
    question_slug = _slugify_storage_fragment(question)
    key = f"{storage_prefix}/{submission_id}/{question_slug}{extension}"
    return bucket_name, key


def _download_signature(signature_url: str) -> tuple[bytes, str | None]:
    request = Request(
        signature_url,
        headers={
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=20) as response:
        content = response.read()
        content_type = response.headers.get_content_type() if response.headers else None
    return content, content_type


def _store_file_answer(
    parsed_body: dict[str, Any],
    question: str,
    file_url: str,
    storage_config: dict[str, Any],
) -> str:
    location = _file_storage_location(parsed_body, question, file_url, storage_config)
    if location is None:
        raise RuntimeError("A destination bucket and submission_id are required to store YouForm files.")
    bucket_name, key = location
    content, content_type = _download_signature(file_url)
    if not content_type:
        guessed, _ = mimetypes.guess_type(file_url)
        content_type = guessed or "application/octet-stream"
    _s3_client().put_object(
        Bucket=bucket_name,
        Key=key,
        Body=content,
        ContentType=content_type,
    )
    logger.info(
        "Stored YouForm file for submission %s question %s at s3://%s/%s",
        parsed_body.get("submission_id"),
        question,
        bucket_name,
        key,
    )
    return f"s3://{bucket_name}/{key}"


def _normalize_answers(parsed_body: dict[str, Any], storage_config: dict[str, Any]) -> list[dict[str, Any]]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return []
    normalized: list[dict[str, Any]] = []
    for question, answer in answers.items():
        normalized_question = _clean_text(str(question))
        normalized_answer = _clean_text(answer) if isinstance(answer, str) else answer
        if _is_youform_file_url(answer) and storage_config.get("bucket_name"):
            try:
                normalized_answer = _store_file_answer(
                    parsed_body,
                    str(normalized_question),
                    answer.strip(),
                    storage_config,
                )
            except Exception:
                logger.exception(
                    "Failed to copy YouForm file for submission %s question %s. Keeping original URL.",
                    parsed_body.get("submission_id"),
                    normalized_question,
                )
        normalized.append({"question": str(normalized_question), "answer": normalized_answer})
    return normalized


def _background_check_queue_url() -> str | None:
    value = os.getenv("BACKGROUND_CHECK_REVIEW_QUEUE_URL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _background_check_form_id() -> str:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret = _load_secret(secret_id)
        value = (secret.get("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID") or "").strip()
        if value:
            return value
        raise RuntimeError(f"VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID is missing in secret {secret_id}.")
    value = (os.getenv("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID") or "").strip()
    if value:
        return value
    raise RuntimeError("VOLUNTEER_BACKGROUND_CHECK_COMPLIANCE_FORM_ID is not configured.")


def _parse_s3_uri(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith("s3://"):
        return None
    without_scheme = value[5:]
    bucket_name, _, key = without_scheme.partition("/")
    if not bucket_name or not key:
        return None
    return bucket_name, key


def _is_background_check_identity_file(question: str, stored_answer: Any) -> bool:
    parsed = _parse_s3_uri(stored_answer)
    if parsed is None:
        return False
    _, key = parsed
    if not key.lower().endswith(".pdf"):
        return False
    normalized_question = _ascii_normalized(question)
    normalized_key = _ascii_normalized(os.path.basename(key))
    identity_markers = ("cedula", "documento de identidad", "documento identidad", "identificacion")
    return any(marker in normalized_question or marker in normalized_key for marker in identity_markers)


def _background_check_review_messages(item: dict[str, Any]) -> list[dict[str, Any]]:
    answers = item.get("answers")
    if not isinstance(answers, list):
        return []
    messages: list[dict[str, Any]] = []
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        question = str(answer.get("question") or "").strip()
        stored_answer = answer.get("answer")
        if not question or not _is_background_check_identity_file(question, stored_answer):
            continue
        parsed = _parse_s3_uri(stored_answer)
        if parsed is None:
            continue
        bucket_name, key = parsed
        messages.append(
            {
                "source": "youform_webhook",
                "document_kind": "cedula",
                "form_id": item.get("form_id"),
                "submission_id": item.get("submission_id"),
                "submission_pk": item.get("pk"),
                "submission_sk": item.get("sk"),
                "question": question,
                "s3_uri": stored_answer,
                "s3_bucket": bucket_name,
                "s3_key": key,
                "contact_name": item.get("contact_name"),
                "contact_email": item.get("contact_email"),
                "contact_phone": item.get("contact_phone"),
                "completed_at": item.get("completed_at"),
            }
        )
    return messages


def _enqueue_background_check_reviews(item: dict[str, Any]) -> list[dict[str, Any]]:
    # This queue is reserved exclusively for the compliance/background-check form.
    # Even if another form accidentally reaches this branch, we must refuse to
    # enqueue it to avoid mixing unrelated submissions into the reviewer flow.
    if str(item.get("form_id") or "").strip() != _background_check_form_id():
        logger.info(
            "Skipping background check enqueue for submission %s because form_id %s does not match the configured compliance form.",
            item.get("submission_id"),
            item.get("form_id"),
        )
        return []
    queue_url = _background_check_queue_url()
    if not queue_url:
        logger.info(
            "BACKGROUND_CHECK_REVIEW_QUEUE_URL is not configured. Skipping background check enqueue for submission %s.",
            item.get("submission_id"),
        )
        return []
    messages = _background_check_review_messages(item)
    if not messages:
        return []
    published: list[dict[str, Any]] = []
    client = _sqs_client()
    for message in messages:
        response = client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message, ensure_ascii=False, default=str),
        )
        published.append(
            {
                "submission_id": message.get("submission_id"),
                "document_kind": message.get("document_kind"),
                "question": message.get("question"),
                "s3_uri": message.get("s3_uri"),
                "message_id": response.get("MessageId"),
            }
        )
    logger.info("Enqueued background check review jobs: %s", json.dumps(published, ensure_ascii=False, default=str))
    return published


def _detected_file_answers(parsed_body: dict[str, Any]) -> list[dict[str, str]]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return []
    detected: list[dict[str, str]] = []
    for question, answer in answers.items():
        if _is_youform_file_url(answer):
            detected.append(
                {
                    "question": str(_clean_text(str(question))),
                    "url": str(answer).strip(),
                }
            )
    return detected


def _answer_lookup(parsed_body: dict[str, Any]) -> dict[str, Any]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return {}
    return {
        _normalized_question_key(str(question)): (_clean_text(answer) if isinstance(answer, str) else answer)
        for question, answer in answers.items()
    }


def _extract_scalar_answer(answer_lookup: dict[str, Any], *questions: str) -> str | None:
    for question in questions:
        value = answer_lookup.get(_normalized_question_key(question))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_eventbrite_event_metadata(event_url: Any) -> dict[str, str | None]:
    if not isinstance(event_url, str) or not event_url.strip():
        return {
            "eventbrite_event_url": None,
            "eventbrite_event_id": None,
            "eventbrite_event_slug": None,
            "eventbrite_event_name": None,
        }
    cleaned_url = event_url.strip()
    match = re.search(r"/e/([^/?#]+)-tickets-(\d+)", cleaned_url)
    if not match:
        return {
            "eventbrite_event_url": cleaned_url,
            "eventbrite_event_id": None,
            "eventbrite_event_slug": None,
            "eventbrite_event_name": None,
        }
    slug = match.group(1)
    return {
        "eventbrite_event_url": cleaned_url,
        "eventbrite_event_id": match.group(2),
        "eventbrite_event_slug": slug,
        "eventbrite_event_name": slug.replace("-", " "),
    }


def _normalized_phone_key(phone: str) -> str:
    return re.sub(r"\s+", "", phone.strip())


def _normalized_whatsapp_phone(phone: str | None) -> str | None:
    if not isinstance(phone, str) or not phone.strip():
        return None
    digits = re.sub(r"\D+", "", phone)
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
        f"Hola {contact_name}, recibí tu propuesta sobre {event_name} con fecha tentativa {requested_date}. "
        "Gracias por compartirla. Mi nombre es Daniel, no soy un bot respondiendo automáticamente. "
        "Me gustaría saber si ya tienes un lugar pensado y un aforo. La idea es empezar con 3-4 personas y, "
        "si es posible, tener una llamada de 15 min o menos para resolver dudas o explicar algunos detalles."
    )
    return f"https://wa.me/{phone}?text={quote(message)}"


def _build_keys(
    key_strategy: str,
    eventbrite_event_id: str | None,
    form_id: Any,
    submission_id: Any,
    registrant_email: str | None,
    event_date: str | None,
    completed_at: str | None,
    contact_phone: str | None = None,
) -> dict[str, str]:
    safe_form_id = str(form_id or "UNKNOWN_FORM")
    safe_submission_id = str(submission_id or "UNKNOWN_SUBMISSION")
    safe_completed_at = completed_at or "UNKNOWN"

    if key_strategy == "form":
        keys = {
            "pk": f"FORM#{safe_form_id}",
            "sk": f"SUBMISSION#{safe_submission_id}",
            "gsi1pk": f"FORM#{safe_form_id}",
            "gsi1sk": f"COMPLETED_AT#{safe_completed_at}#SUBMISSION#{safe_submission_id}",
        }
        if registrant_email:
            normalized_email = registrant_email.strip().lower()
            keys["gsi2pk"] = f"EMAIL#{normalized_email}"
            keys["gsi2sk"] = f"FORM#{safe_form_id}#COMPLETED_AT#{safe_completed_at}#SUBMISSION#{safe_submission_id}"
        if contact_phone:
            keys["gsi3pk"] = f"PHONE#{_normalized_phone_key(contact_phone)}"
            keys["gsi3sk"] = f"FORM#{safe_form_id}#COMPLETED_AT#{safe_completed_at}#SUBMISSION#{safe_submission_id}"
        return keys

    safe_event_id = eventbrite_event_id or UNKNOWN_EVENT_ID
    keys = {
        "pk": f"EVENT#{safe_event_id}#FORM#{safe_form_id}",
        "sk": f"SUBMISSION#{safe_submission_id}",
        "gsi1pk": f"EVENT#{safe_event_id}",
        "gsi1sk": f"COMPLETED_AT#{safe_completed_at}#SUBMISSION#{safe_submission_id}",
    }
    if registrant_email:
        normalized_email = registrant_email.strip().lower()
        keys["gsi2pk"] = f"EMAIL#{normalized_email}"
        keys["gsi2sk"] = f"EVENT_DATE#{event_date or 'UNKNOWN'}#EVENT#{safe_event_id}#SUBMISSION#{safe_submission_id}"
    if event_date:
        keys["gsi3pk"] = f"EVENT_DATE#{event_date}"
        keys["gsi3sk"] = (
            f"EVENT#{safe_event_id}#EMAIL#{(registrant_email or 'UNKNOWN').strip().lower()}#SUBMISSION#{safe_submission_id}"
        )
    return keys


def _build_submission_item(parsed_body: dict[str, Any], storage_config: dict[str, Any]) -> dict[str, Any] | None:
    submission_id = parsed_body.get("submission_id")
    if not submission_id:
        return None

    answer_lookup = _answer_lookup(parsed_body)
    key_strategy = str(storage_config.get("key_strategy") or "eventbrite_event")
    event_metadata = _extract_eventbrite_event_metadata(
        answer_lookup.get(_normalized_question_key(EVENT_URL_QUESTION))
    )
    event_date = _extract_scalar_answer(answer_lookup, EVENT_DATE_QUESTION)
    registration_email = _extract_scalar_answer(answer_lookup, REGISTRATION_EMAIL_QUESTION)
    contact_name = _extract_scalar_answer(answer_lookup, CONTACT_NAME_QUESTION)
    contact_email = _extract_scalar_answer(answer_lookup, CONTACT_EMAIL_QUESTION)
    contact_phone = _extract_scalar_answer(answer_lookup, CONTACT_PHONE_QUESTION)
    proposal_event_name = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_EVENT_NAME_QUESTION)
    proposal_presenter_intro = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_PRESENTATION_QUESTION)
    proposal_topic = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_TOPIC_QUESTION)
    proposal_requested_date = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_REQUESTED_DATE_QUESTION)
    proposal_requested_time = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_REQUESTED_TIME_QUESTION)
    proposal_admin_question = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_ADMIN_QUESTION)
    preferred_email = registration_email if key_strategy == "eventbrite_event" else (contact_email or registration_email)
    completed_at = parsed_body.get("completed_at")

    item = {
        **_build_keys(
            key_strategy,
            event_metadata["eventbrite_event_id"],
            parsed_body.get("form_id"),
            submission_id,
            preferred_email,
            event_date if isinstance(event_date, str) else None,
            completed_at if isinstance(completed_at, str) else None,
            contact_phone,
        ),
        "entity_type": "youform_submission",
        "submission_id": submission_id,
        "form_id": parsed_body.get("form_id"),
        "form_name": parsed_body.get("form_name"),
        "youform_event_id": parsed_body.get("event_id"),
        "event_type": parsed_body.get("event_type"),
        "started_at": parsed_body.get("started_at"),
        "completed_at": completed_at,
        "eventbrite_event_id": event_metadata["eventbrite_event_id"],
        "eventbrite_event_slug": event_metadata["eventbrite_event_slug"],
        "eventbrite_event_name": event_metadata["eventbrite_event_name"],
        "eventbrite_event_url": event_metadata["eventbrite_event_url"],
        "event_date": event_date,
        "registration_email": registration_email.lower().strip() if isinstance(registration_email, str) else None,
        "contact_name": contact_name,
        "contact_email": contact_email.lower().strip() if isinstance(contact_email, str) else None,
        "contact_phone": contact_phone,
        "proposal_event_name": proposal_event_name,
        "proposal_presenter_intro": proposal_presenter_intro,
        "proposal_topic": proposal_topic,
        "proposal_requested_date": proposal_requested_date,
        "proposal_requested_time": proposal_requested_time,
        "proposal_admin_question": proposal_admin_question,
        "answers": _normalize_answers(parsed_body, storage_config),
    }
    return {key: value for key, value in item.items() if value is not None}


def _volunteer_intent_from_email() -> str:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError("VOLUNTEER_INTENT_NOTIFICATION_FROM_EMAIL is not configured.")


def _volunteer_intent_allowed_admin_emails() -> set[str]:
    return {
        "wearecircleup@gmail.com",
        "hola@circleup.com.co",
    }


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
    return "Nueva propuesta de voluntariado"


def _build_volunteer_intent_admin_email(item: dict[str, Any]) -> tuple[str, str, str]:
    event_name = item.get("proposal_event_name") or "Nueva propuesta"
    subject = f"{_volunteer_intent_admin_subject_prefix()}: {event_name}"
    support_url = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_SUPPORT_URL", "https://circleup.com.co")
    logo_url = _volunteer_intent_logo_url()
    whatsapp_url = _build_volunteer_intent_whatsapp_url(item)

    summary = (
        f"{item.get('contact_name') or 'Alguien'} compartió una nueva propuesta para Circle Up. "
        "Te dejamos aquí los datos clave para revisarla rápido."
    )

    field_rows = [
        ("PK", item.get("pk")),
        ("Email", item.get("contact_email") or item.get("registration_email")),
        ("Teléfono", item.get("contact_phone")),
        ("¿Cómo se llama tu evento?", item.get("proposal_event_name")),
        ("¿De qué se tratará tu evento?", item.get("proposal_topic")),
        ("¿Qué día te gustaría que fuera el evento?", item.get("proposal_requested_date")),
        ("¿A qué hora?", item.get("proposal_requested_time")),
        ("¿Tienes alguna pregunta para nosotros?", item.get("proposal_admin_question")),
    ]
    field_rows = [(label, str(value)) for label, value in field_rows if value]

    text_lines = [
        "Hola,",
        "",
        summary,
        "",
    ]
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
        "<html>"
        "<head>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        "<style>"
        "@media screen and (max-width: 720px) {"
        "  .admin-shell { width: 100% !important; }"
        "  .content-col { padding: 28px 20px 22px !important; }"
        "}"
        "</style>"
        "</head>"
        "<body style=\"margin: 0; padding: 0; background-color: #f7f7f4; font-family: Arial, Helvetica, sans-serif; color: #153f69;\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background-color: #f7f7f4; padding: 40px 20px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" class=\"admin-shell\" style=\"max-width: 760px; background-color: #ffffff;\">"
        "<tr><td class=\"content-col\" style=\"padding: 32px 28px 28px;\">"
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
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\">"
        "<tr>"
        "<td style=\"vertical-align: bottom; text-align: left;\">"
        "<div style=\"margin: 0 0 4px; color: #7d95ad; font-size: 12px; line-height: 18px; text-transform: uppercase; letter-spacing: 0.12em;\">Circle Up Community</div>"
        f"<div style=\"font-size: 12px; line-height: 18px; color: #0f4978;\"><a href=\"{escape(support_url, quote=True)}\" style=\"color: #0f4978; text-decoration: none;\">circleup.com.co</a></div>"
        "</td>"
        "<td style=\"vertical-align: bottom; text-align: right;\">"
    )
    if logo_url:
        html_body += (
            f"<img src=\"{escape(logo_url, quote=True)}\" alt=\"Circle Up Community\" width=\"42\" style=\"display: inline-block; width: 42px; height: auto; border: 0; outline: none; text-decoration: none;\">"
        )
    html_body += (
        "</td>"
        "</tr>"
        "</table>"
        "</div>"
        "</td></tr></table></td></tr></table></body></html>"
    )
    return subject, text_body, html_body


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
        f"Hola {contact_name}, recibí tu propuesta sobre *{event_name}*, con fecha tentativa {requested_date}. "
        "Gracias por compartirla. Mi nombre es Daniel, no soy un bot respondiendo automáticamente. "
        "Me gustaría saber si ya tienes un lugar pensado y un aforo. La idea es empezar con 3-4 personas y, "
        "si es posible, tener una llamada de 15 min o menos, para resolver dudas o explicar algunos detalles. "
        "No dudes en escribir a este número cualquier duda; un mensaje de voz también está perfecto."
    )
    return f"https://wa.me/{phone}?text={quote(message)}"


def _volunteer_intent_admin_subject_prefix() -> str:
    value = os.getenv("VOLUNTEER_INTENT_NOTIFICATION_SUBJECT_PREFIX")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "Propuesta voluntario"


def _send_volunteer_intent_admin_notification(item: dict[str, Any]) -> dict[str, Any]:
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


def _record_admin_notification_result(
    table_name: str,
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
    _dynamodb_table(table_name).update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_values,
    )


def _reconcile_minor_authorization_job(item: dict[str, Any]) -> dict[str, Any]:
    jobs_table = _minor_authorization_jobs_table()
    event_id = item.get("eventbrite_event_id")
    registration_email = item.get("registration_email")
    submission_id = item.get("submission_id")
    completed_at = item.get("completed_at")
    authorized_form_id = _authorized_minor_form_id()

    # This webhook can be reused by multiple YouForm forms, but only the legal
    # minor-authorization form is allowed to mark a validation job as authorized.
    if item.get("form_id") != authorized_form_id:
        logger.info(
            "Skipping minor authorization reconciliation because form_id %s is not the authorized minor form %s.",
            item.get("form_id"),
            authorized_form_id,
        )
        return {"reconciled": False, "reason": "form_id_not_authorized"}

    if jobs_table is None:
        logger.info("Skipping minor authorization reconciliation because MINOR_AUTHORIZATION_JOBS_TABLE_NAME is not configured.")
        return {"reconciled": False, "reason": "jobs_table_not_configured"}
    if not event_id or not registration_email:
        logger.info(
            "Skipping minor authorization reconciliation because event_id or registration_email is missing for submission %s.",
            submission_id,
        )
        return {"reconciled": False, "reason": "missing_event_or_email"}

    response = jobs_table.query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"EMAIL#{registration_email}"),
    )
    items = response.get("Items") or []
    matching_jobs = [
        job for job in items
        if job.get("event_id") == event_id and job.get("status") in {"pending", "missing_form"}
    ]
    if not matching_jobs:
        logger.info(
            "No pending minor authorization job matched submission %s for event %s and email %s.",
            submission_id,
            event_id,
            registration_email,
        )
        return {"reconciled": False, "reason": "no_matching_job"}

    updated_jobs: list[dict[str, Any]] = []
    for job in matching_jobs:
        pk = job["pk"]
        sk = job["sk"]
        gsi1sk = f"COMPLETED_AT#{completed_at or 'UNKNOWN'}#EVENT#{event_id}#ATTENDEE#{job.get('attendee_id') or 'UNKNOWN_ATTENDEE'}"
        jobs_table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=(
                "SET #status = :status, "
                "validation_result = :validation_result, "
                "authorization_found = :authorization_found, "
                "matched_submission_id = :matched_submission_id, "
                "completed_at = :completed_at, "
                "last_attempt_at = :last_attempt_at, "
                "gsi1pk = :gsi1pk, "
                "gsi1sk = :gsi1sk"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "authorized",
                ":validation_result": "form_found",
                ":authorization_found": True,
                ":matched_submission_id": submission_id,
                ":completed_at": completed_at,
                ":last_attempt_at": completed_at,
                ":gsi1pk": "STATUS#authorized",
                ":gsi1sk": gsi1sk,
            },
        )
        updated_jobs.append({"pk": pk, "sk": sk})

    logger.info(
        "Reconciled minor authorization jobs from YouForm submission %s: %s",
        submission_id,
        json.dumps(updated_jobs, ensure_ascii=False, default=str),
    )
    return {
        "reconciled": True,
        "updated_jobs": updated_jobs,
        "submission_id": submission_id,
    }


def _store_submission(parsed_body: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    storage_config = _storage_config_for_form(parsed_body.get("form_id"))
    if storage_config is None:
        logger.info(
            "Skipping persistence because form_id %s is not configured for storage routing.",
            parsed_body.get("form_id"),
        )
        return False, None
    table_name = str(storage_config["table_name"])
    item = _build_submission_item(parsed_body, storage_config)
    if item is None:
        logger.info("Skipping persistence because submission_id is missing.")
        return False, None
    _dynamodb_table(table_name).put_item(Item=item)
    logger.info("Stored YouForm submission %s in DynamoDB table %s.", item["submission_id"], table_name)
    return True, item


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    raw_body = _decoded_body(event)
    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_body = None

    stored = False
    reconciliation: dict[str, Any] | None = None
    admin_notification: dict[str, Any] | None = None
    background_check_reviews: list[dict[str, Any]] | None = None
    storage_route: dict[str, Any] | None = None
    stored_item: dict[str, Any] | None = None
    detected_file_answers: list[dict[str, str]] = []

    if isinstance(parsed_body, dict):
        storage_config = _storage_config_for_form(parsed_body.get("form_id"))
        detected_file_answers = _detected_file_answers(parsed_body)
        if storage_config is not None:
            storage_route = {
                "form_id": parsed_body.get("form_id"),
                "table_name": storage_config.get("table_name"),
                "bucket_name": storage_config.get("bucket_name"),
                "storage_prefix": storage_config.get("storage_prefix"),
                "reconcile_minor_authorization": storage_config.get("reconcile_minor_authorization"),
                "key_strategy": storage_config.get("key_strategy"),
                "admin_notification_type": storage_config.get("admin_notification_type"),
                "background_check_processing": storage_config.get("background_check_processing"),
            }
        stored, item = _store_submission(parsed_body)
        stored_item = item
        if stored and item is not None and storage_config and storage_config.get("reconcile_minor_authorization"):
            reconciliation = _reconcile_minor_authorization_job(item)
        if stored and item is not None and storage_config and storage_config.get("admin_notification_type") == "volunteer_intent_proposal":
            try:
                admin_notification = _send_volunteer_intent_admin_notification(item)
                _record_admin_notification_result(str(storage_config["table_name"]), item, admin_notification)
            except Exception as exc:
                logger.exception("Failed to send volunteer intent admin notification for submission %s.", item.get("submission_id"))
                admin_notification = {
                    "sent": False,
                    "status": "failed",
                    "message_id": None,
                }
                _record_admin_notification_result(str(storage_config["table_name"]), item, admin_notification, str(exc))
        if stored and item is not None and storage_config and storage_config.get("background_check_processing"):
            background_check_reviews = _enqueue_background_check_reviews(item)

    logger.info(
        "Received YouForm webhook: %s",
        json.dumps(
            {
                "request_context": event.get("requestContext"),
                "raw_body": raw_body,
                "parsed_body": parsed_body,
                "storage_route": storage_route,
                "file_answers_detected": detected_file_answers,
                "stored": stored,
                "stored_item": stored_item,
                "admin_notification": admin_notification,
                "background_check_reviews": background_check_reviews,
                "reconciliation": reconciliation,
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
                "admin_notification": admin_notification,
                "background_check_reviews": background_check_reviews,
                "reconciliation": reconciliation,
            }
        ),
    }
