"""Network-free tests for the fixed Circle Up instantiation sequence."""

import asyncio

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.instantiation import EventInstantiationManager
from app.schemas import EventInstantiation


def valid_payload() -> dict:
    return {
        "name": "Clase de prueba",
        "start": "2026-08-04T15:00:00Z",
        "end": "2026-08-04T16:00:00Z",
        "timezone": "America/Bogota",
        "online_event": False,
        "venue_id": "venue-1",
        "capacity": 3,
        "ticket_name": "General",
        "registration_opens": "2026-07-28T15:00:00Z",
        "overview": "Aprendizaje comunitario en una hora.",
        "presenter_note": "Ana Torres es investigadora comunitaria y guiara una conversacion practica sobre el tema y sus aplicaciones cotidianas.",
        "venue_consumption_note": "Consumo minimo sugerido por el lugar.",
        "venue_consumption_amount": 2000,
        "presenter_questions": [
            {
                "prompt": "Que quieres aprender?",
                "type": "text",
                "required": False,
                "choices": [],
            }
        ],
    }


class FakeEventbriteClient:
    def __init__(self, fail_questions: bool = False, fail_delete: bool = False):
        self.calls: list[str] = []
        self.structured_content: dict | None = None
        self.created_event: dict | None = None
        self.fail_questions = fail_questions
        self.fail_delete = fail_delete

    async def create_event(self, event):
        self.calls.append("event")
        self.created_event = event
        return {"id": "event-1", **event}

    async def update_ticket_buyer_settings(self, event_id, ticket_buyer_settings):
        self.calls.append("ticket_buyer_settings")
        return {
            "event_id": event_id,
            **ticket_buyer_settings,
        }

    async def create_ticket(self, event_id, ticket):
        self.calls.append("ticket")
        return {"id": "ticket-1", **ticket}

    async def create_question(self, event_id, question):
        self.calls.append("question")
        if self.fail_questions:
            raise RuntimeError("question failed")
        return question

    async def create_structured_content(self, event_id, version, content):
        self.calls.append("content")
        self.structured_content = {"version": version, "content": content}
        return content

    async def get_structured_content(self, event_id):
        self.calls.append("content_readback")
        return {"modules": self.structured_content["content"]["modules"]}

    async def get_event(self, event_id, params=None):
        self.calls.append("validate")
        return {"id": event_id, "status": "draft"}

    async def delete_event(self, event_id):
        self.calls.append("delete")
        if self.fail_delete:
            raise RuntimeError("cleanup failed")


def manager(client):
    settings = Settings("org", "organizer-1", "token", "USD")
    return EventInstantiationManager(client, settings)


def test_instantiation_validates_the_fixed_contract() -> None:
    EventInstantiation(**valid_payload())
    bogota_evening = valid_payload()
    bogota_evening["start"] = "2026-07-31T23:30:00Z"
    bogota_evening["end"] = "2026-08-01T00:30:00Z"
    bogota_evening["registration_opens"] = "2026-07-24T23:30:00Z"
    EventInstantiation(**bogota_evening)
    invalid = valid_payload()
    invalid["capacity"] = 2
    with pytest.raises(ValidationError, match="greater than or equal to 3"):
        EventInstantiation(**invalid)
    invalid = valid_payload()
    invalid["capacity"] = 11
    with pytest.raises(ValidationError, match="less than or equal to 10"):
        EventInstantiation(**invalid)
    invalid_name = valid_payload()
    invalid_name["name"] = "x" * 76
    with pytest.raises(ValidationError, match="at most 75 characters"):
        EventInstantiation(**invalid_name)
    invalid_overview = valid_payload()
    invalid_overview["overview"] = "x" * 801
    with pytest.raises(ValidationError, match="at most 800 characters"):
        EventInstantiation(**invalid_overview)
    invalid_presenter_note = valid_payload()
    invalid_presenter_note["presenter_note"] = "x" * 1001
    with pytest.raises(ValidationError, match="at most 1000 characters"):
        EventInstantiation(**invalid_presenter_note)


