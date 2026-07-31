from app.schemas import VenueCreate, VenueUpdate


def test_venue_coordinates_are_nested_in_eventbrite_address() -> None:
    payload = VenueCreate(name="Casa", latitude=4.711, longitude=-74.072).eventbrite_payload()

    assert payload["address"]["latitude"] == 4.711
    assert payload["address"]["longitude"] == -74.072
    assert "latitude" not in payload
    assert "longitude" not in payload


def test_venue_update_coordinates_are_nested_in_eventbrite_address() -> None:
    payload = VenueUpdate(latitude=4.711, longitude=-74.072).eventbrite_payload()

    assert payload == {"address": {"latitude": 4.711, "longitude": -74.072}}
