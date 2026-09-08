import base64
import json
import logging
import mimetypes
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, dict[str, str]] = {}


class ProcessingError(RuntimeError):
    def __init__(self, error_type: str, detail: str, status_code: int = 500):
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail
        self.status_code = status_code

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
PARTITION_KEY_QUESTION = "Partition key"
BACKGROUND_CHECK_APPROVAL_QUESTION = "Estado de aprobación"


def _log_json(message: str, payload: dict[str, Any]) -> None:
    logger.info("%s: %s", message, json.dumps(payload, ensure_ascii=False, default=str))


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
    raw = str(value or "")
    repaired = raw
    for _ in range(2):
        if not any(marker in repaired for marker in ("Ã", "Â")):
            break
        try:
            candidate = repaired.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if candidate == repaired:
            break
        repaired = candidate
    cleaned = str(_clean_text(repaired) or "").strip().lower()
    ascii_text = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    # Some webhook payloads arrive with replacement characters like "?" after
    # a lossy decode. We collapse punctuation so question matching keeps
    # working even when accents were mangled upstream.
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _dynamodb_table(table_name: str):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _lambda_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("lambda", region_name=region)


def _minor_authorization_processor_function_name() -> str:
    value = (os.getenv("MINOR_AUTHORIZATION_PROCESSOR_FUNCTION_NAME") or "").strip()
    if value:
        return value
    raise RuntimeError("MINOR_AUTHORIZATION_PROCESSOR_FUNCTION_NAME is not configured.")


def _volunteer_intent_notifier_function_name() -> str:
    value = (os.getenv("VOLUNTEER_INTENT_NOTIFIER_FUNCTION_NAME") or "").strip()
    if value:
        return value
    raise RuntimeError("VOLUNTEER_INTENT_NOTIFIER_FUNCTION_NAME is not configured.")


def _background_check_dispatcher_function_name() -> str:
    value = (os.getenv("BACKGROUND_CHECK_DISPATCHER_FUNCTION_NAME") or "").strip()
    if value:
        return value
    raise RuntimeError("BACKGROUND_CHECK_DISPATCHER_FUNCTION_NAME is not configured.")


def _invoke_lambda(function_name: str, payload: dict[str, Any], invocation_type: str) -> dict[str, Any]:
    response = _lambda_client().invoke(
        FunctionName=function_name,
        InvocationType=invocation_type,
        Payload=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
    )
    status_code = int(response.get("StatusCode") or 0)
    if invocation_type == "Event":
        if status_code != 202:
            raise RuntimeError(f"Async invoke for {function_name} failed with status {status_code}.")
        return {
            "accepted": True,
            "function_name": function_name,
            "status_code": status_code,
        }

    if status_code != 200:
        raise RuntimeError(f"Sync invoke for {function_name} failed with status {status_code}.")
    raw_payload = response["Payload"].read().decode("utf-8")
    parsed = json.loads(raw_payload) if raw_payload else {}
    if int(parsed.get("statusCode") or 200) >= 400:
        raise RuntimeError(f"{function_name} returned status {parsed.get('statusCode')}.")
    body = parsed.get("body")
    if isinstance(body, str) and body:
        return json.loads(body)
    if isinstance(body, dict):
        return body
    return parsed


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


def _background_internal_review_form_id() -> str:
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret = _load_secret(secret_id)
        value = (secret.get("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID") or "").strip()
        if value:
            return value
        raise RuntimeError(f"VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID is missing in secret {secret_id}.")
    value = (os.getenv("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID") or "").strip()
    if value:
        return value
    raise RuntimeError("VOLUNTEER_BACKGROUND_INTERNAL_REVIEW_FORM_ID is not configured.")


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


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


def _normalized_answers_map(parsed_body: dict[str, Any]) -> dict[str, Any]:
    answers = parsed_body.get("answers")
    if not isinstance(answers, dict):
        return {}
    return {
        str(_clean_text(str(question))): (_clean_text(answer) if isinstance(answer, str) else answer)
        for question, answer in answers.items()
    }


def _deep_clean(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_deep_clean(item) for item in value]
    if isinstance(value, dict):
        return {str(_clean_text(str(key))): _deep_clean(item) for key, item in value.items()}
    return value


