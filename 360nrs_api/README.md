# 360nrs API

Local FastAPI wrapper and test harness for the 360nrs SMS API.

This folder is meant for two things:

- operating the 360nrs API through a small local HTTP service
- running controlled account and SMS tests before wiring it into other systems

## Implemented endpoints

- `GET /health`: local health check
- `GET /account`: validates credentials and IP whitelist against 360nrs
- `POST /sms`: sends an SMS campaign
- `GET /sms/{message_id}`: fetches a previously accepted SMS by id

## Local setup

```powershell
cd 360nrs_api
uv sync
uv run uvicorn app.main:app --reload --port 8010
```

The service loads environment variables in this order:

1. exported variables
2. root `../.env.local`
3. service `./.env.local`
4. service `./.env`

## Required configuration

```powershell
$env:NRS360_USERNAME = "circleupcomm"
$env:NRS360_API_PASSWORD = "your-api-password"
$env:NRS360_DASHBOARD_HOST = "https://dashboard.360nrs.com"
```

Optional variables:

```powershell
$env:NRS360_API_AUTH_TOKEN = "internal-wrapper-token"
$env:NRS360_TIMEOUT_SECONDS = "30"
$env:NRS360_NOTIFICATION_URL = "https://yourapp.example/webhooks/360nrs"
$env:NRS360_TEST_FROM = "TEST"
$env:NRS360_TEST_TO = "573194477860"
$env:NRS360_TEST_MESSAGE = "Prueba Circle Up 360nrs"
```

## Example requests

Check account access:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8010/account"
```

Send a test SMS:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8010/sms" -ContentType "application/json" -Body '{
  "to": ["573194477860"],
  "from": "TEST",
  "message": "Prueba Circle Up 360nrs"
}'
```

## Direct scripts

```powershell
uv run python scripts/check_account.py
uv run python scripts/send_test_sms.py
```

## Tests

Mocked tests only:

```powershell
uv run pytest
```

Real account check:

```powershell
$env:NRS360_LIVE_TEST = "1"
uv run pytest tests/test_live_api.py -m live
```

Real SMS send:

```powershell
$env:NRS360_LIVE_TEST = "1"
$env:NRS360_LIVE_SEND_SMS = "1"
uv run pytest tests/test_live_api.py -m live
```

## Notes

- 360nrs uses `Basic` authentication built from `base64(username:apiPassword)`.
- `https://dashboard.360nrs.com` behaved like the real API host during live validation; `app.360nrs.com` returned a plain `404`.
- The caller IP must be whitelisted by 360nrs before real requests succeed.
- The `apiPassword` is separate from the dashboard login password.
