from typing import Any

import httpx


class EventbriteAPIError(Exception):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class EventbriteClient:
    """One place for Eventbrite-specific HTTP calls as the API grows."""

    def __init__(self, client: httpx.AsyncClient, organization_id: str):
        self._client = client
        self._organization_id = organization_id

    async def request(self, method: str, path: str, *, params=None, json=None) -> dict:
        response = await self._client.request(method, path, params=params, json=json)
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise EventbriteAPIError(response.status_code, detail)
        return response.json() if response.content else {}

    async def list_events(self, params: dict) -> dict:
        return await self.request("GET", f"/organizations/{self._organization_id}/events/", params=params)

    async def get_event(self, event_id: str, params: dict | None = None) -> dict:
        return await self.request("GET", f"/events/{event_id}/", params=params)

    async def list_venues(self, params: dict) -> dict:
        return await self.request("GET", f"/organizations/{self._organization_id}/venues/", params=params)

    async def get_venue(self, venue_id: str) -> dict:
        return await self.request("GET", f"/venues/{venue_id}/")

    async def list_attendees(self, event_id: str, params: dict) -> dict:
        return await self.request("GET", f"/events/{event_id}/attendees/", params=params)

    async def get_attendee(self, event_id: str, attendee_id: str) -> dict:
        return await self.request("GET", f"/events/{event_id}/attendees/{attendee_id}/")

    async def create_event(self, event: dict) -> dict:
        return await self.request("POST", f"/organizations/{self._organization_id}/events/", json={"event": event})

    async def update_event(self, event_id: str, event: dict) -> dict:
        return await self.request("POST", f"/events/{event_id}/", json={"event": event})

    async def create_venue(self, venue: dict) -> dict:
        return await self.request("POST", f"/organizations/{self._organization_id}/venues/", json={"venue": venue})

    async def update_venue(self, venue_id: str, venue: dict) -> dict:
        return await self.request("POST", f"/venues/{venue_id}/", json={"venue": venue})

    async def create_free_ticket(self, event_id: str, name: str, quantity: int) -> dict:
        return await self.request(
            "POST", f"/events/{event_id}/ticket_classes/",
            json={"ticket_class": {"name": name, "quantity_total": quantity, "free": True}},
        )

    async def create_ticket(self, event_id: str, ticket: dict) -> dict:
        return await self.request("POST", f"/events/{event_id}/ticket_classes/", json={"ticket_class": ticket})

    async def create_question(self, event_id: str, question: dict) -> dict:
        return await self.request("POST", f"/events/{event_id}/questions/", json={"question": question})

    async def create_structured_content(self, event_id: str, version: int, content: dict) -> dict:
        return await self.request("POST", f"/events/{event_id}/structured_content/{version}/", json=content)

    async def get_structured_content(self, event_id: str) -> dict:
        return await self.request("GET", f"/events/{event_id}/structured_content/", params={"purpose": "listing"})

    async def image_upload_instructions(self) -> dict:
        return await self.request("GET", "/media/upload/", params={"type": "image-event-logo"})

    async def complete_image_upload(self, upload_token: str, crop_mask: dict) -> dict:
        return await self.request("POST", "/media/upload/", json={"upload_token": upload_token, "crop_mask": crop_mask})

    async def publish_event(self, event_id: str) -> dict:
        return await self.request("POST", f"/events/{event_id}/publish/")

    async def delete_event(self, event_id: str) -> None:
        await self.request("DELETE", f"/events/{event_id}/")