def _parse_background_partition_key(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    match = re.fullmatch(
        r"FORM#(?P<form_id>[^#]+)#SUBMISSION#(?P<submission_id>[^#]+)#DOCUMENT#(?P<document_number>.+)",
        value.strip(),
    )
    if not match:
        return None
    parsed = match.groupdict()
    return {
        "partition_key": value.strip(),
        "source_form_id": parsed["form_id"],
        "source_submission_id": parsed["submission_id"],
        "source_document_number": parsed["document_number"],
        "source_submission_pk": f"FORM#{parsed['form_id']}",
        "source_submission_sk": f"SUBMISSION#{parsed['submission_id']}",
    }


def _is_background_check_internal_review(parsed_body: dict[str, Any]) -> bool:
    # This form must always be gated by the exact configured form id. Otherwise,
    # any unrelated YouForm payload that happens to include similarly named
    # fields could be persisted as a background-check internal review record.
    if str(parsed_body.get("form_id") or "").strip() != _background_internal_review_form_id():
        return False
    answers = _answer_lookup(parsed_body)
    partition_key = _extract_scalar_answer(answers, PARTITION_KEY_QUESTION)
    approval_status = _extract_scalar_answer(
        answers,
        BACKGROUND_CHECK_APPROVAL_QUESTION,
        "estado de aprobacion",
        "estado de aprobaci",
        "estado aprobacion",
    )
    return isinstance(partition_key, str) and partition_key.startswith("FORM#") and isinstance(approval_status, str)


def _storage_config_for_form(form_id: Any, parsed_body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    normalized_form_id = str(form_id or "").strip()
    config = _configured_form_routes().get(normalized_form_id) if normalized_form_id else None
    if config:
        table_name = str(config.get("table_name") or "").strip()
        if not table_name:
            logger.warning("No submission table configured for form_id %s.", normalized_form_id)
            return None
        return config

    # The internal review form is intentionally linked through the hidden
    # "Partition key" answer instead of depending on a dedicated event URL.
    # We still require the exact secret-managed form id so only the intended
    # internal review workflow can write sibling records next to a background
    # check submission.
    if isinstance(parsed_body, dict) and _is_background_check_internal_review(parsed_body):
        table_name = str(os.getenv("VOLUNTEER_BACKGROUND_CHECK_SUBMISSIONS_TABLE_NAME") or "").strip()
        if not table_name:
            logger.warning("No submission table configured for background check internal review form_id %s.", normalized_form_id)
            return None
        return {
            "table_name": table_name,
            "bucket_name": None,
            "storage_prefix": None,
            "reconcile_minor_authorization": False,
            "preserve_signature_key": False,
            "key_strategy": "background_internal_review",
            "admin_notification_type": None,
            "background_check_processing": False,
        }
    return None

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


def _request_context_summary(request_context: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "request_id": (request_context or {}).get("requestId"),
        "time": (request_context or {}).get("time"),
    }


def _parse_webhook(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_body = _decoded_body(event)
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as exc:
        raise ProcessingError("invalid_payload", "Invalid JSON body.", status_code=400) from exc
    if not isinstance(payload, dict):
        raise ProcessingError("invalid_payload", "Webhook body must be a JSON object.", status_code=400)
    return payload, event.get("requestContext")


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
                logger.exception("Failed to copy YouForm file. Keeping original URL.")
                _log_json(
                    "YouForm file copy fallback",
                    {
                        "error_type": "file_copy_error",
                        "submission_id": parsed_body.get("submission_id"),
                        "form_id": parsed_body.get("form_id"),
                        "question": str(normalized_question),
                    },
                )
        normalized.append({"question": str(normalized_question), "answer": normalized_answer})
    return normalized

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
        expected_ascii = _ascii_normalized(question)
        for answer_key, answer_value in answer_lookup.items():
            normalized_key = _ascii_normalized(answer_key)
            if (
                (
                    normalized_key == expected_ascii
                    or (
                        " " in expected_ascii
                        and (
                            (expected_ascii and expected_ascii in normalized_key)
                            or (normalized_key and normalized_key in expected_ascii)
                        )
                    )
                )
                and isinstance(answer_value, str)
                and answer_value.strip()
            ):
                return answer_value.strip()
    return None


def _extract_event_url_answer(answer_lookup: dict[str, Any]) -> str | None:
    direct = _extract_scalar_answer(answer_lookup, EVENT_URL_QUESTION, "evento asiste", "a que evento asiste")
    if direct:
        return direct
    for answer_key, answer_value in answer_lookup.items():
        if not isinstance(answer_value, str) or not answer_value.strip():
            continue
        normalized_key = _ascii_normalized(answer_key)
        if "evento" in normalized_key and "eventbrite" in answer_value:
            return answer_value.strip()
    return None


def _extract_event_date_answer(answer_lookup: dict[str, Any]) -> str | None:
    direct = _extract_scalar_answer(answer_lookup, EVENT_DATE_QUESTION, "que dia es el evento", "dia es el evento")
    if direct:
        return direct
    for answer_key, answer_value in answer_lookup.items():
        if not isinstance(answer_value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", answer_value.strip()):
            continue
        normalized_key = _ascii_normalized(answer_key)
        if "evento" in normalized_key:
            return answer_value.strip()
    return None


def _extract_registration_email_answer(answer_lookup: dict[str, Any]) -> str | None:
    direct = _extract_scalar_answer(
        answer_lookup,
        REGISTRATION_EMAIL_QUESTION,
        "con que correo vas a realizar la inscripcion",
        "correo vas a realizar la inscripcion",
    )
    if direct:
        return direct
    for answer_key, answer_value in answer_lookup.items():
        if not isinstance(answer_value, str) or "@" not in answer_value:
            continue
        normalized_key = _ascii_normalized(answer_key)
        if ("correo" in normalized_key or "email" in normalized_key) and (
            "inscrip" in normalized_key or "registr" in normalized_key or "realizar" in normalized_key
        ):
            return answer_value.strip()
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


def _build_keys(
    key_strategy: str,
    eventbrite_event_id: str | None,
    form_id: Any,
    submission_id: Any,
    registrant_email: str | None,
    event_date: str | None,
    completed_at: str | None,
    contact_phone: str | None = None,
    source_submission_pk: str | None = None,
    source_submission_sk: str | None = None,
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

    if key_strategy == "background_internal_review":
        safe_source_pk = source_submission_pk or f"FORM#{safe_form_id}"
        safe_source_sk = source_submission_sk or "SUBMISSION#UNKNOWN_SOURCE_SUBMISSION"
        keys = {
            "pk": safe_source_pk,
            "sk": f"{safe_source_sk}#INTERNAL_REVIEW#{safe_submission_id}",
            "gsi1pk": safe_source_pk,
            "gsi1sk": f"COMPLETED_AT#{safe_completed_at}#INTERNAL_REVIEW#{safe_submission_id}",
        }
        if registrant_email:
            normalized_email = registrant_email.strip().lower()
            keys["gsi2pk"] = f"EMAIL#{normalized_email}"
            keys["gsi2sk"] = f"{safe_source_pk}#COMPLETED_AT#{safe_completed_at}#INTERNAL_REVIEW#{safe_submission_id}"
        if contact_phone:
            keys["gsi3pk"] = f"PHONE#{_normalized_phone_key(contact_phone)}"
            keys["gsi3sk"] = f"{safe_source_pk}#COMPLETED_AT#{safe_completed_at}#INTERNAL_REVIEW#{safe_submission_id}"
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
    normalized_answers = _normalized_answers_map(parsed_body)
    event_metadata = _extract_eventbrite_event_metadata(_extract_event_url_answer(answer_lookup))
    event_date = _extract_event_date_answer(answer_lookup)
    registration_email = _extract_registration_email_answer(answer_lookup)
    contact_name = _extract_scalar_answer(answer_lookup, CONTACT_NAME_QUESTION)
    contact_email = _extract_scalar_answer(answer_lookup, CONTACT_EMAIL_QUESTION)
    contact_phone = _extract_scalar_answer(answer_lookup, CONTACT_PHONE_QUESTION)
    proposal_event_name = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_EVENT_NAME_QUESTION)
    proposal_presenter_intro = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_PRESENTATION_QUESTION)
    proposal_topic = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_TOPIC_QUESTION)
    proposal_requested_date = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_REQUESTED_DATE_QUESTION)
    proposal_requested_time = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_REQUESTED_TIME_QUESTION)
    proposal_admin_question = _extract_scalar_answer(answer_lookup, VOLUNTEER_INTENT_ADMIN_QUESTION)
    partition_key = _extract_scalar_answer(answer_lookup, PARTITION_KEY_QUESTION)
    parsed_partition_key = _parse_background_partition_key(partition_key)
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
            parsed_partition_key["source_submission_pk"] if parsed_partition_key else None,
            parsed_partition_key["source_submission_sk"] if parsed_partition_key else None,
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
    if key_strategy == "background_internal_review":
        item.update(
            {
                "source_partition_key": parsed_partition_key["partition_key"] if parsed_partition_key else None,
                "source_form_id": parsed_partition_key["source_form_id"] if parsed_partition_key else None,
                "source_submission_id": parsed_partition_key["source_submission_id"] if parsed_partition_key else None,
                "source_document_number": parsed_partition_key["source_document_number"] if parsed_partition_key else None,
                "source_submission_pk": parsed_partition_key["source_submission_pk"] if parsed_partition_key else None,
                "source_submission_sk": parsed_partition_key["source_submission_sk"] if parsed_partition_key else None,
                "answers_map": normalized_answers,
            }
        )
    return {key: value for key, value in item.items() if value is not None}


