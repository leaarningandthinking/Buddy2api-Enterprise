"""TraeWork supplier-list fetch. Isolated from chat I/O."""

from __future__ import annotations

import httpx
from model_capacity import capacity_fields

from providers.traework.constants import AGENT_API, ENTERPRISE_AGENT_API, MODELS_PATH, route_mode
from providers.traework.token import TraeWorkAuthError, auth_headers


def parse_supplier_models(payload) -> list[dict]:
    rows = _rows_from_payload(payload)
    models: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            mid = row.strip()
            name = mid
        elif isinstance(row, dict):
            mid = str(
                row.get("id")
                or row.get("model_name")
                or row.get("name")
                or row.get("model")
                or ""
            ).strip()
            name = str(row.get("display_name") or row.get("name") or row.get("model_name") or mid)
        else:
            continue
        if not mid or mid in seen:
            continue
        seen.add(mid)
        item = {"id": mid, "name": name or mid}
        item.update(capacity_fields(row))
        models.append(item)
    return models


def _flatten_model_groups(rows: list) -> list:
    """TraeWork returns function buckets: data.list[].models[], not a flat id list."""
    flattened: list = []
    for row in rows:
        if not isinstance(row, dict):
            flattened.append(row)
            continue
        nested = row.get("models")
        grouped = isinstance(nested, list) and not (
            row.get("id") or row.get("model_name") or row.get("model")
        )
        if grouped:
            flattened.extend(nested)
            continue
        flattened.append(row)
    return flattened


def _rows_from_payload(payload) -> list:
    if isinstance(payload, list):
        return _flatten_model_groups(payload)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), (dict, list)) else payload
    if isinstance(data, list):
        return _flatten_model_groups(data)
    if not isinstance(data, dict):
        return []
    for key in ("models", "model_list", "items", "list", "model_infos"):
        rows = data.get(key)
        if isinstance(rows, list):
            return _flatten_model_groups(rows)
    nested = data.get("data")
    if isinstance(nested, list):
        return _flatten_model_groups(nested)
    if isinstance(nested, dict):
        for key in ("models", "model_list", "items", "list"):
            rows = nested.get(key)
            if isinstance(rows, list):
                return _flatten_model_groups(rows)
    return []


async def fetch_supplier_models(account: dict) -> list[dict]:
    headers = auth_headers(account)
    # 消费端与企业端各有一份 solo_work_remote 目录；dual 模式合并两端
    mode = route_mode()
    hosts = {"enterprise": [ENTERPRISE_AGENT_API], "consumer": [AGENT_API]}.get(mode)
    if hosts is None:
        hosts = [ENTERPRISE_AGENT_API, AGENT_API]
    merged: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Without functions, the endpoint defaults to the legacy solo_coder
        # catalog. Work sessions use the current solo_work_remote catalog.
        for host in hosts:
            response = await client.get(
                f"{host}{MODELS_PATH}",
                headers=headers,
                params={"functions": "solo_work_remote", "show_custom_model": "true"},
            )
            if response.status_code >= 400:
                raise TraeWorkAuthError(f"models HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise TraeWorkAuthError("models response is not JSON") from exc
            if isinstance(payload, dict) and payload.get("code") not in (None, 0):
                raise TraeWorkAuthError(str(payload.get("message") or payload.get("code")))
            for item in parse_supplier_models(payload):
                mid = str(item.get("id"))
                if mid in seen:
                    continue
                seen.add(mid)
                merged.append(item)
    return merged
