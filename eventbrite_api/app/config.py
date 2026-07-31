import json
import os
from dataclasses import dataclass
from pathlib import Path

import boto3


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = Path(__file__).resolve().parents[1]
CIRCLE_UP_ORGANIZATION_ID = "2998243227926"
CIRCLE_UP_ORGANIZER_ID = "121240412403"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs without overwriting exported variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    organization_id: str
    organizer_id: str
    private_token: str
    default_currency: str
    api_auth_token: str | None = None
    api_base_url: str = "https://www.eventbriteapi.com/v3"


def load_secret(secret_id: str) -> dict[str, str]:
    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    payload = response.get("SecretString")
    if not payload:
        raise RuntimeError(f"Secret {secret_id} does not contain SecretString.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"Secret {secret_id} must contain a JSON object.")
    return {str(key): str(value) for key, value in data.items() if value is not None}


def get_settings() -> Settings:
    load_env_file(PROJECT_ROOT / ".env.local")
    load_env_file(API_ROOT / ".env")
    secret_values: dict[str, str] = {}
    secret_id = os.getenv("EVENTBRITE_SECRET_ID")
    if secret_id:
        secret_values = load_secret(secret_id)
    configured_organization_id = secret_values.get("EVENTBRITE_ORGANIZATION_ID") or os.getenv("EVENTBRITE_ORGANIZATION_ID")
    private_token = secret_values.get("EVENTBRITE_PRIVATE_TOKEN") or os.getenv("EVENTBRITE_PRIVATE_TOKEN")
    api_auth_token = secret_values.get("EVENTBRITE_API_AUTH_TOKEN") or os.getenv("EVENTBRITE_API_AUTH_TOKEN")
    if configured_organization_id and configured_organization_id != CIRCLE_UP_ORGANIZATION_ID:
        raise RuntimeError("EVENTBRITE_ORGANIZATION_ID must match the fixed Circle Up organization.")
    if not private_token:
        raise RuntimeError(
            "Set EVENTBRITE_PRIVATE_TOKEN in Secrets Manager, eventbrite_api/.env or in the root .env.local."
        )
    return Settings(
        organization_id=CIRCLE_UP_ORGANIZATION_ID,
        organizer_id=CIRCLE_UP_ORGANIZER_ID,
        private_token=private_token,
        default_currency=os.getenv("EVENTBRITE_DEFAULT_CURRENCY", "USD").upper(),
        api_auth_token=api_auth_token,
    )
