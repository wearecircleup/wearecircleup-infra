from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.client import NRS360APIError, NRS360Client
from app.config import Settings, get_settings
from app.schemas import SMSSendRequest


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=httpx.Timeout(settings.timeout_seconds),
    ) as http_client:
        app.state.nrs360 = NRS360Client(http_client, settings.username, settings.api_password)
        app.state.settings = settings
        yield


app = FastAPI(
    title="360nrs API",
    version="1.0.0",
    description="Internal wrapper for account validation and SMS sends through 360nrs.",
    lifespan=lifespan,
)


def get_client(request: Request) -> NRS360Client:
    return request.app.state.nrs360


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return await call_next(request)
    if settings.api_auth_token:
        authorization = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.api_auth_token}"
        if authorization != expected:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.exception_handler(NRS360APIError)
async def nrs360_error_handler(request: Request, exc: NRS360APIError) -> JSONResponse:
    logger.exception(
        "360nrs API error on %s %s: status=%s detail=%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/account", tags=["account"])
async def get_account(client: NRS360Client = Depends(get_client)) -> dict:
    return await client.get_account()


@app.post("/sms", status_code=status.HTTP_202_ACCEPTED, tags=["sms"])
async def send_sms(
    payload: SMSSendRequest,
    client: NRS360Client = Depends(get_client),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    response = await client.send_sms(payload.api_payload(settings.default_notification_url))
    accepted = [item for item in response.get("result", []) if item.get("accepted")]
    rejected = [item for item in response.get("result", []) if not item.get("accepted")]
    status_code = status.HTTP_202_ACCEPTED if accepted and not rejected else status.HTTP_207_MULTI_STATUS
    return JSONResponse(
        status_code=status_code,
        content=response,
    )


@app.get("/sms/{message_id}", tags=["sms"])
async def get_sms(message_id: str, client: NRS360Client = Depends(get_client)) -> dict:
    cleaned = message_id.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="message_id is required.")
    return await client.get_sms(cleaned)
