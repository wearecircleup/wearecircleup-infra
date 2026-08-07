from __future__ import annotations

import asyncio
import os

import httpx

from app.client import NRS360Client
from app.config import get_settings
from app.schemas import SMSSendRequest


async def main() -> None:
    settings = get_settings()
    payload = SMSSendRequest(
        to=[os.getenv("NRS360_TEST_TO", "573194477860")],
        **{
            "from": os.getenv("NRS360_TEST_FROM", "TEST"),
            "message": os.getenv("NRS360_TEST_MESSAGE", "Prueba Circle Up 360nrs"),
        },
    )
    async with httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=httpx.Timeout(settings.timeout_seconds),
    ) as http_client:
        client = NRS360Client(http_client, settings.username, settings.api_password)
        response = await client.send_sms(payload.api_payload(settings.default_notification_url))
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
