from __future__ import annotations

import asyncio

import httpx

from app.client import NRS360Client
from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=httpx.Timeout(settings.timeout_seconds),
    ) as http_client:
        client = NRS360Client(http_client, settings.username, settings.api_password)
        response = await client.get_account()
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
