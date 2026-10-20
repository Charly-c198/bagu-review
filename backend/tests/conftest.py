from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 必须在导入 app 之前设置数据目录，确保测试使用独立数据库。
TEST_DIR = Path(tempfile.mkdtemp(prefix="bajiu-test-"))
os.environ["BAJIU_DB_PATH"] = str(TEST_DIR / "test.db")
os.environ["BAJIU_DATA_DIR"] = str(TEST_DIR)
os.environ["APP_USERNAME"] = "admin"
os.environ["APP_PASSWORD"] = "admin123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import DB_PATH  # noqa: E402
from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import ensure_default_user, login_limiter  # noqa: E402
from app.services.tagging import load_seed_rules  # noqa: E402


@pytest.fixture()
def client():
    # 直接重建数据库文件，避免 SQLite 外键导致的自引用表 drop 顺序问题。
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    init_db()
    ensure_default_user()
    with login_limiter._lock:
        login_limiter._attempts.clear()
        login_limiter._failures.clear()
        login_limiter._locked_until.clear()
    db = SessionLocal()
    try:
        load_seed_rules(db)
    finally:
        db.close()
    test_client = TestClient(app)
    yield test_client
    test_client.close()


@pytest.fixture()
def auth_client(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
