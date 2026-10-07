"""WeChat OAuth helpers for QClaw. Official 0.2.36.629 uses 4050/4026/4055."""

from __future__ import annotations

from urllib.parse import parse_qs, quote, urlparse

from providers.qclaw.constants import WX_APP_ID, WX_LOGIN_REDIRECT, WX_QRCONNECT
from providers.qclaw.jprx import create_api_key, wx_login, wx_login_state
from providers.qclaw.store import session_to_account


def login_url(state: str) -> str:
    redirect = quote(WX_LOGIN_REDIRECT, safe="")
    return (
        f"{WX_QRCONNECT}?appid={WX_APP_ID}"
        f"&redirect_uri={redirect}"
        f"&response_type=code&scope=snsapi_login"
        f"&state={quote(state, safe='')}#wechat_redirect"
    )


def parse_callback(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty WeChat callback")
    if "://" not in text and "code=" not in text:
        return {"code": text, "state": ""}
    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    code = (query.get("code") or [""])[0] or text
    state = (query.get("state") or [""])[0]
    return {"code": code, "state": state}


async def start_login(guid: str) -> dict:
    account = {"uid": "1", "refresh_token": "", "extra": {"guid": guid or "1"}}
    data = await wx_login_state(account, {"guid": guid or "1"})
    state = str(data.get("state") or "")
    if not state:
        raise ValueError("jprx 4050 did not return state")
    return {"state": state, "url": login_url(state), "guid": guid}


async def complete_login(guid: str, code: str, state: str) -> dict:
    account = {"uid": "1", "refresh_token": "", "extra": {"guid": guid or "1"}}
    data = await wx_login(account, {"guid": guid, "code": code, "state": state})
    jwt = str(data.get("token") or "")
    channel_token = str(data.get("openclaw_channel_token") or "")
    user = data.get("user_info") if isinstance(data.get("user_info"), dict) else {}
    user_id = str(user.get("userId") or user.get("user_id") or "")
    session_account = {
        "uid": user_id,
        "refresh_token": jwt,
        "extra": {"guid": guid, "openclaw_channel_token": channel_token},
    }
    key_info = {}
    if jwt:
        key_info = await create_api_key(session_account)
    sk = str(key_info.get("key") or "")
    session = {
        "uid": user_id,
        "nickname": user.get("nickname") or "",
        "access_token": sk,
        "refresh_token": jwt,
        "guid": guid,
        "user": user,
        "openclaw_channel_token": channel_token,
        "source": "oauth",
    }
    parsed = session_to_account(session)
    if not parsed["access_token"]:
        raise ValueError("login succeeded but createApiKey (4055) returned no sk key")
    return parsed
