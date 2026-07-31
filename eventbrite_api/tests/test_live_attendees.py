"""Opt-in verification of real registrations created through Eventbrite checkout.

Eventbrite's public API exposes attendees for reading, not an endpoint that
creates an arbitrary attendee. Register the two test accounts through the
published event checkout, then run this test. It never writes check-in state.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


pytestmark = pytest.mark.live


def test_real_checkout_registrations_are_visible_without_checkin() -> None:
    event_id = os.getenv("EVENTBRITE_ATTENDEE_EVENT_ID")
    assert event_id, "Set EVENTBRITE_ATTENDEE_EVENT_ID to the published test event."
    expected = {"danielnicolasmuner@gmail.com", "gocircleup@gmail.com"}

    with TestClient(app) as client:
        response = client.get(f"/events/{event_id}/attendees", params={"page": 1})
        assert response.status_code == 200, response.text
        attendees = response.json()["attendees"]

    actual = {item.get("profile", {}).get("email", "").lower() for item in attendees}
    assert expected <= actual
