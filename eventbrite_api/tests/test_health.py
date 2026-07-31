"""Contract tests that run without Eventbrite credentials or network access."""

from app.main import app
from app.exports import attendee_export
from app.schemas import EventCreate


def test_create_payload_converts_bogota_time_to_utc() -> None:
    event = EventCreate(
        name="Evento de prueba",
        start="2026-07-27T10:00:00-05:00",
        end="2026-07-27T11:00:00-05:00",
    )

    payload = event.eventbrite_payload("USD")

    assert payload["start"]["utc"] == "2026-07-27T15:00:00Z"
    assert payload["end"]["utc"] == "2026-07-27T16:00:00Z"
    assert payload["currency"] == "USD"


def test_crud_routes_are_registered() -> None:
    routes = {(route.path, method) for route in app.routes for method in route.methods or set()}

    assert ("/health", "GET") in routes
    assert ("/events", "GET") in routes
    assert ("/events", "POST") in routes
    assert ("/event-instantiations", "POST") in routes
    assert ("/event-instantiations/{event_id}/publish", "POST") in routes
    assert ("/events/{event_id}/image/upload-request", "GET") in routes
    assert ("/events/{event_id}/image/upload-binary", "POST") in routes
    assert ("/events/{event_id}/image/complete", "POST") in routes
    assert ("/events/{event_id}", "GET") in routes
    assert ("/events/{event_id}", "PATCH") in routes
    assert ("/events/{event_id}", "DELETE") in routes
    assert ("/events/{event_id}/attendees", "GET") in routes
    assert ("/events/{event_id}/attendees/{attendee_id}", "GET") in routes
    assert ("/events/{event_id}/attendance", "GET") in routes
    assert ("/events/{event_id}/export", "GET") in routes


def test_export_normalizes_answers_without_barcodes() -> None:
    export = attendee_export(
        {"id": "event-1", "name": {"text": "Taller"}, "status": "live"},
        [
            {
                "id": "attendee-1",
                "profile": {"name": "Ana Perez", "email": "ana@example.com"},
                "checked_in": True,
                "barcodes": [{"barcode": "do-not-export"}],
                "answers": [{"question_id": "q1", "question": "Interes", "answer": "Python", "type": "text"}],
            }
        ],
    )

    attendee = export["attendees"][0]
    assert attendee["answers"][0]["answer"] == "Python"
    assert "barcodes" not in attendee