def test_manager_runs_event_ticket_questions_content_then_validation() -> None:
    client = FakeEventbriteClient()
    result = asyncio.run(manager(client).create_and_validate(EventInstantiation(**valid_payload())))
    assert client.calls == ["event", "ticket_buyer_settings", "ticket", "question", "question", "question", "question", "question", "question", "content", "content_readback", "validate"]
    assert result["validated"] is True
    assert result["ticket"]["quantity_total"] == 3
    assert "summary" not in client.created_event
    assert result["questions"][0]["ticket_classes"] == [{"id": "ticket-1"}]
    assert result["questions"][0]["question"]["html"] == "Que quieres aprender?"
    assert result["questions"][0]["type"] == "text"
    assert result["questions"][1]["type"] == "dropdown"
    assert result["questions"][2]["type"] == "dropdown"
    assert "NNA Primero, Siempre" in result["questions"][3]["question"]["html"]
    assert 'href="' not in result["questions"][3]["question"]["html"]
    assert result["questions"][3]["type"] == "checkbox"
    assert result["questions"][3]["choices"][0]["answer"]["html"] == "Acepto"
    assert "<em>" in result["questions"][3]["question"]["html"]
    assert "tratamiento de mis datos" in result["questions"][4]["question"]["html"]
    assert result["questions"][4]["choices"][0]["answer"]["html"] == "Acepto"
    assert "<em>" in result["questions"][4]["question"]["html"]
    assert "consumo mínimo" in result["questions"][5]["question"]["html"]
    assert result["questions"][5]["choices"][0]["answer"]["html"] == "Acepto"
    assert "<em>" in result["questions"][5]["question"]["html"]
    assert "respondent" not in result["questions"][0]
    assert "respondent" not in result["questions"][1]
    assert "respondent" not in result["questions"][2]
    assert "respondent" not in result["questions"][3]
    assert "respondent" not in result["questions"][4]
    assert "respondent" not in result["questions"][5]
    assert client.structured_content["version"] == 1
    assert client.structured_content["content"]["purpose"] == "listing"
    assert client.structured_content["content"]["publish"] is True
    body = client.structured_content["content"]["modules"][0]["data"]["body"]["text"]
    assert "Aprendizaje comunitario en una hora." in body
    assert "<aside>Ana Torres es investigadora comunitaria y guiara una conversacion practica sobre el tema y sus aplicaciones cotidianas.</aside>" in body
    assert "<strong>" not in body
    assert "<h3>¿Qué es Circle Up Community?</h3><p><em>Un proyecto de investigación, aún en fase de validación, que conecta tecnología, comunidad y academia mediante aprendizaje comunitario. No es una fundación ni una organización sin ánimo de lucro, y por ahora no cuenta con representación legal constituida.</em></p>" in body
    assert (
        "<h3>¿Tiene algún costo?</h3><p><em>Participar es gratuito y Circle Up no recibe dinero por este encuentro. "
        "Algunos espacios pueden tener un consumo mínimo como parte de su acuerdo con el lugar. Si aplica, encontrarás "
        "el valor y las condiciones en la descripción del sitio en Eventbrite. Para encuentros virtuales, no aplica.</em></p>"
        in body
    )
    assert "Consumo minimo sugerido por el lugar." not in body
    assert '<h2><a href="https://app.youform.com/forms/iamr7tnj" style="text-decoration: none;">NNA Primero, Siempre</a></h2>' in body
    assert 'href="https://app.youform.com/forms/iamr7tnj"' in body
    assert "NNA significa niñas, niños y adolescentes." in body
    assert "Si la inscripción es para una persona menor de edad, te pedimos leer este punto con atención." in body
    assert "debe ser diligenciado por el representante legal" in body
    assert "Debe completarse antes de inscribirse en Eventbrite" in body
    assert "podremos anular la inscripción y no será posible realizar el check-in" in body
    assert "Para menores de 14 años, el proceso requiere acompañamiento presencial del representante legal" in body
    assert "no tomamos fotos de menores de edad" in body
    assert "procuramos entornos seguros con acompañamiento responsable" in body
    assert '<b>Contacto:</b> <a href="https://www.circleup.com.co/">circleup.com.co</a>' in body
    assert "Sobre este encuentro" not in body
    assert "Llegada" not in body
    assert "Que llevar" not in body
    assert "Si no puedes asistir" not in body


def test_structured_content_omits_a_repeated_title_in_overview() -> None:
    payload = valid_payload()
    payload["name"] = "Software NASA"
    payload["overview"] = "Software NASA\n\nEste es un proyecto super interesante de matematicas avanzadas."

    body = EventInstantiation(**payload).structured_content_payload()["modules"][0]["data"]["body"]["text"]

    assert body.startswith("<p>Este es un proyecto super interesante de matematicas avanzadas.</p><aside>Ana Torres es investigadora comunitaria")
    assert "</aside><br><br><h2><a href=\"https://app.youform.com/forms/iamr7tnj\" style=\"text-decoration: none;\">NNA Primero, Siempre</a></h2>" in body
    assert body.index("<h2>FAQs</h2>") > body.index("hola@circleup.com.co")
    assert "Software NASA" not in body


def test_manager_deletes_partial_draft_on_failure() -> None:
    client = FakeEventbriteClient(fail_questions=True)
    with pytest.raises(RuntimeError, match="question failed"):
        asyncio.run(manager(client).create_and_validate(EventInstantiation(**valid_payload())))
    assert client.calls == ["event", "ticket_buyer_settings", "ticket", "question", "delete"]


def test_manager_preserves_the_original_error_when_cleanup_fails() -> None:
    client = FakeEventbriteClient(fail_questions=True, fail_delete=True)
    with pytest.raises(RuntimeError, match="question failed"):
        asyncio.run(manager(client).create_and_validate(EventInstantiation(**valid_payload())))
    assert client.calls == ["event", "ticket_buyer_settings", "ticket", "question", "delete"]


