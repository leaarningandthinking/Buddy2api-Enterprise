"""Check GitHub/CDN for a newer Buddy2api and apply a local git update."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from version import VERSION

ROOT = Path(__file__).resolve().parent
DEFAULT_REPO = "wicm84266964/Buddy2api"
CACHE_OK_TTL = 600.0
CACHE_FAIL_TTL = 60.0
VERSION_RE = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']', re.M)
VERSION_SOURCES = (
    ("jsdelivr", "https://cdn.jsdelivr.net/gh/{repo}@main/version.py", "file"),
    ("jsdelivr-fastly", "https://fastly.jsdelivr.net/gh/{repo}@main/version.py", "file"),
    ("github-raw", "https://raw.githubusercontent.com/{repo}/main/version.py", "file"),
    ("github-release", "https://api.github.com/repos/{repo}/releases/latest", "release"),
)

_cache: dict = {"at": 0.0, "ttl": 0.0, "payload": None}


def repo() -> str:
    value = os.environ.get("CB_GATEWAY_UPDATE_REPO", DEFAULT_REPO).strip()
    return value or DEFAULT_REPO


def fake_latest() -> str | None:
    return _normalize_version(os.environ.get("CB_GATEWAY_FAKE_LATEST", ""))


def parse_version_file(text: str) -> str | None:
    match = VERSION_RE.search(text or "")
    if not match:
        return None
    return _normalize_version(match.group(1))


def parse_release_tag(text: str) -> str | None:
    import json

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_version(str(data.get("tag_name") or data.get("name") or ""))


def _normalize_version(value: str) -> str | None:
    text = value.strip()
    if text.lower().startswith("v") and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    if not text or not text[0].isdigit():
        return None
    return text


def version_key(value: str) -> tuple[int, ...]:
    parts = []
    normalized = _normalize_version(value) or "0"
    for piece in normalized.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts or (0,))


def is_newer(remote: str, local: str) -> bool:
    return version_key(remote) > version_key(local)


def reset_cache() -> None:
    _cache["at"] = 0.0
    _cache["ttl"] = 0.0
    _cache["payload"] = None


def in_docker() -> bool:
    flag = os.environ.get("CB_DOCKER", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    return Path("/.dockerenv").exists()


def install_kind() -> str:
    if in_docker():
        return "docker"
    if (ROOT / ".git").is_dir():
        return "git"
    return "files"


def install_hint(kind: str) -> str:
    if kind == "docker":
        return "Docker 部署请在宿主机重新构建镜像后重启"
    if kind == "files":
        return "当前不是 git 克隆，请按 README 手动更新"
    return ""


def restart_allowed() -> bool:
    flag = os.environ.get("CB_GATEWAY_SKIP_RESTART", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


async def _get(url: str) -> tuple[int, str]:
    headers = {"User-Agent": f"Buddy2api/{VERSION}", "Accept": "application/json, text/plain"}
    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        return response.status_code, response.text or ""


async def check(*, force: bool = False) -> dict:
    now = time.time()
    payload = _cache.get("payload")
    if not force and payload and now - float(_cache.get("at") or 0) < float(_cache.get("ttl") or 0):
        return payload
    payload = await _check_now()
    _cache["at"] = now
    _cache["ttl"] = CACHE_OK_TTL if payload.get("checked") else CACHE_FAIL_TTL
    _cache["payload"] = payload
    return payload


async def _check_now() -> dict:
    kind = install_kind()
    latest = None
    source = None
    forced = fake_latest()
    if forced:
        latest = forced
        source = "fake"
    else:
        latest, source = await _fetch_latest()
    current = VERSION
    checked = latest is not None
    update_available = bool(checked and is_newer(latest, current))
    return {
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "can_apply": kind == "git" and update_available,
        "install": kind,
        "checked": checked,
        "source": source,
        "message": install_hint(kind) if update_available and kind != "git" else "",
    }


async def _fetch_latest() -> tuple[str | None, str | None]:
    for name, template, mode in VERSION_SOURCES:
        url = template.format(repo=repo())
        try:
            status, text = await _get(url)
        except Exception:
            continue
        if status != 200 or not text:
            continue
        parsed = parse_version_file(text) if mode == "file" else parse_release_tag(text)
        if not parsed:
            continue
        return parsed, name
    return None, None


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    kwargs = {
        "args": args,
        "cwd": str(ROOT),
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(**kwargs)


def _git_ready() -> str | None:
    if install_kind() != "git":
        return install_hint(install_kind()) or "当前安装不能一键更新"
    try:
        inside = _run(["git", "rev-parse", "--is-inside-work-tree"], 8)
    except FileNotFoundError:
        return "未找到 git，无法一键更新"
    except subprocess.TimeoutExpired:
        return "git 响应超时"
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return "当前目录不是 git 仓库"
    try:
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], 8)
        status = _run(["git", "status", "--porcelain"], 8)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "无法读取 git 状态"
    name = branch.stdout.strip()
    if branch.returncode != 0 or name in {"", "HEAD"}:
        return "当前是游离 HEAD，请手动更新"
    if name not in {"main", "master"}:
        return f"当前分支是 {name}，一键更新只支持 main"
    dirty = [
        line
        for line in status.stdout.splitlines()
        if line.strip() and not line.startswith("??") and not line.startswith("!!")
    ]
    if dirty:
        return "工作区有未提交修改，请先手动处理"
    return None


def _local_version() -> str:
    try:
        text = (ROOT / "version.py").read_text(encoding="utf-8")
    except OSError:
        return VERSION
    return parse_version_file(text) or VERSION


def apply() -> dict:
    snapshot = asyncio.run(check(force=True))
    if not snapshot.get("update_available"):
        if not snapshot.get("checked"):
            return {
                "ok": False,
                "restart": False,
                "current": snapshot.get("current") or VERSION,
                "latest": snapshot.get("latest"),
                "message": "暂时查不到远端版本",
            }
        return {
            "ok": False,
            "restart": False,
            "current": snapshot.get("current") or VERSION,
            "latest": snapshot.get("latest"),
            "message": f"已是最新版本 v{snapshot.get('current') or VERSION}",
        }
    if snapshot.get("source") == "fake":
        return {
            "ok": True,
            "restart": False,
            "current": snapshot.get("current") or VERSION,
            "latest": snapshot.get("latest"),
            "message": "测试模式：不会拉取代码，也不会重启",
        }
    blocked = _git_ready()
    if blocked:
        return {
            "ok": False,
            "restart": False,
            "current": snapshot.get("current") or VERSION,
            "latest": snapshot.get("latest"),
            "message": blocked,
        }
    try:
        pull = _run(["git", "pull", "--ff-only"], 90)
    except FileNotFoundError:
        return {"ok": False, "restart": False, "message": "未找到 git，无法一键更新"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "restart": False, "message": "git pull 超时"}
    if pull.returncode != 0:
        detail = (pull.stderr or pull.stdout or "git pull 失败").strip()
        return {"ok": False, "restart": False, "message": detail[:400]}
    new_version = _local_version()
    if not is_newer(new_version, snapshot["current"]) and new_version == snapshot["current"]:
        return {
            "ok": False,
            "restart": False,
            "current": new_version,
            "latest": snapshot.get("latest"),
            "message": "已拉取，但本地版本没有变化。请确认 git remote 指向本仓库 main",
        }
    requirements = ROOT / "requirements.txt"
    if requirements.is_file():
        try:
            pip = _run([sys.executable, "-m", "pip", "install", "-r", str(requirements)], 180)
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "restart": False,
                "current": new_version,
                "latest": snapshot.get("latest"),
                "message": "代码已更新，但安装依赖超时。请手动执行 pip install -r requirements.txt 后重启",
            }
        if pip.returncode != 0:
            detail = (pip.stderr or pip.stdout or "pip 失败").strip()
            return {
                "ok": False,
                "restart": False,
                "current": new_version,
                "latest": snapshot.get("latest"),
                "message": f"代码已更新，但安装依赖失败：{detail[:300]}",
            }
    reset_cache()
    return {
        "ok": True,
        "restart": True,
        "current": snapshot["current"],
        "latest": new_version,
        "message": f"已更新到 v{new_version}，正在重启",
    }


def restart_now() -> None:
    if not restart_allowed():
        return
    python = sys.executable
    argv = [python, *sys.argv]
    if os.name == "nt":
        _restart_windows(python, argv)
        return
    os.execv(python, argv)


def schedule_restart(delay: float = 0.4) -> None:
    if not restart_allowed():
        return
    threading.Thread(target=_restart_after, args=(delay,), daemon=True).start()


def _restart_after(delay: float) -> None:
    time.sleep(max(0.0, delay))
    restart_now()


def _restart_windows(python: str, argv: list[str]) -> None:
    parent = os.getpid()
    cwd = os.getcwd()
    waiter = (
        "import os, time, subprocess\n"
        f"p={parent}\n"
        f"a={argv!r}\n"
        f"c={cwd!r}\n"
        "for _ in range(75):\n"
        "    try:\n"
        "        os.kill(p, 0)\n"
        "    except OSError:\n"
        "        break\n"
        "    time.sleep(0.2)\n"
        "time.sleep(0.4)\n"
        "flags=getattr(subprocess,'DETACHED_PROCESS',8)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)\n"
        "subprocess.Popen(a, cwd=c, close_fds=True, creationflags=flags)\n"
    )
    flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    subprocess.Popen([python, "-c", waiter], close_fds=True, creationflags=flags)
    os._exit(0)
