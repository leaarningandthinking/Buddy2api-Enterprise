#!/bin/zsh
# Buddy2api 启动脚本（macOS，TraeWork 通道）
cd "$(dirname "$0")"

export CB_TRAEWORK_AUTH_DIR="$HOME/Library/Application Support/TRAE SOLO CN/User/globalStorage"

# 想只开 TraeWork 一个通道时，取消下面这行的注释：
# export CB_GATEWAY_PROVIDERS=traework

exec .venv/bin/python server.py --no-browser