def _build_background_internal_review_payload(parsed_body: dict[str, Any]) -> dict[str, Any] | None:
    answer_lookup = _answer_lookup(parsed_body)
    partition_key = _extract_scalar_answer(answer_lookup, PARTITION_KEY_QUESTION)
    parsed_partition_key = _parse_background_partition_key(partition_key)
    if not parsed_partition_key:
        return None

    return {
        "pk": parsed_partition_key["source_submission_pk"],
        "sk": parsed_partition_key["source_submission_sk"],
        "internal_review": {
            "partition_key": parsed_partition_key["partition_key"],
            "source_form_id": parsed_partition_key["source_form_id"],
            "source_submission_id": parsed_partition_key["source_submission_id"],
            "source_document_number": parsed_partition_key["source_document_number"],
            "submission_id": parsed_body.get("submission_id"),
            "form_id": parsed_body.get("form_id"),
            "form_name": parsed_body.get("form_name"),
            "youform_event_id": parsed_body.get("event_id"),
            "event_type": parsed_body.get("event_type"),
            "started_at": parsed_body.get("started_at"),
            "completed_at": parsed_body.get("completed_at"),
            "answers": _normalized_answers_map(parsed_body),
        },
    }


def _store_background_internal_review(parsed_body: dict[str, Any], storage_config: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    payload = _build_background_internal_review_payload(parsed_body)
    if payload is None:
        logger.info("Skipping background internal review persistence because Partition key is missing or invalid.")
        return False, None

    table_name = str(storage_config["table_name"])
    _dynamodb_table(table_name).update_item(
        Key={"pk": payload["pk"], "sk": payload["sk"]},
        UpdateExpression="SET internal_review = :internal_review",
        ExpressionAttributeValues={":internal_review": payload["internal_review"]},
    )
    logger.info(
        "Stored YouForm internal review %s in DynamoDB table %s for original submission %s / %s.",
        parsed_body.get("submission_id"),
        table_name,
        payload["pk"],
        payload["sk"],
    )
    return True, payload


def _storage_route_summary(parsed_body: dict[str, Any], storage_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if storage_config is None:
        return None
    return {
        "form_id": parsed_body.get("form_id"),
        "table_name": storage_config.get("table_name"),
        "bucket_name": storage_config.get("bucket_name"),
        "storage_prefix": storage_config.get("storage_prefix"),
        "reconcile_minor_authorization": storage_config.get("reconcile_minor_authorization"),
        "key_strategy": storage_config.get("key_strategy"),
        "admin_notification_type": storage_config.get("admin_notification_type"),
        "background_check_processing": storage_config.get("background_check_processing"),
    }


def _resolve_storage_route(parsed_body: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    storage_config = _storage_config_for_form(parsed_body.get("form_id"), parsed_body)
    return storage_config, _storage_route_summary(parsed_body, storage_config)


def _store_submission_with_config(
    parsed_body: dict[str, Any],
    storage_config: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any] | None]:
    if storage_config is None:
        logger.info(
            "Skipping persistence because form_id %s is not configured for storage routing.",
            parsed_body.get("form_id"),
        )
        return False, None
    if str(storage_config.get("key_strategy") or "") == "background_internal_review":
        return _store_background_internal_review(parsed_body, storage_config)
    table_name = str(storage_config["table_name"])
    item = _build_submission_item(parsed_body, storage_config)
    if item is None:
        logger.info("Skipping persistence because submission_id is missing.")
        return False, None
    _dynamodb_table(table_name).put_item(Item=item)
    logger.info("Stored YouForm submission %s in DynamoDB table %s.", item["submission_id"], table_name)
    return True, item


def _store_submission(parsed_body: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    storage_config, _storage_route = _resolve_storage_route(parsed_body)
    return _store_submission_with_config(parsed_body, storage_config)


def _dispatch_followups(item: dict[str, Any], storage_config: dict[str, Any]) -> dict[str, Any]:
    followups: dict[str, Any] = {
        "reconciliation": None,
        "admin_notification": None,
        "background_check_reviews": None,
    }
    try:
        if storage_config.get("reconcile_minor_authorization"):
            followups["reconciliation"] = _invoke_lambda(
                _minor_authorization_processor_function_name(),
                item,
                "RequestResponse",
            )
        if storage_config.get("admin_notification_type") == "volunteer_intent_proposal":
            followups["admin_notification"] = _invoke_lambda(
                _volunteer_intent_notifier_function_name(),
                item,
                "Event",
            )
        if storage_config.get("background_check_processing"):
            followups["background_check_reviews"] = _invoke_lambda(
                _background_check_dispatcher_function_name(),
                item,
                "Event",
            )
    except Exception as exc:
        raise ProcessingError("downstream_invoke_error", str(exc), status_code=200) from exc
    return followups


def _submission_summary(parsed_body: dict[str, Any]) -> dict[str, Any]:
    answers = parsed_body.get("answers")
    answer_count = len(answers) if isinstance(answers, dict) else 0
    return {
        "form_id": parsed_body.get("form_id"),
        "form_name": parsed_body.get("form_name"),
        "submission_id": parsed_body.get("submission_id"),
        "event_type": parsed_body.get("event_type"),
        "completed_at": parsed_body.get("completed_at"),
        "answer_count": answer_count,
    }


def _stored_item_summary(stored_item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(stored_item, dict):
        return None
    return {
        "pk": stored_item.get("pk"),
        "sk": stored_item.get("sk"),
        "submission_id": stored_item.get("submission_id"),
        "form_id": stored_item.get("form_id"),
        "eventbrite_event_id": stored_item.get("eventbrite_event_id"),
        "answers_count": len(stored_item.get("answers") or []),
    }


def _followup_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    summary = {
        "accepted": result.get("accepted"),
        "function_name": result.get("function_name"),
        "status_code": result.get("status_code"),
    }
    if "reconciled" in result:
        summary.update(
            {
                "reconciled": result.get("reconciled"),
                "reason": result.get("reason"),
                "submission_id": result.get("submission_id"),
                "updated_job_count": len(result.get("updated_jobs") or []),
            }
        )
    return {key: value for key, value in summary.items() if value is not None}


def _log_webhook_summary(
    request_context: dict[str, Any] | None,
    parsed_body: dict[str, Any] | None,
    storage_route: dict[str, Any] | None,
    detected_file_answers: list[dict[str, str]],
    stored: bool,
    stored_item: dict[str, Any] | None,
    reconciliation: dict[str, Any] | None,
    admin_notification: dict[str, Any] | None,
    background_check_reviews: dict[str, Any] | None,
    error_type: str | None = None,
    error_detail: str | None = None,
) -> None:
    _log_json(
        "Received YouForm webhook",
        {
            "request_context": _request_context_summary(request_context),
            "submission": _submission_summary(parsed_body) if isinstance(parsed_body, dict) else None,
            "storage_route": storage_route,
            "detected_files": {
                "file_answer_count": len(detected_file_answers),
                "questions": [item.get("question") for item in detected_file_answers if item.get("question")][:8],
            },
            "stored": stored,
            "stored_item": _stored_item_summary(stored_item),
            "reconciliation": _followup_summary(reconciliation),
            "admin_notification": _followup_summary(admin_notification),
            "background_check_reviews": _followup_summary(background_check_reviews),
            "error_type": error_type,
            "error_detail": error_detail,
        },
    )


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    parsed_body: dict[str, Any] | None = None
    request_context: dict[str, Any] | None = event.get("requestContext")
    stored = False
    reconciliation: dict[str, Any] | None = None
    admin_notification: dict[str, Any] | None = None
    background_check_reviews: dict[str, Any] | None = None
    storage_route: dict[str, Any] | None = None
    stored_item: dict[str, Any] | None = None
    detected_file_answers: list[dict[str, str]] = []
    try:
        parsed_body, request_context = _parse_webhook(event)
        detected_file_answers = _detected_file_answers(parsed_body)
        storage_config, storage_route = _resolve_storage_route(parsed_body)
        if storage_config is None:
            _log_webhook_summary(
                request_context,
                parsed_body,
                None,
                detected_file_answers,
                stored=False,
                stored_item=None,
                reconciliation=None,
                admin_notification=None,
                background_check_reviews=None,
                error_type="unknown_form_route",
                error_detail="Form is not configured for storage routing.",
            )
            return _json_response(
                200,
                {
                    "ok": True,
                    "message": "YouForm webhook received.",
                    "stored": False,
                    "reason": "unknown_form_route",
                    "admin_notification": None,
                    "background_check_reviews": None,
                    "reconciliation": None,
                },
            )
        try:
            stored, stored_item = _store_submission_with_config(parsed_body, storage_config)
        except Exception as exc:
            raise ProcessingError("storage_error", str(exc), status_code=500) from exc

        if stored and stored_item is not None:
            followups = _dispatch_followups(stored_item, storage_config)
            reconciliation = followups["reconciliation"]
            admin_notification = followups["admin_notification"]
            background_check_reviews = followups["background_check_reviews"]

        _log_webhook_summary(
            request_context,
            parsed_body,
            storage_route,
            detected_file_answers,
            stored,
            stored_item,
            reconciliation,
            admin_notification,
            background_check_reviews,
        )
        return _json_response(
            200,
            {
                "ok": True,
                "message": "YouForm webhook received.",
                "stored": stored,
                "admin_notification": admin_notification,
                "background_check_reviews": background_check_reviews,
                "reconciliation": reconciliation,
            },
        )
    except ProcessingError as exc:
        logger.exception("YouForm webhook processing failed: %s", exc.error_type)
        _log_webhook_summary(
            request_context,
            parsed_body,
            storage_route,
            detected_file_answers,
            stored,
            stored_item,
            reconciliation,
            admin_notification,
            background_check_reviews,
            error_type=exc.error_type,
            error_detail=exc.detail,
        )
        return _json_response(
            exc.status_code,
            {
                "ok": False,
                "message": "YouForm webhook processing failed.",
                "error_type": exc.error_type,
                "detail": exc.detail,
                "stored": stored,
                "admin_notification": admin_notification,
                "background_check_reviews": background_check_reviews,
                "reconciliation": reconciliation,
            },
        )
    except Exception as exc:
        logger.exception("Unexpected YouForm webhook error.")
        _log_webhook_summary(
            request_context,
            parsed_body,
            storage_route,
            detected_file_answers,
            stored,
            stored_item,
            reconciliation,
            admin_notification,
            background_check_reviews,
            error_type="unexpected_error",
            error_detail=str(exc),
        )
        return _json_response(
            500,
            {
                "ok": False,
                "message": "YouForm webhook processing failed.",
                "error_type": "unexpected_error",
                "detail": str(exc),
                "stored": stored,
                "admin_notification": admin_notification,
                "background_check_reviews": background_check_reviews,
                "reconciliation": reconciliation,
            },
        )
