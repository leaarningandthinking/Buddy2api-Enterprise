#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

echo ""
echo "  ========================================"
echo "   Buddy 2 API"
echo "  ========================================"
echo ""

# 优先使用固定名称的 Conda 环境；无需提前 conda activate
conda_exe=""
if command -v conda >/dev/null 2>&1; then
    conda_exe="$(command -v conda)"
else
    for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "/opt/conda/bin/conda"; do
        if [ -x "$candidate" ]; then
            conda_exe="$candidate"
            break
        fi
    done
fi

if [ -n "$conda_exe" ]; then
    echo "  [环境] Conda: buddy2api"
    if ! "$conda_exe" run -n buddy2api python --version >/dev/null 2>&1; then
        echo "  [安装] 创建 Conda 环境 buddy2api (Python 3.12)..."
        "$conda_exe" create -n buddy2api python=3.12 -y
    fi
    if ! "$conda_exe" run -n buddy2api python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        echo "  [更新] 将 buddy2api 环境升级到 Python 3.12..."
        "$conda_exe" install -n buddy2api python=3.12 -y
    fi
    if ! "$conda_exe" run -n buddy2api python -c 'import fastapi, uvicorn, httpx, cryptography' >/dev/null 2>&1; then
        echo "  [安装] 安装锁定依赖..."
        "$conda_exe" run -n buddy2api python -m pip install -r requirements.txt
    fi
    echo "  [启动] http://127.0.0.1:8787"
    echo "  [停止] Ctrl+C"
    echo ""
    exec "$conda_exe" run --no-capture-output -n buddy2api python server.py --port 8787 "$@"
fi

echo "  [环境] 未找到 Conda，使用项目 .venv"
if ! command -v python3 >/dev/null 2>&1; then
    echo "  [错误] 未找到 Python 3.10+，请安装 Miniconda 或 Python"
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo "  [错误] Python 版本过低，请安装 Python 3.10+"
    exit 1
fi

venv_dir=".venv"
if [ ! -x "$venv_dir/bin/python" ]; then
    echo "  [安装] 创建项目虚拟环境..."
    python3 -m venv "$venv_dir"
fi
if ! "$venv_dir/bin/python" -c 'import fastapi, uvicorn, httpx, cryptography' >/dev/null 2>&1; then
    echo "  [安装] 安装锁定依赖..."
    "$venv_dir/bin/python" -m pip install -r requirements.txt
fi
echo "  [启动] http://127.0.0.1:8787"
echo "  [停止] Ctrl+C"
echo ""
exec "$venv_dir/bin/python" server.py --port 8787 "$@"
