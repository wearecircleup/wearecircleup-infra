from __future__ import annotations

import base64
from typing import Any

import httpx


class NRS360APIError(Exception):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class NRS360Client:
    def __init__(self, client: httpx.AsyncClient, username: str, api_password: str):
        token = base64.b64encode(f"{username}:{api_password}".encode("utf-8")).decode("ascii")
        client.headers.update(
            {
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self._client = client

    async def request(self, method: str, path: str, *, params=None, json=None) -> dict:
        response = await self._client.request(method, path, params=params, json=json)
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise NRS360APIError(response.status_code, detail)
        return response.json() if response.content else {}

    async def get_account(self) -> dict:
        return await self.request("GET", "/account")

    async def send_sms(self, payload: dict) -> dict:
        return await self.request("POST", "/sms", json=payload)

    async def get_sms(self, message_id: str) -> dict:
        return await self.request("GET", f"/sms/{message_id}")
