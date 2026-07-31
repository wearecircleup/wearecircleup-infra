"""Stable, provider-neutral attendee records for future data exports."""

from datetime import datetime, timezone


def attendee_record(event_id: str, attendee: dict) -> dict:
    profile = attendee.get("profile") or {}
    answers = attendee.get("answers") or []

    return {
        "event_id": event_id,
        "attendee_id": attendee.get("id"),
        "name": profile.get("name"),
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "email": profile.get("email"),
        "ticket_class_id": attendee.get("ticket_class_id"),
        "ticket_class_name": attendee.get("ticket_class_name"),
        "checked_in": attendee.get("checked_in", False),
        "attendee_status": attendee.get("status"),
        "cancelled": attendee.get("cancelled", False),
        "refunded": attendee.get("refunded", False),
        "answers": [
            {
                "question_id": answer.get("question_id"),
                "question": answer.get("question"),
                "answer": answer.get("answer"),
                "type": answer.get("type"),
            }
            for answer in answers
        ],
        "source": "eventbrite",
    }


def attendee_export(event: dict, attendees: list[dict]) -> dict:
    event_id = str(event["id"])
    return {
        "export_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": {
            "id": event_id,
            "name": (event.get("name") or {}).get("text"),
            "start": event.get("start"),
            "end": event.get("end"),
            "status": event.get("status"),
        },
        "attendees": [attendee_record(event_id, attendee) for attendee in attendees],
    }
