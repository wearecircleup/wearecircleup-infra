from datetime import datetime, timedelta, timezone
from typing import Literal
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator


class EventCreate(BaseModel):
    name: str = Field(max_length=75, examples=["Taller de prueba Circle Up"])
    start: datetime = Field(examples=["2026-07-27T10:00:00-05:00"])
    end: datetime = Field(examples=["2026-07-27T11:00:00-05:00"])
    timezone: str = Field(default="America/Bogota", examples=["America/Bogota"])
    currency: str | None = Field(default=None, min_length=3, max_length=3, examples=["USD"])
    description: str | None = Field(default=None, examples=["Una prueba creada desde la API de Circle Up."])
    online_event: bool = True
    listed: bool = True
    shareable: bool = True
    ticket_name: str = Field(default="Entrada general")
    ticket_quantity: int = Field(default=100, gt=0)
    publish: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "EventCreate":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name is required.")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must include a UTC offset, for example -05:00.")
        if self.end <= self.start:
            raise ValueError("end must be after start.")
        return self

    def eventbrite_payload(self, default_currency: str) -> dict:
        event = {
            "name": {"html": self.name},
            "start": {"timezone": self.timezone, "utc": self.start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "end": {"timezone": self.timezone, "utc": self.end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "currency": (self.currency or default_currency).upper(),
            "online_event": self.online_event,
            "listed": self.listed,
            "shareable": self.shareable,
        }
        if self.description:
            event["description"] = {"html": self.description}
        return event


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=75)
    summary: str | None = Field(default=None, max_length=140)
    start: datetime | None = None
    end: datetime | None = None
    timezone: str | None = None
    online_event: bool | None = None
    listed: bool | None = None
    shareable: bool | None = None

    def eventbrite_payload(self) -> dict:
        event: dict = {}
        if self.name is not None:
            event["name"] = {"html": self.name}
        if self.summary is not None:
            event["summary"] = self.summary
        for field in ("start", "end"):
            value = getattr(self, field)
            if value is not None:
                if value.tzinfo is None:
                    raise ValueError(f"{field} must include a UTC offset.")
                event[field] = {"timezone": self.timezone or "America/Bogota", "utc": value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for field in ("online_event", "listed", "shareable"):
            value = getattr(self, field)
            if value is not None:
                event[field] = value
        return event


class VenueBase(BaseModel):
    name: str = Field(examples=["Casa de la Cultura"])
    address_1: str | None = Field(default=None, examples=["Calle 10 # 20-30"])
    address_2: str | None = Field(default=None, examples=["Piso 2"])
    city: str | None = Field(default=None, examples=["Bogota"])
    region: str | None = Field(default=None, examples=["Cundinamarca"])
    postal_code: str | None = Field(default=None, examples=["110111"])
    country: str = Field(default="CO", min_length=2, max_length=2, examples=["CO"])
    latitude: float | None = Field(default=None, examples=[4.711])
    longitude: float | None = Field(default=None, examples=[-74.0721])


class VenueCreate(VenueBase):
    def eventbrite_payload(self) -> dict:
        venue = {
            "name": self.name,
            "address": {
                "country": self.country.upper(),
            },
        }
        if self.address_1 is not None:
            venue["address"]["address_1"] = self.address_1
        if self.address_2 is not None:
            venue["address"]["address_2"] = self.address_2
        if self.city is not None:
            venue["address"]["city"] = self.city
        if self.region is not None:
            venue["address"]["region"] = self.region
        if self.postal_code is not None:
            venue["address"]["postal_code"] = self.postal_code
        if self.latitude is not None:
            venue["address"]["latitude"] = self.latitude
        if self.longitude is not None:
            venue["address"]["longitude"] = self.longitude
        return venue


class VenueUpdate(BaseModel):
    name: str | None = None
    address_1: str | None = None
    address_2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    latitude: float | None = None
    longitude: float | None = None

    def eventbrite_payload(self) -> dict:
        venue: dict = {}
        if self.name is not None:
            venue["name"] = self.name
        address: dict = {}
        for field in ("address_1", "address_2", "city", "region", "postal_code", "latitude", "longitude"):
            value = getattr(self, field)
            if value is not None:
                address[field] = value
        if self.country is not None:
            address["country"] = self.country.upper()
        if address:
            venue["address"] = address
        return venue


class ImageUploadCompletion(BaseModel):
    """JSON returned by the Studio after the signed binary upload succeeds."""

    upload_token: str = Field(min_length=1)
    crop_mask: dict


DEFAULT_FAQS = (
    (
        "¿Qué es Circle Up Community?",
        "Un proyecto de investigación que conecta tecnología, comunidad y academia mediante aprendizaje comunitario.",
    ),
    (
        "¿Cómo es el encuentro?",
        "Dura hasta una hora, reúne de 3 a 10 personas y se adapta a cualquier espacio. ¿Conoces uno? Cuéntanos y lo gestionamos.",
    ),
    (
        "¿Tiene algún costo?",
        "Participar es gratuito y Circle Up no recibe dinero por este encuentro. Algunos espacios pueden tener un consumo mínimo como parte de su acuerdo con el lugar. Si aplica, encontrarás el valor y las condiciones en la descripción del sitio en Eventbrite. Para encuentros virtuales, no aplica.",
    ),
    (
        "¿Cómo usamos tus datos?",
        "Al inscribirte, autorizas el tratamiento de los datos que proporcionas, conforme a la Ley 1581 de 2012, únicamente para gestionar tu inscripción, registrar tu asistencia, enviarte información y notificaciones relacionadas con el evento, y apoyar la actividad de investigación. Solicitamos solo la información necesaria y no compartiremos tus datos personales con terceros.",
    ),
)
CONTACT_URL = "https://www.circleup.com.co/"
CONTACT_EMAIL = "hola@circleup.com.co"
TIMEZONE_FALLBACKS = {
    "America/Bogota": timezone(timedelta(hours=-5)),
}
EDUCATION_LEVEL_QUESTION = "¿Cuál es tu nivel educativo actual?"
EDUCATION_LEVEL_CHOICES = [
    "Primaria",
    "Secundaria o bachillerato",
    "Tecnico o tecnologo",
    "Universitario",
    "Especializacion",
    "Posgrado",
    "Doctorado",
    "Otro",
]
PHONE_QUESTION = "¿Quieres recibir actualizaciones por SMS? Déjanos tu número. Lo usaremos solo para este evento."
AGE_RANGE_QUESTION = "¿Cuál es tu rango de edad?"
AGE_RANGE_CHOICES = [
    "14 a 17 años",
    "18 a 24 años",
    "25 a 34 años",
    "35 a 44 años",
    "45 a 54 años",
    "55 años o más",
]
MINOR_AUTHORIZATION_QUESTION = (
    "Si eres menor de edad, te enviaremos una autorización para tu acudiente. "
    "Debe estar firmada digitalmente para tu check-in."
)
MULTIPLE_CHOICE_TYPES = {"radio", "dropdown", "checkbox"}


class PresenterQuestion(BaseModel):
    prompt: str = Field(min_length=1)
    type: Literal["text", "radio", "dropdown", "checkbox"]
    required: bool = False
    choices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_choices(self) -> "PresenterQuestion":
        self.prompt = self.prompt.strip()
        self.choices = [choice.strip() for choice in self.choices if choice.strip()]
        if not self.prompt:
            raise ValueError("Presenter question prompt cannot be empty.")
        if self.type in MULTIPLE_CHOICE_TYPES and len(self.choices) < 2:
            raise ValueError("Choice-based presenter questions require at least two options.")
        if self.type == "text" and self.choices:
            raise ValueError("Text presenter questions cannot define options.")
        return self

    def eventbrite_payload(self) -> dict:
        payload = {
            "question": {"html": self.prompt},
            "respondent": "attendee",
            "type": self.type,
            "required": self.required,
            "choices": [],
            "ticket_classes": [],
        }
        if self.type in MULTIPLE_CHOICE_TYPES:
            payload["choices"] = [{"answer": {"html": choice}} for choice in self.choices]
        return payload


class EventInstantiation(BaseModel):
    name: str = Field(min_length=1, max_length=75)
    start: datetime
    end: datetime
    timezone: str = Field(default="America/Bogota")
    online_event: bool
    venue_id: str | None = None
    capacity: int = Field(ge=3, le=10)
    ticket_name: str = Field(default="Entrada General", min_length=1)
    registration_opens: datetime
    overview: str = Field(min_length=1, max_length=800)
    presenter_note: str = Field(default="", max_length=1000)
    venue_consumption_note: str = ""
    venue_consumption_amount: int = Field(default=0, ge=0)
    presenter_questions: list[PresenterQuestion] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_circle_up_contract(self) -> "EventInstantiation":
        self.name = self.name.strip()
        self.ticket_name = self.ticket_name.strip()
        self.overview = self.overview.strip()
        self.presenter_note = self.presenter_note.strip()
        self.venue_consumption_note = self.venue_consumption_note.strip()
        if not self.name:
            raise ValueError("name is required.")
        if not self.ticket_name:
            raise ValueError("ticket_name is required.")
        if not self.overview:
            raise ValueError("overview is required.")
        if self.start.tzinfo is None or self.end.tzinfo is None or self.registration_opens.tzinfo is None:
            raise ValueError("Event and registration timestamps must include a UTC offset.")
        event_timezone = self._event_timezone()
        local_start = self.start.astimezone(event_timezone)
        local_end = self.end.astimezone(event_timezone)
        if self.end - self.start != timedelta(hours=1) or local_start.date() != local_end.date():
            raise ValueError("Events must last exactly one hour and end on the same day.")
        if not self.registration_opens < self.start:
            raise ValueError("Ticket sales must open before the event start.")
        if self.online_event is False and not self.venue_id:
            raise ValueError("In-person events require an existing venue_id.")
        if self.online_event is True and self.venue_id:
            raise ValueError("Online events cannot include venue_id.")
        return self

    def _event_timezone(self):
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            fallback = TIMEZONE_FALLBACKS.get(self.timezone)
            if fallback is not None:
                return fallback
            raise ValueError("timezone must be a valid IANA timezone, for example America/Bogota.")

    def _utc(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def event_payload(self, organizer_id: str, currency: str) -> dict:
        event = {
            "name": {"html": self.name},
            "start": {"utc": self._utc(self.start), "timezone": self.timezone},
            "end": {"utc": self._utc(self.end), "timezone": self.timezone},
            "currency": currency,
            "organizer_id": organizer_id,
            "online_event": self.online_event,
            "capacity": self.capacity,
        }
        if not self.online_event:
            event["venue_id"] = str(self.venue_id).strip()
        return event

    def ticket_payload(self) -> dict:
        return {
            "name": self.ticket_name,
            "free": True,
            "quantity_total": self.capacity,
            "maximum_quantity": 1,
            "sales_start": self._utc(self.registration_opens),
            "sales_end": self._utc(self.start),
        }

    def question_payloads(self) -> list[dict]:
        questions = [question.eventbrite_payload() for question in self.presenter_questions]
        questions.extend([
            {
                "question": {"html": EDUCATION_LEVEL_QUESTION},
                "respondent": "attendee",
                "type": "dropdown",
                "required": True,
                "choices": [{"answer": {"html": choice}} for choice in EDUCATION_LEVEL_CHOICES],
                "ticket_classes": [],
            },
            {
                "question": {"html": AGE_RANGE_QUESTION},
                "respondent": "attendee",
                "type": "dropdown",
                "required": True,
                "choices": [{"answer": {"html": choice}} for choice in AGE_RANGE_CHOICES],
                "ticket_classes": [],
            },
            {
                "question": {
                    "html": PHONE_QUESTION,
                },
                "respondent": "attendee",
                "type": "text",
                "required": False,
                "choices": [],
                "ticket_classes": [],
            },
            {
                "question": {"html": MINOR_AUTHORIZATION_QUESTION},
                "respondent": "attendee",
                "type": "checkbox",
                "required": True,
                "choices": [{"answer": {"html": "Entiendo"}}],
                "ticket_classes": [],
            },
            {
                "question": {
                    "html": "¿Aceptas la información del evento y las reglas de convivencia del lugar?<br><br><em>Acepto el tratamiento de mis datos, según la Ley 1581 de 2012, solo para mi inscripción y mensajes de este evento. No se comparten con terceros.</em>",
                },
                "respondent": "attendee",
                "type": "checkbox",
                "required": True,
                "choices": [{"answer": {"html": "Acepto"}}],
                "ticket_classes": [],
            },
        ])
        if not self.online_event and self.venue_consumption_amount:
            amount = f"${self.venue_consumption_amount:,.0f}".replace(",", ".")
            questions.append(
                {
                    "question": {
                        "html": f"Entiendo que el lugar anfitrión solicita un consumo mínimo de {amount} COP para consumo propio, cobrado por el lugar y no por Circle Up Community?",
                    },
                    "respondent": "attendee",
                    "type": "checkbox",
                    "required": True,
                    "choices": [{"answer": {"html": "Entiendo"}}],
                    "ticket_classes": [],
                }
            )
        return questions

    def structured_content_payload(self) -> dict:
        overview_blocks = [block.strip() for block in re.split(r"\n\s*\n", self.overview) if block.strip()]
        if overview_blocks and overview_blocks[0].casefold() == self.name.casefold():
            overview_blocks = overview_blocks[1:]
        overview_parts = [f"<p>{block}</p>" for block in overview_blocks]
        if self.presenter_note:
            overview_parts.append(f"<aside>{self.presenter_note}</aside>")
        overview_html = "".join(overview_parts)
        faq_html = []
        for question, answer in DEFAULT_FAQS:
            faq_html.append(f"<h3>{question}</h3><p><em>{answer}</em></p>")
        body_parts = []
        if overview_html:
            body_parts.append(overview_html)
            body_parts.append("<br><br>")
        body_parts.append("<h2>FAQs</h2>")
        body_parts.append("".join(faq_html))
        body_parts.append(
            f'<p><b>Contacto:</b> <a href="{CONTACT_URL}">circleup.com.co</a> | <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>'
        )
        return {
            "version_number": 1,
            "purpose": "listing",
            "publish": True,
            "modules": [
                {
                    "type": "text",
                    "data": {
                        "body": {
                            "type": "text",
                            "alignment": "left",
                            "text": "".join(body_parts),
                        }
                    },
                }
            ],
        }
