"""QClaw request signing. JPrx-Ctx is MD5; aizone requires a conversation request id."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid

from providers.qclaw.constants import (
    CLIENT_VERSION,
    JPRX_RND_CHARS,
    JPRX_RND_LEN,
    JPRX_SIGNATURE_KEY,
)


def random_rnd(length: int = JPRX_RND_LEN) -> str:
    return "".join(secrets.choice(JPRX_RND_CHARS) for _ in range(length))


def jprx_ctx(body: str, gid: str, *, rnd: str | None = None, date: str | None = None) -> str:
    """Official 0.2.36.629 JPrx-Ctx: rnd / date / gid / md5(body+key+rnd+date+gid)."""
    token_gid = gid or "1"
    nonce = rnd if rnd is not None else random_rnd()
    ts = date if date is not None else str(int(time.time()))
    material = f"{body}{JPRX_SIGNATURE_KEY}{nonce}{ts}{token_gid}"
    digest = hashlib.md5(material.encode("utf-8")).hexdigest()
    return f"rnd={nonce}; date={ts}; gid={token_gid}; sg={digest}"


def aizone_headers(
    *,
    api_key: str,
    jwt: str = "",
    guid: str = "",
    account: str = "",
    request_id: str | None = None,
) -> dict[str, str]:
    """Direct aizone chat headers.

    Official 0.2.36.629 live capture: Bearer sk- key is accepted, but the
    request is 400 without X-Conversation-Request-ID. HMAC inject headers
    from the desktop proxy are not required on the public aizone host.
    """
    rid = request_id or str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"QClaw/{CLIENT_VERSION}",
        "X-Conversation-Request-ID": rid,
        "X-Conversation-ID": str(uuid.uuid4()),
        "X-Conversation-Message-ID": str(uuid.uuid4()),
        "X-QClaw-Version": CLIENT_VERSION,
        "X-Trigger": "webchat",
        "X-Guid": guid or "1",
        "X-Account": account or "1",
    }
    if jwt:
        headers["X-OpenClaw-Token"] = jwt
    return headers
