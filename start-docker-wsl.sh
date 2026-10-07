#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data

echo ""
echo "  ========================================"
echo "   Buddy 2 API Docker for WSL"
echo "  ========================================"
echo ""

if ! command -v docker >/dev/null 2>&1; then
    echo "  [错误] 未找到 Docker，请先启动 Docker Desktop，并确认 WSL 能访问 docker 命令。"
    exit 1
fi

auth_dir="${CB_HOST_AUTH_DIR:-}"

if [ -z "$auth_dir" ] && command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    win_local="$(cmd.exe /c echo %LOCALAPPDATA% 2>/dev/null | tr -d '\r')"
    if [ -n "$win_local" ]; then
        auth_dir="$(wslpath -u "$win_local")/CodeBuddyExtension/Data/Public/auth"
    fi
fi

if [ -z "$auth_dir" ] || [ ! -d "$auth_dir" ]; then
    auth_dir="$(find /mnt/c/Users -path '*/AppData/Local/CodeBuddyExtension/Data/Public/auth' -type d 2>/dev/null | head -n 1 || true)"
fi

compose_files=(-f docker-compose.yml)
if [ -n "$auth_dir" ] && [ -d "$auth_dir" ]; then
    export CB_HOST_AUTH_DIR="$auth_dir"
    compose_files+=(-f docker-compose.windows.yml)
    echo "  [auth] $auth_dir"
    echo "  [挂载] $auth_dir -> /auth:ro"
else
    echo "  [提示] 未找到 Work Buddy auth 目录，将不挂载 Windows overlay。"
    echo "  启动后可在管理页手动导入。指定路径："
    echo "  export CB_HOST_AUTH_DIR=/mnt/c/Users/你的用户名/AppData/Local/CodeBuddyExtension/Data/Public/auth"
fi
if [ -z "${CB_GATEWAY_ADMIN_TOKEN:-}" ]; then
    CB_GATEWAY_ADMIN_TOKEN="cb-admin-$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
    export CB_GATEWAY_ADMIN_TOKEN
    echo "  [安全] 已为本次会话生成随机管理 Token。"
fi

echo "  [启动] http://127.0.0.1:8787"
echo ""

docker compose "${compose_files[@]}" up -d --build

echo ""
echo "  已启动。打开 http://127.0.0.1:8787，账号页先选通道再检测导入。"
echo "  QClaw / 千问办公的 Windows 登录文件在 Linux 容器里解不开，这两家请用 python server.py。"
