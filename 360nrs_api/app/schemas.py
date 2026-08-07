from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_recipient(value: str) -> str:
    cleaned = "".join(char for char in value.strip() if char.isdigit() or char == "+")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    return cleaned


class SMSRecipientResult(BaseModel):
    accepted: bool
    to: str
    id: str | None = None
    parts: int | None = None
    scheduledAt: str | None = None
    expiresAt: str | None = None
    error: dict | None = None


class SMSSendResponse(BaseModel):
    campaignId: int | None = None
    sendingId: int | None = None
    result: list[SMSRecipientResult] = Field(default_factory=list)


class SMSSendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    to: list[str] = Field(min_length=1)
    from_: str = Field(alias="from", min_length=1, max_length=16)
    message: str = Field(min_length=1, max_length=1600)
    notificationUrl: str | None = None
    scheduleDate: datetime | None = None
    expirationDate: datetime | None = None
    campaignName: str | None = Field(default=None, max_length=100)
    encoding: Literal["AUTO", "GSM7", "UCS2"] | None = None
    parts: int | None = Field(default=None, ge=1, le=8)
    flash: bool | None = None
    splitParts: bool | None = None
    certified: bool | None = None
    tags: dict[str, str] | None = None

    @field_validator("to")
    @classmethod
    def validate_to(cls, recipients: list[str]) -> list[str]:
        normalized = [normalize_recipient(recipient) for recipient in recipients]
        normalized = [recipient for recipient in normalized if recipient]
        if not normalized:
            raise ValueError("Provide at least one valid recipient.")
        return normalized

    @field_validator("from_")
    @classmethod
    def validate_from(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("from is required.")
        return cleaned

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message is required.")
        return cleaned

    @model_validator(mode="after")
    def validate_dates(self) -> "SMSSendRequest":
        if self.scheduleDate and self.expirationDate and self.expirationDate <= self.scheduleDate:
            raise ValueError("expirationDate must be after scheduleDate.")
        return self

    def api_payload(self, default_notification_url: str | None = None) -> dict:
        payload = {
            "to": self.to,
            "from": self.from_,
            "message": self.message,
        }
        for field in (
            "campaignName",
            "encoding",
            "parts",
            "flash",
            "splitParts",
            "certified",
            "tags",
        ):
            value = getattr(self, field)
            if value is not None:
                payload[field] = value
        if self.notificationUrl or default_notification_url:
            payload["notificationUrl"] = self.notificationUrl or default_notification_url
        if self.scheduleDate is not None:
            payload["scheduleDate"] = self.scheduleDate.isoformat()
        if self.expirationDate is not None:
            payload["expirationDate"] = self.expirationDate.isoformat()
        return payload
