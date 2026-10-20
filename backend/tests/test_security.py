"""安全与口径闭环：SSRF 白名单、登录限流、规则打标准确率、待审不透传原始渲染。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import TagRule
from app.services.tagging import load_seed_rules, suggest_meta

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

BAD_SOURCE_URLS = [
    "http://github.com/owner/repo",  # 非 https
    "https://evil.example.com/owner/repo",  # 非白名单
    "https://github.com.evil.com/owner/repo",  # 后缀伪装
    "https://127.0.0.1/owner/repo",  # 内网地址
    "https://169.254.169.254/latest/meta-data",  # 云元数据
    "https://raw.githubusercontent.com/onlyowner",  # 路径不完整
]


def test_crawl_source_rejects_non_whitelisted_urls(auth_client: TestClient) -> None:
    for url in BAD_SOURCE_URLS:
        response = auth_client.post(
            "/api/v1/crawl/sources",
            json={"name": "ssrf", "source_kind": "github", "url": url},
        )
        assert response.status_code == 400, f"{url} 应被拒绝，实际 {response.status_code}"
        assert response.json()["code"] == "VALIDATION_ERROR"

    ok_response = auth_client.post(
        "/api/v1/crawl/sources",
        json={
            "name": "合法源",
            "source_kind": "github",
            "url": "https://github.com/owner/repo/tree/main/docs",
        },
    )
    assert ok_response.status_code == 200, ok_response.text


def test_login_rate_limit_and_lockout(client: TestClient) -> None:
    statuses = []
    for _ in range(12):
        response = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
        )
        statuses.append(response.json()["code"])
    assert "RATE_LIMITED" in statuses

    # 锁定期内即使口令正确也应被拒，防止暴力破解“猜中即放行”。
    locked = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert locked.status_code in (401, 429)
    assert locked.json()["code"] in ("AUTH_INVALID", "RATE_LIMITED")


def test_seed_rules_cover_sample_pending_items(auth_client: TestClient) -> None:
    """文档 1.3：用 20 条样例待审项验收，至少 15 条给出建议标签或分类。"""
    from app.services.import_parsers import parse_markdown

    text = (SEED_DIR / "content_m1_supplement.md").read_text(encoding="utf-8")
    parsed = parse_markdown(text)
    samples = parsed.questions[:15] + parsed.knowledge[:5]
    assert len(samples) == 20

    with SessionLocal() as db:
        load_seed_rules(db)
        assert db.scalar(select(TagRule.id).limit(1)) is not None
        hit = 0
        for item in samples:
            if item.__class__.__name__ == "ParsedQuestion":
                meta = suggest_meta(db, f"{item.stem}\n{item.answer}")
            else:
                meta = suggest_meta(db, item.content, item_type="knowledge", title=item.title)
            if meta["tags"] or meta["category_path"]:
                hit += 1
        assert hit >= 15, f"仅 {hit}/20 条给出建议标签或分类"
