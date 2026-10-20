"""500 题规模下的列表性能验收（文档 1.3 / 11.1 W2：筛选 ≤200ms）。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.database import SessionLocal, engine
from app.models import (
    Bookmark,
    Category,
    Company,
    MistakeBook,
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionTag,
    ReviewSchedule,
    Tag,
)
from app.utils.text import question_hash, simhash64

TOPICS = ["Java", "Python", "MySQL", "Redis", "网络", "操作系统", "JVM", "算法"]
KINDS = ["概念", "原理", "流程", "对比", "易错点"]


def _seed_500() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Question.id).limit(1)):
            return
        root = Category(name="性能测试板块", level=1, sort_order=1)
        db.add(root)
        db.flush()
        stack = Category(name="性能测试技术栈", level=2, parent_id=root.id)
        db.add(stack)
        db.flush()
        points = [Category(name=topic, level=3, parent_id=stack.id) for topic in TOPICS]
        tags = [Tag(name=f"tag-{i}") for i in range(40)]
        companies = [Company(name=f"公司{i}") for i in range(20)]
        db.add_all([*points, *tags, *companies])
        db.flush()
        for i in range(500):
            stem = f"第 {i} 题：{TOPICS[i % len(TOPICS)]} 的 {KINDS[i % len(KINDS)]} 考点是什么？"
            question = Question(
                stem=stem,
                answer=f"参考答案 {i}",
                difficulty=(i % 5) + 1,
                frequency=("high", "mid", "low")[i % 3],
                status="active",
                source_type=("manual", "import", "crawler")[i % 3],
                content_hash=question_hash(stem),
                simhash=simhash64(stem),
            )
            db.add(question)
            db.flush()
            db.add(QuestionCategory(question_id=question.id, category_id=points[i % len(points)].id))
            db.add(QuestionTag(question_id=question.id, tag_id=tags[i % len(tags)].id))
            db.add(QuestionCompany(question_id=question.id, company_id=companies[i % len(companies)].id))
            schedule = ReviewSchedule(question_id=question.id)
            if i % 2 == 0:
                schedule.last_q = (2, 4, 5)[i % 3]
                schedule.first_reviewed_at = "2026-01-01"
                schedule.next_review_date = "2000-01-01"
            db.add(schedule)
            if i % 10 == 0:
                db.add(Bookmark(question_id=question.id))
            if i % 7 == 0:
                db.add(MistakeBook(question_id=question.id, action="added", reason="unfamiliar"))
        db.commit()


def _count_queries(fn):
    counter = {"n": 0}

    def _before(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return counter["n"], result


def _list_timed(client: TestClient):
    start = time.perf_counter()
    response = client.get("/api/v1/questions", params={"page_size": 100})
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert response.status_code == 200, response.text
    return response.json()["data"], elapsed_ms


def test_question_list_performance_and_query_count(auth_client: TestClient) -> None:
    _seed_500()

    _list_timed(auth_client)  # 预热：首次请求含 ORM/连接初始化
    queries, (data, elapsed_ms) = _count_queries(lambda: _list_timed(auth_client))

    assert data["total"] >= 500
    items = data["items"]
    assert len(items) == 100
    for key in ("tags", "companies", "categories", "schedule", "bookmarked", "in_mistake"):
        assert key in items[0]

    # count + 列表 + 分类映射 + 排程 + 收藏 + 错题 + 标签 + 公司 + 分类 关联
    assert queries <= 12, f"列表出现 N+1：{queries} 次查询"
    assert elapsed_ms < 200, f"500 题筛选耗时 {elapsed_ms:.0f}ms，超过 200ms"


def test_filtered_list_matches_detail_fields(auth_client: TestClient) -> None:
    _seed_500()
    response = auth_client.get(
        "/api/v1/questions", params={"page_size": 5, "mastery": "mastered"}
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert items
    assert all(item["mastery"] == "mastered" for item in items)
    first = items[0]
    detail = auth_client.get(f"/api/v1/questions/{first['id']}").json()["data"]
    for key in (
        "stem",
        "mastery",
        "category_path",
        "tags",
        "companies",
        "bookmarked",
        "in_mistake",
    ):
        assert detail[key] == first[key], key