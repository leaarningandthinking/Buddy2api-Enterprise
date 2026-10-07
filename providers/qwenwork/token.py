"""QwenWork device-token refresh. Isolated from WorkBuddy refresh."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from providers.qwenwork.constants import (
    BUILD,
    GATEWAY,
    IDE_VERSION,
    REFRESH_PATH,
    RELEASE_VERSION,
    USER_AGENT,
)
from providers.qwenwork.store import iso_to_ms, write_refreshed_auth


class QwenWorkAuthError(RuntimeError):
    pass


def openapi_headers(request_id: str = "") -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "X-Request-Id": request_id or f"buddy2api-{int(time.time() * 1000)}",
        "X-QwenWork-Version": IDE_VERSION,
        "X-QwenWork-Release-Version": RELEASE_VERSION,
        "X-QwenWork-Build": BUILD,
        "X-QwenWork-Platform": "win32",
        "X-QwenWork-Arch": "x64",
        "X-QwenWork-Channel": "stable",
        "Content-Type": "application/json",
    }


def is_token_expired(account: dict, skew_ms: int = 300_000) -> bool:
    expires_at = int(account.get("expires_at") or 0)
    if expires_at <= 0:
        return False
    return time.time() * 1000 >= expires_at - skew_ms


async def refresh_account(account: dict) -> dict:
    import database as db

    refresh = str(account.get("refresh_token") or "")
    if not refresh:
        raise QwenWorkAuthError("QwenWork account has no refresh_token")
    headers = openapi_headers()
    access = str(account.get("access_token") or "")
    if access:
        headers["Authorization"] = f"Bearer {access}"
    body = {"refresh_token": refresh, "target": "c"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{GATEWAY}{REFRESH_PATH}", headers=headers, json=body)
    if response.status_code >= 400:
        raise QwenWorkAuthError(f"deviceToken refresh failed: HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise QwenWorkAuthError("deviceToken refresh returned non-JSON") from exc
    token = data.get("device_token") or data.get("token") or ""
    new_refresh = data.get("refresh_token") or refresh
    if not token:
        raise QwenWorkAuthError("refresh response missing device_token")
    expires_at = iso_to_ms(data.get("expires_at"))
    if not expires_at and isinstance(data.get("expires_in"), (int, float)):
        expires_at = int((time.time() + float(data["expires_in"])) * 1000)
    refresh_expires_at = iso_to_ms(data.get("refresh_token_expires_at"))
    if not refresh_expires_at and isinstance(data.get("refresh_token_expires_in"), (int, float)):
        refresh_expires_at = int((time.time() + float(data["refresh_token_expires_in"])) * 1000)
    patch = {
        "access_token": token,
        "refresh_token": new_refresh,
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
        "status": "active",
    }
    db.update_account(account["id"], patch)
    extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
    auth_path = extra.get("auth_path")
    if auth_path:
        try:
            write_refreshed_auth(Path(auth_path), patch)
        except Exception:
            pass
    fresh = db.get_account(account["id"])
    if not fresh:
        raise QwenWorkAuthError("account disappeared after refresh")
    return fresh
