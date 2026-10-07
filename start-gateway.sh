#!/bin/zsh
# Buddy2api 网关手动启动（macOS，仅 WorkBuddy 通道）
cd "$(dirname "$0")"
export CB_GATEWAY_PROVIDERS=workbuddy
exec .venv/bin/python server.py --no-browser
