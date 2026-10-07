"""TraeWork chat via remote chat_sessions. Isolated HTTP client."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator

import httpx

import auth_manager
import database as db
from providers.traework.constants import (
    AGENT_API,
    AGENT_ID,
    CHANNEL_ID,
    ENTERPRISE_AGENT_API,
    ENTERPRISE_DEFAULT_MODEL,
    ENTERPRISE_STATIC_MODELS,
    SESSION_MODE,
    SESSIONS_PATH,
    STATIC_MODELS,
    route_mode,
)
from providers.traework.token import TraeWorkAuthError, auth_headers, is_token_expired, refresh_account


def translate_model(model: str) -> str:
    import aliases

    inner = (model or "auto").strip() or "auto"
    if inner == "auto":
        # dual/enterprise 模式下 auto 走企业额度；consumer 模式沿用消费端别名
        if route_mode() == "consumer":
            return aliases.resolve(CHANNEL_ID, "auto")
        return ENTERPRISE_DEFAULT_MODEL
    return aliases.resolve(CHANNEL_ID, inner)


def _route_for(model_inner: str) -> str:
    mode = route_mode()
    if mode == "enterprise":
        return ENTERPRISE_AGENT_API
    if mode == "consumer":
        return AGENT_API
    if model_inner in ENTERPRISE_STATIC_MODELS:
        return ENTERPRISE_AGENT_API
    return AGENT_API


def accepts_model(inner: str) -> bool:
    import aliases
    import catalog

    value = (inner or "").strip()
    if value in aliases.merged_map(CHANNEL_ID):
        return True
    if value in ENTERPRISE_STATIC_MODELS:
        return True
    models = catalog.models_for(CHANNEL_ID, [{"id": item} for item in STATIC_MODELS])
    ids = {str(item.get("id")) for item in models if isinstance(item, dict)}
    return value in ids


def _last_user_text(payload: dict) -> str:
    for item in reversed(payload.get("messages") or []):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
            text = "".join(parts).strip()
            if text:
                return text
    return ""


_SKIP_EVENT_NAMES = {
    "heartbeat",
    "status_changed",
    "platform_timing",
    "timing_events",
    "token_usage",
    "model_config",
    "project_name_message",
    "session_title_message",
    "session_icon_message",
    "metadata",
}
_SKIP_NODE_TYPES = {"status", "heartbeat", "metadata"}
_REASONING_NODE_TYPES = {"thinking", "reasoning", "thought", "chain_of_thought"}
_TEXT_NODE_TYPES = {"text", "markdown", "output_text", "answer"}
_FINISH_TOOL_NAMES = {"finish", "attempt_completion", "complete_task"}
_RECURSE_KEYS = ("messages", "content", "data", "plan_item", "payload")


def _intish(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_usage(raw) -> dict:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    prompt = _intish(raw.get("prompt_tokens"))
    completion = _intish(raw.get("completion_tokens"))
    total = _intish(raw.get("total_tokens")) or (prompt + completion)
    if not prompt and not completion and not total:
        return {}
    usage = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    reasoning = _intish(raw.get("reasoning_tokens"))
    if reasoning:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    return usage


def _dedupe(chunks: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk in chunks:
        text = (chunk or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return "\n".join(ordered).strip()


def _finish_summary(info: dict) -> str:
    name = str(info.get("name") or "").strip().lower()
    if name not in _FINISH_TOOL_NAMES:
        return ""
    params = info.get("params") if isinstance(info.get("params"), dict) else {}
    summary = params.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    result = info.get("result") if isinstance(info.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    nested = data.get("summary")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return ""


def _collect(value, content: list[str], reasoning: list[str]) -> None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                _collect(json.loads(text), content, reasoning)
            except json.JSONDecodeError:
                pass
        return
    if isinstance(value, list):
        for item in value:
            _collect(item, content, reasoning)
        return
    if not isinstance(value, dict):
        return

    kind = str(value.get("type") or "")
    if kind in _SKIP_NODE_TYPES:
        return

    info = value.get("tool_call_info")
    if isinstance(info, dict):
        summary = _finish_summary(info)
        if summary:
            content.append(summary)

    if kind in {"tool", "tool_call"}:
        summary = _finish_summary(value)
        if summary:
            content.append(summary)
        return

    thought = value.get("reasoning_content")
    if isinstance(thought, str) and thought.strip():
        reasoning.append(thought.strip())
    thought = value.get("thought")
    if kind in _REASONING_NODE_TYPES and isinstance(thought, str) and thought.strip():
        reasoning.append(thought.strip())

    if kind in _REASONING_NODE_TYPES:
        for key in ("text_content", "text", "markdown", "plain_text"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                reasoning.append(item.strip())
        return

    if kind in _TEXT_NODE_TYPES or kind in {"", "plan_item"}:
        for key in ("text_content", "text", "markdown", "plain_text"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                content.append(item.strip())

    for key in _RECURSE_KEYS:
        child = value.get(key)
        if child is None or child is value:
            continue
        if key == "content" and isinstance(child, str) and child.strip() and not child.strip().startswith(("{", "[")):
            if child.strip() not in content:
                content.append(child.strip())
            continue
        _collect(child, content, reasoning)


def _text_from_event(event: str, payload: dict) -> str:
    if event in _SKIP_EVENT_NAMES:
        return ""
    content: list[str] = []
    reasoning: list[str] = []
    _collect(payload, content, reasoning)
    return _dedupe(content)


def extract_assistant_turn(items: list) -> dict:
    content: list[str] = []
    reasoning: list[str] = []
    usage: dict = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("role") not in {"assistant", "system"} and item.get("message_type") != "task":
            continue
        _collect(item.get("content"), content, reasoning)
        parsed = _parse_usage(item.get("token_usage"))
        if parsed:
            usage = parsed
    return {
        "text": _dedupe(content),
        "reasoning": _dedupe(reasoning),
        "usage": usage,
    }


def extract_assistant_text(items: list) -> str:
    return extract_assistant_turn(items)["text"]


def _openai_json(
    model: str,
    text: str,
    finish: str = "stop",
    reasoning: str = "",
    usage: dict | None = None,
) -> dict:
    message = {"role": "assistant", "content": text}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "id": f"traework-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish,
            }
        ],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _pick(tried: set[int]) -> dict | None:
    account = auth_manager.pick_account(tried, provider=CHANNEL_ID)
    if account:
        if is_token_expired(account):
            try:
                return await refresh_account(account)
            except TraeWorkAuthError:
                pass
        else:
            return account
    expired = [
        row
        for row in db.list_accounts(provider=CHANNEL_ID)
        if row.get("status") == "expired" and row.get("id") not in tried
    ]
    for row in expired:
        try:
            return await refresh_account(row)
        except TraeWorkAuthError:
            continue
    return None


def _log(api_key_info, account, model_name, stream, finish, status, error, t0, usage: dict | None = None):
    usage = usage or {}
    try:
        db.record_request(
            {
                "api_key_id": api_key_info["id"] if api_key_info else None,
                "api_key_name": api_key_info["name"] if api_key_info else None,
                "account_id": account["id"] if account else None,
                "account_name": account.get("name") if account else None,
                "provider": CHANNEL_ID,
                "model": model_name,
                "stream": 1 if stream else 0,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "credit": 0,
                "finish_reason": finish,
                "duration_ms": int((time.time() - t0) * 1000),
                "status_code": status,
                "error_msg": error,
                "increment_usage": True,
            }
        )
    except Exception:
        pass


def _format_upstream_error(payload: dict) -> str:
    code = payload.get("code")
    message = str(payload.get("message") or "").strip()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    detail = ""
    if data:
        wanted = {k: data[k] for k in ("dimension", "quota", "used", "next_flash") if k in data}
        detail = " " + json.dumps(wanted or data, ensure_ascii=False, default=str)[:200]
    prefix = f"TraeWork upstream error {code}" if code else "TraeWork upstream error"
    return f"{prefix}: {message or 'no message'}.{detail}"


async def _turn(account: dict, prompt: str, model: str, timeout: float = 90.0, api_base: str = "") -> dict:
    base = (api_base or AGENT_API).rstrip("/")
    headers = auth_headers(account)
    session_url = f"{base}{SESSIONS_PATH}"
    sid = ""
    async with httpx.AsyncClient(timeout=timeout) as client:
        created = await client.post(
            session_url,
            headers=headers,
            json={"mode": SESSION_MODE, "auto_create_project": True, "origin": "web"},
        )
        if created.status_code >= 400:
            raise TraeWorkAuthError(f"create session HTTP {created.status_code}")
        data = created.json() if created.content else {}
        if data.get("code") not in (None, 0):
            raise TraeWorkAuthError(str(data.get("message") or data.get("code")))
        sid = str((data.get("data") or {}).get("chat_session_id") or "")
        if not sid:
            raise TraeWorkAuthError("create session missing chat_session_id")
        pieces: list[str] = []
        finished = asyncio.Event()
        upstream_error: dict = {}

        async def read_events() -> None:
            nonlocal upstream_error
            event_name = "message"
            try:
                async with client.stream(
                    "GET",
                    f"{session_url}/{sid}/events",
                    headers={**headers, "Accept": "text/event-stream"},
                ) as response:
                    if response.status_code >= 400:
                        finished.set()
                        return
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event_name = line[6:].strip() or "message"
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        try:
                            event_payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if event_name == "error" and isinstance(event_payload, dict):
                            upstream_error = event_payload
                            finished.set()
                            return
                        text = _text_from_event(event_name, event_payload if isinstance(event_payload, dict) else {})
                        if text:
                            pieces.append(text)
                        if event_name == "done":
                            finished.set()
                            return
            except httpx.HTTPError:
                finished.set()

        task = asyncio.create_task(read_events())
        try:
            await asyncio.sleep(0.35)
            query = json.dumps(
                [{"type": "text", "data": {"content": prompt}}],
                ensure_ascii=False,
            )
            sent = await client.post(
                f"{session_url}/{sid}/messages",
                headers=headers,
                json={
                    "chat_session_id": sid,
                    "content": [],
                    "query": query,
                    "model_name": model,
                    "agent_id": AGENT_ID,
                    "agent_type": AGENT_ID,
                },
            )
            payload = sent.json() if sent.content else {}
            if sent.status_code >= 400 or payload.get("code") not in (None, 0):
                raise TraeWorkAuthError(str(payload.get("message") or f"HTTP {sent.status_code}"))
            try:
                await asyncio.wait_for(finished.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            messages = await client.get(f"{session_url}/{sid}/messages", headers=headers)
            body = messages.json() if messages.content else {}
            items = ((body.get("data") or {}).get("items") or [])
            turn = extract_assistant_turn(items)
            text = turn["text"] or "\n".join(dict.fromkeys(pieces)).strip()
            if not text:
                if upstream_error:
                    raise TraeWorkAuthError(_format_upstream_error(upstream_error))
                raise TraeWorkAuthError("TraeWork turn finished without assistant text")
            return {
                "text": text,
                "reasoning": turn["reasoning"],
                "usage": turn["usage"],
            }
        finally:
            task.cancel()
            try:
                await client.delete(f"{session_url}/{sid}", headers=headers)
            except Exception:
                pass


async def chat_completions(payload: dict, api_key_info: dict | None) -> tuple:
    model = translate_model(str(payload.get("model") or "auto"))
    prompt = _last_user_text(payload)
    if not prompt:
        return (
            "error",
            (400, {"error": {"message": "messages must include a user turn", "type": "invalid_request_error"}}),
        )
    stream = bool(payload.get("stream"))
    tried: set[int] = set()
    last_error = None
    for _ in range(3):
        account = await _pick(tried)
        if not account:
            break
        tried.add(int(account["id"]))
        t0 = time.time()
        try:
            turn = await _turn(account, prompt, model, api_base=_route_for(model))
            auth_manager.mark_account_success(account["id"])
            _log(
                api_key_info, account, payload.get("model") or model, stream, "stop", 200, "", t0,
                turn.get("usage"),
            )
            model_name = str(payload.get("model") or model)
            if stream:
                return (
                    "stream",
                    _stream_once(turn["text"], model_name, turn.get("reasoning") or "", turn.get("usage")),
                )
            return (
                "json",
                _openai_json(model_name, turn["text"], reasoning=turn.get("reasoning") or "", usage=turn.get("usage")),
            )
        except TraeWorkAuthError as exc:
            auth_manager.mark_account_failure(account["id"], 503)
            last_error = ("error", (503, {"error": {"message": str(exc)[:240], "type": "server_error"}}))
            _log(api_key_info, account, payload.get("model") or model, stream, "error", 503, str(exc)[:240], t0)
            continue
        except httpx.HTTPError as exc:
            auth_manager.mark_account_failure(account["id"], 503)
            last_error = ("error", (503, {"error": {"message": str(exc)[:240], "type": "server_error"}}))
            continue
    return last_error or (
        "error",
        (
            503,
            {
                "error": {
                    "message": "No available accounts",
                    "type": "channel_unavailable",
                    "code": "channel_unavailable",
                }
            },
        ),
    )


async def _stream_once(
    text: str,
    model: str,
    reasoning: str = "",
    usage: dict | None = None,
) -> AsyncGenerator[bytes, None]:
    cid = f"traework-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    delta: dict = {"role": "assistant"}
    if reasoning:
        delta["reasoning_content"] = reasoning
    if text:
        delta["content"] = text
    chunk = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
    done = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"


async def test_chat(account: dict, model: str = "auto", prompt: str = "请回复：pong") -> dict:
    t0 = time.time()
    chosen = translate_model(model or "auto")
    try:
        turn = await _turn(
            account,
            prompt or "请回复：pong",
            chosen,
            timeout=90.0,
            api_base=_route_for(chosen),
        )
        text = turn["text"]
    except TraeWorkAuthError as exc:
        return {
            "ok": False,
            "status_code": 503,
            "duration_ms": int((time.time() - t0) * 1000),
            "message": str(exc)[:400],
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "status_code": 0,
            "duration_ms": int((time.time() - t0) * 1000),
            "message": str(exc)[:400],
        }
    return {
        "ok": True,
        "status_code": 200,
        "duration_ms": int((time.time() - t0) * 1000),
        "model": chosen,
        "message": text[:400],
    }
