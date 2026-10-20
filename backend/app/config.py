"""运行配置。所有路径均可通过环境变量覆盖，默认本地单用户部署。"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_ROOT = BASE_DIR.parent                             # bajiu-review/

try:  # 本地开发可选 .env；Docker 由 compose 注入环境变量
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass

DATA_DIR = Path(os.getenv("BAJIU_DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("BAJIU_DB_PATH", str(DATA_DIR / "bajiu.db")))
DATABASE_URL = os.getenv("BAJIU_DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

FRONTEND_DIST = Path(
    os.getenv("BAJIU_FRONTEND_DIST", str(PROJECT_ROOT / "frontend" / "dist"))
)

APP_PASSWORD = os.getenv("APP_PASSWORD", "admin123")
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
TOKEN_TTL_MINUTES = int(os.getenv("BAJIU_TOKEN_TTL_MINUTES", "10080"))  # 7 天
SESSION_COOKIE = "bajiu_session"
CSRF_COOKIE = "bajiu_csrf"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "BAJIU_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

MAX_IMPORT_BYTES = int(os.getenv("BAJIU_MAX_IMPORT_BYTES", str(5 * 1024 * 1024)))
MAX_IMPORT_ROWS = int(os.getenv("BAJIU_MAX_IMPORT_ROWS", "2000"))

HOST = os.getenv("BAJIU_HOST", "127.0.0.1")
PORT = int(os.getenv("BAJIU_PORT", "8000"))

# GitHub 采集的 TLS 校验方式：
#   certifi（默认，内置 CA）| system（操作系统根证书；本机走 TLS 代理时用这个）
#   | none（不校验，仅排障用，存在中间人风险）
GITHUB_SSL_MODE = os.getenv("BAJIU_GITHUB_SSL", "certifi").strip().lower()
