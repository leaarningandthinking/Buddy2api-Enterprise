"""Channel registry. WorkBuddy, QClaw, QwenWork, and TraeWork are enabled by default."""

from __future__ import annotations

import os

from providers.protocol import (
    KNOWN_CHANNEL_IDS,
    KNOWN_CHANNEL_SET,
    ChannelId,
    Provider,
)
from providers.qclaw import PROVIDER as QCLAW_PROVIDER
from providers.qwenwork import PROVIDER as QWENWORK_PROVIDER
from providers.traework import PROVIDER as TRAEWORK_PROVIDER
from providers.workbuddy import PROVIDER as WORKBUDDY_PROVIDER

DEFAULT_PROVIDER_IDS: tuple[str, ...] = ("workbuddy", "qclaw", "qwenwork", "traework")

_LOADED: dict[str, Provider] = {
    "workbuddy": WORKBUDDY_PROVIDER,
    "qclaw": QCLAW_PROVIDER,
    "qwenwork": QWENWORK_PROVIDER,
    "traework": TRAEWORK_PROVIDER,
}


def _parse_enabled() -> list[str]:
    raw = (os.environ.get("CB_GATEWAY_PROVIDERS") or "").strip()
    if not raw:
        return list(DEFAULT_PROVIDER_IDS)
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    if not parts:
        return list(DEFAULT_PROVIDER_IDS)
    unknown = [item for item in parts if item not in KNOWN_CHANNEL_SET]
    if unknown:
        raise RuntimeError(
            f"Unknown CB_GATEWAY_PROVIDERS id(s): {', '.join(unknown)}. "
            f"Known: {', '.join(KNOWN_CHANNEL_IDS)}"
        )
    if "workbuddy" not in parts:
        parts = ["workbuddy", *parts]
    # workbuddy first, then remaining in written order
    ordered = ["workbuddy"]
    for item in parts:
        if item != "workbuddy" and item not in ordered:
            ordered.append(item)
    return ordered


def enabled_provider_ids() -> list[str]:
    return _parse_enabled()


def is_known_channel(channel: str) -> bool:
    return channel in KNOWN_CHANNEL_SET


def is_channel_enabled(channel: str) -> bool:
    return channel in enabled_provider_ids()


def get_provider(channel: str) -> Provider | None:
    if channel not in enabled_provider_ids():
        return None
    return _LOADED.get(channel)


def register_provider(provider: Provider) -> None:
    """Test helper to install a stub channel."""
    _LOADED[provider.id] = provider
