"""Per-channel model aliases.

User maps overlay each channel's built-in map and never cross channels.
Legacy flat `model_aliases` settings are treated as WorkBuddy-only.
"""

from __future__ import annotations

import sqlite3

import database as db

SETTING = "model_aliases"


class AliasError(ValueError):
    """Invalid alias payload."""


def _builtin_aliases(channel: str) -> dict[str, str]:
    if channel == "workbuddy":
        import proxy

        return dict(proxy._BUILTIN_ALIASES)
    if channel == "qclaw":
        from providers.qclaw.constants import ALIASES

        return dict(ALIASES)
    if channel == "qwenwork":
        from providers.qwenwork.constants import ALIASES

        return dict(ALIASES)
    if channel == "traework":
        from providers.traework.constants import ALIASES

        return dict(ALIASES)
    return {}


def _clean_map(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        alias = key.strip()
        target = value.strip()
        if not alias or not target:
            continue
        out[alias] = target
    return out


def load_user_aliases() -> dict[str, dict[str, str]]:
    try:
        raw = db.get_setting(SETTING, {}) or {}
    except sqlite3.OperationalError:
        return {}
    if not isinstance(raw, dict) or not raw:
        return {}
    if any(isinstance(value, dict) for value in raw.values()):
        return {
            str(channel): _clean_map(mapping)
            for channel, mapping in raw.items()
            if isinstance(mapping, dict)
        }
    return {"workbuddy": _clean_map(raw)}


def user_aliases_for(channel: str) -> dict[str, str]:
    return dict(load_user_aliases().get(channel) or {})


def merged_map(channel: str) -> dict[str, str]:
    return {**_builtin_aliases(channel), **user_aliases_for(channel)}


def resolve(channel: str, model: str) -> str:
    value = (model or "").strip()
    if not value:
        return value
    return merged_map(channel).get(value, value)


def builtin_keys(channel: str) -> set[str]:
    return set(_builtin_aliases(channel))


def save_user_aliases(data: dict) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict):
        raise AliasError("aliases must be an object")
    payload = {"workbuddy": data} if data and all(isinstance(value, str) for value in data.values()) else data

    import providers

    stored = load_user_aliases()
    for channel, mapping in payload.items():
        name = str(channel or "").strip()
        if not name:
            raise AliasError("channel is required")
        if not providers.is_known_channel(name):
            raise AliasError(f"unknown channel '{name}'")
        if not isinstance(mapping, dict):
            raise AliasError(f"aliases for '{name}' must be an object")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()):
            raise AliasError("aliases must map string names to string model IDs")
        skip = builtin_keys(name)
        clean: dict[str, str] = {}
        for key, value in mapping.items():
            alias = key.strip()
            target = value.strip()
            if not alias or not target:
                continue
            if "/" in alias:
                raise AliasError("alias must not contain '/'")
            if alias in skip:
                continue
            clean[alias] = target
        stored[name] = clean
    db.set_setting(SETTING, stored)
    return stored


def snapshot() -> dict:
    import providers

    sources = []
    for channel in providers.enabled_provider_ids():
        provider = providers.get_provider(channel)
        builtin = _builtin_aliases(channel)
        sources.append(
            {
                "channel": channel,
                "display_name": getattr(provider, "display_name", channel) if provider else channel,
                "aliases": merged_map(channel),
                "builtin_keys": list(builtin.keys()),
            }
        )
    return {"sources": sources}
