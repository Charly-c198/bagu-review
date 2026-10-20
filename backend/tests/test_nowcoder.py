"""牛客公开页爬虫（M2）验收：URL/robots、HTML 提取、任务管线。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import ApiError
from app.models import CrawlSource, CrawlTask, CrawlTaskFile, PendingItem
from app.services import crawler
from app.services.nowcoder import (
    NowcoderClient,
    NowcoderTarget,
    extract_post,
    parse_nowcoder_post,
    parse_nowcoder_source,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nowcoder_post.html"


def test_nowcoder_source_validation() -> None:
    assert parse_nowcoder_source("https://www.nowcoder.com/discuss/123").kind == "post"
    assert (
        parse_nowcoder_source("https://www.nowcoder.com/sitemap1.xml").kind == "sitemap"
    )
    for bad in (
        "https://evil.example.com/discuss/1",
        "http://www.nowcoder.com/discuss/1",
        "https://www.nowcoder.com/discuss",
    ):
        with pytest.raises(ApiError):
            parse_nowcoder_source(bad)


def test_nowcoder_extract_and_parse() -> None:
    title, body = extract_post(FIXTURE.read_text(encoding="utf-8"))
    assert "后端面经" in title
    assert "TCP 三次握手" in body
    result = parse_nowcoder_post(f"# {title}\n\n{body}")
    assert len(result.questions) == 2
    tcp = next(q for q in result.questions if "三次握手" in q.stem)
    assert "防止历史" in tcp.answer
    assert tcp.confidence >= 0.6
    assert any("缓存雪崩" in item.title for item in result.knowledge)


def test_nowcoder_robots_disallow(monkeypatch) -> None:
    client = NowcoderClient()
    monkeypatch.setattr(client, "_disallow_rules", lambda: ["/discuss/private"])
    with pytest.raises(ApiError):
        client.check_robots(
            NowcoderTarget(
                kind="post", url="https://www.nowcoder.com/discuss/private/1"
            )
        )
    client.check_robots(
        NowcoderTarget(kind="post", url="https://www.nowcoder.com/discuss/123")
    )
    client.close()


class FakeNowcoderClient:
    def __init__(self, posts: dict[str, str], **_kwargs) -> None:
        self.posts = posts

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def check_robots(self, _target) -> None:
        return None

    def list_files(self, _target, max_files):
        return list(self.posts)[:max_files]

    def fetch_post(self, url):
        text = self.posts[url]
        return 200, "夹具帖子", text


def test_nowcoder_run_task(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)
    markdown = (
        "# 测试面经\n\n"
        "## 题目：Redis 持久化 RDB 和 AOF 的区别？\n"
        "**答案**：RDB 快照恢复快，AOF 日志更完整。\n"
    )
    posts = {
        f"https://www.nowcoder.com/discuss/{index}": markdown for index in (101, 102, 103)
    }
    monkeypatch.setattr(
        crawler, "NowcoderClient", lambda **_kwargs: FakeNowcoderClient(posts)
    )
    with SessionLocal() as db:
        source = CrawlSource(
            name="nowcoder-fixture",
            source_kind="nowcoder",
            url="https://www.nowcoder.com/discuss/101",
            interval_sec=1,
            timeout_sec=5,
            max_retries=1,
        )
        db.add(source)
        db.flush()
        task = CrawlTask(source_id=source.id, status="pending")
        db.add(task)
        db.commit()
        task_id = task.id

    crawler.run_task(task_id)
    with SessionLocal() as db:
        task = db.get(CrawlTask, task_id)
        assert task.status == "success", task.log
        assert task.total_files == 3
        assert task.success_files == 3
        files = db.scalars(
            select(CrawlTaskFile).where(CrawlTaskFile.task_id == task_id)
        ).all()
        assert all(row.status == "success" for row in files)
        assert all(row.cached_path and Path(row.cached_path).exists() for row in files)
        pending = db.scalars(
            select(PendingItem).where(PendingItem.source_type == "crawler")
        ).all()
        assert any(item.stem and "Redis 持久化" in item.stem for item in pending)
