from app.client import EventbriteClient
from app.config import Settings
from app.schemas import EventInstantiation


class EventInstantiationManager:
    """Runs the fixed Circle Up draft sequence in the documented order."""

    def __init__(self, client: EventbriteClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def create_and_validate(self, draft: EventInstantiation) -> dict:
        event = draft.event_payload(self.settings.organizer_id, self.settings.default_currency)
        created = await self.client.create_event(event)
        event_id = str(created["id"])
        try:
            ticket = await self.client.create_ticket(event_id, draft.ticket_payload())
            ticket_id = str(ticket["id"])
            questions = []
            for question in draft.question_payloads():
                request = dict(question)
                # Eventbrite's Question contract expects ticket-class objects,
                # not a list of bare IDs.
                request["ticket_classes"] = [{"id": ticket_id}]
                questions.append(await self.client.create_question(event_id, request))
            # The version belongs in the URL path. Eventbrite's documented body
            # contains only purpose, publish and the complete module list.
            content = draft.structured_content_payload()
            version_number = content.pop("version_number")
            await self.client.create_structured_content(event_id, version_number, content)
            persisted_content = await self.client.get_structured_content(event_id)
            if content["modules"] and not persisted_content.get("modules"):
                raise RuntimeError("Eventbrite did not persist the listing content.")
            validated = await self.client.get_event(
                event_id, {"expand": "venue,ticket_classes,ticket_availability"}
            )
            return {"event": validated, "ticket": ticket, "questions": questions, "validated": True}
        except Exception:
            # A partial draft is not a valid Circle Up event. Keep the original error.
            try:
                await self.client.delete_event(event_id)
            except Exception:
                # Cleanup is best-effort. Do not hide the failure that made the
                # draft invalid in the first place.
                pass
            raise
