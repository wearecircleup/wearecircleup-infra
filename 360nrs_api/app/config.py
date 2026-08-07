from __future__ import annotations

import os
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
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
    username: str
    api_password: str
    dashboard_host: str
    api_base_url: str
    timeout_seconds: float = 30.0
    api_auth_token: str | None = None
    default_notification_url: str | None = None

    @property
    def basic_token(self) -> str:
        pair = f"{self.username}:{self.api_password}"
        return b64encode(pair.encode("utf-8")).decode("ascii")


def _normalized_host(raw_host: str) -> str:
    host = raw_host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def get_settings() -> Settings:
    load_env_file(PROJECT_ROOT / ".env.local")
    load_env_file(API_ROOT / ".env.local")
    load_env_file(API_ROOT / ".env")

    username = (os.getenv("NRS360_USERNAME") or "").strip()
    api_password = os.getenv("NRS360_API_PASSWORD") or ""
    dashboard_host = _normalized_host(os.getenv("NRS360_DASHBOARD_HOST", "https://dashboard.360nrs.com"))
    timeout_seconds = float(os.getenv("NRS360_TIMEOUT_SECONDS", "30"))
    api_auth_token = (os.getenv("NRS360_API_AUTH_TOKEN") or "").strip() or None
    default_notification_url = (os.getenv("NRS360_NOTIFICATION_URL") or "").strip() or None

    if not username:
        raise RuntimeError("Set NRS360_USERNAME in the environment or .env.local.")
    if not api_password:
        raise RuntimeError("Set NRS360_API_PASSWORD in the environment or .env.local.")

    return Settings(
        username=username,
        api_password=api_password,
        dashboard_host=dashboard_host,
        api_base_url=f"{dashboard_host}/api/rest",
        timeout_seconds=timeout_seconds,
        api_auth_token=api_auth_token,
        default_notification_url=default_notification_url,
    )
