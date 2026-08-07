"""Contract tests that run without 360nrs credentials or network access."""

from app.main import app
from app.schemas import SMSSendRequest


def test_crud_routes_are_registered() -> None:
    routes = {(route.path, method) for route in app.routes for method in route.methods or set()}

    assert ("/health", "GET") in routes
    assert ("/account", "GET") in routes
    assert ("/sms", "POST") in routes
    assert ("/sms/{message_id}", "GET") in routes


def test_sms_request_normalizes_recipients() -> None:
    request = SMSSendRequest(
        to=["+57 319 447 7860"],
        **{"from": "TEST", "message": "Hola"},
    )

    assert request.api_payload() == {
        "to": ["573194477860"],
        "from": "TEST",
        "message": "Hola",
    }
