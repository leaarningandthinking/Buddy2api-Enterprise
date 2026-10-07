"""TraeWork CN (TRAE SOLO CN) protocol constants.

Hosts, client id, and app version were read from the official
0.1.56 product.json and live requests on this machine.

企业后端（work.enterprise.trae.cn）由本机 TRAE SOLO CN 日志逆向得出：
路径结构与消费端一致（/api/remote/v1/*），接受同一把 Cloud-IDE-JWT，
计费走企业权益（cue）而不是消费端免费包的每日任务数。
"""

from __future__ import annotations

import os

CHANNEL_ID = "traework"
DISPLAY_NAME = "TraeWork"

IDE_VERSION = "0.1.56"
CLIENT_ID = "en1oxy7wnw8j9n"
PLATFORM_CODE = "SOLO_PC"
PRODUCT_CODE = "SOLO_Lite"
REQ_SOURCE = 2
APP_ID = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"

UG_API = "https://api.trae.cn"
AGENT_API = "https://trae-api-cn.mchost.guru"
ENTERPRISE_AGENT_API = "https://work.enterprise.trae.cn"

CHECKIN_STATUS_PATH = "/trae/api/v2/ug/checkin_credits/status"
CHECKIN_CLAIM_PATH = "/trae/api/v2/ug/checkin_credits/claim"
USAGE_PATH = "/trae/api/v2/pay/ide_user_ent_usage"
EXCHANGE_PATH = "/trae/api/v3/oauth/ExchangeToken"
GET_USER_PATH = "/cloudide/api/v3/trae/GetUserInfo"
MODELS_PATH = "/api/remote/v1/models"
SESSIONS_PATH = "/api/remote/v1/chat_sessions"

AUTH_STORAGE_KEY = "iCubeAuthInfo://icube.cloudide"
AUTH_DEVICE_PREFIX = "iCubeAuthInfo://icube-dc:"
STORAGE_FILENAME = "storage.json"

# 消费端与企业端使用同一个 work 智能体，区别只在模型目录与计费侧
AGENT_ID = "solo_work_remote"
SESSION_MODE = "work"

# 消费端 solo_work_remote 模型目录（2026-10 实测）
STATIC_MODELS = (
    "qwen-3.7-plus",
    "Doubao-Seed-Evolving",
    "Doubao-Seed-2.1-Pro",
    "Doubao-Seed-2.1-Turbo",
    "step-5-preview",
    "glm-5.3",
    "glm-5.2",
    "deepseek-v4.1-flash",
    "DeepSeek-V4-Flash-Official",
    "DeepSeek-V4-Pro-Official",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.6",
    "minimax-m3",
    "qwen3.8-max",
    # solo_work_lite 时代的旧 id，保留兼容
    "qwen-3.5",
    "glm-5",
    "glm-5.1",
    "kimi-k2.5",
    "Doubao-Seed-2.0-Code",
)

# 企业端 solo_work_remote 模型目录（2026-10 实测）
ENTERPRISE_STATIC_MODELS = (
    "Doubao-Seed-2.1-pro",
    "Doubao-Seed-Evolving",
    "Doubao-Seed-2.1-turbo",
    "Doubao-Seed-2.0-Code",
    "step-5-preview",
    "glm-5.3",
    "glm-5.2",
    "minimax-m3",
    "minimax-m2.7",
    "kimi-k3",
    "kimi-k2.7-code",
    "qwen3.8-max",
    "DeepSeek-V4-Pro-Official",
    "deepseek-V4-Pro",
    "DeepSeek-V4-Flash-Official",
)

ENTERPRISE_DEFAULT_MODEL = "Doubao-Seed-2.1-pro"

ALIASES = {
    "auto": "qwen-3.7-plus",
}

USER_AGENT = "TRAE-SOLO-CN/0.1.56"


def route_mode() -> str:
    """enterprise / consumer / dual（默认 dual：按模型归属选端）。"""
    value = (os.environ.get("CB_TRAEWORK_ROUTE") or "").strip().lower()
    return value if value in ("enterprise", "consumer", "dual") else "dual"
