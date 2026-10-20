from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CrawlSource, CrawlTask, PendingItem, ReviewSchedule
from app.services import crawler
from app.utils.text import normalize_text
from app.utils.timeutil import local_today


def _create_question(client: TestClient, **overrides) -> dict:
    payload = {
        "stem": "测试题目：TCP 为什么需要三次握手？",
        "answer": "确认双方收发能力，防止历史连接。",
        "key_points": ["确认收发能力", "防止历史连接"],
        "notes": "面试口诀：三次才稳。",
        "category_path": "计算机网络/TCP",
        "tags": ["TCP", "测试"],
        "companies": ["测试公司"],
        "difficulty": 3,
        "frequency": "high",
    }
    payload.update(overrides)
    response = client.post("/api/v1/questions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_auth_required(client: TestClient) -> None:
    response = client.get("/api/v1/questions")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_question_rating_same_day_and_stats(auth_client: TestClient) -> None:
    question = _create_question(auth_client)
    assert question["mastery"] == "unlearned"
    assert question["schedule"]["is_new"] is True
    assert question["tags"][0]["name"] in {"TCP", "测试"}

    listed = auth_client.get("/api/v1/questions", params={"q": "三次握手"}).json()
    assert listed["data"]["total"] >= 1

    response = auth_client.post(
        "/api/v1/ratings",
        json={"question_id": question["id"], "q": 5, "mode": "practice"},
    )
    assert response.status_code == 200, response.text
    rating = response.json()["data"]
    assert rating["schedule_applied"] is True
    assert rating["mastery"] == "mastered"
    assert rating["schedule"]["interval_days"] == 1
    expected_next = (local_today() + timedelta(days=1)).isoformat()
    assert rating["schedule"]["next_review_date"] == expected_next

    second = auth_client.post(
        "/api/v1/ratings",
        json={"question_id": question["id"], "q": 5, "mode": "practice"},
    ).json()["data"]
    assert second["schedule_applied"] is False
    assert second["schedule"]["interval_days"] == 1

    detail = auth_client.get(f"/api/v1/questions/{question['id']}").json()["data"]
    assert len(detail["history"]) == 2
    assert detail["history"][0]["q"] == 5

    dashboard = auth_client.get("/api/v1/stats/dashboard").json()["data"]
    assert dashboard["total_questions"] >= 1
    assert dashboard["learned"] >= 1
    assert dashboard["mastered"] >= 1
    assert dashboard["streak"] >= 1
    assert len(dashboard["trend"]) == 7

    removed = auth_client.delete(f"/api/v1/questions/{question['id']}")
    assert removed.status_code == 200
    listed_after = auth_client.get(
        "/api/v1/questions", params={"q": "三次握手"}
    ).json()["data"]
    assert listed_after["total"] == 0


def test_review_queue_and_same_day_exclusion(auth_client: TestClient) -> None:
    question = _create_question(auth_client, stem="复习队列测试题：进程和线程的区别？")
    auth_client.post(
        "/api/v1/ratings", json={"question_id": question["id"], "q": 5}
    )
    # 手动把排程改到今天，验证同一题评分后不再进入今日队列。
    with SessionLocal() as db:
        schedule = db.get(ReviewSchedule, question["id"])
        schedule.next_review_date = local_today().isoformat()
        db.commit()
    payload = auth_client.get("/api/v1/review/today").json()["data"]
    assert all(item["id"] != question["id"] for item in payload["due"])


def test_markdown_import_pending_approve(auth_client: TestClient) -> None:
    markdown = """## 题目：导入测试：什么是 B+ 树？
**答案**：B+ 树是平衡多路搜索树，适合范围查询。
**要点**：矮胖结构；叶子链表
**标签**：数据库,索引
**难度**：4
**频率**：high
**公司**：测试公司
**分类**：数据库/索引

## 知识：B+ 树
**类型**：principle
**分类**：数据库/索引
**别名**：B+Tree
**内容**：B+ 树非叶子节点只存索引，叶子节点用链表连接，适合磁盘范围扫描。
"""
    response = auth_client.post(
        "/api/v1/import/markdown",
        files={"file": ("import-test.md", markdown.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["batch"]["ok_rows"] == 2
    assert data["errors"] == []

    pending = auth_client.get(
        "/api/v1/pending", params={"item_type": "question", "status": "pending"}
    ).json()["data"]
    item = next(
        row
        for row in pending["items"]
        if row["stem"] == normalize_text("导入测试：什么是 B+ 树？")
    )
    approve = auth_client.post(
        f"/api/v1/pending/{item['id']}/approve", json={}
    )
    assert approve.status_code == 200, approve.text
    created = approve.json()["data"]
    assert created["status"] == "active"
    assert created["category_path"] == "数据库/索引"
    assert created["origins"][0]["origin_ref"].startswith("import-test.md:")
    assert created["difficulty"] == 4

    pending_knowledge = auth_client.get(
        "/api/v1/pending", params={"item_type": "knowledge", "status": "pending"}
    ).json()["data"]
    knowledge_item = next(
        row for row in pending_knowledge["items"] if row["knowledge_title"] == "B+ 树"
    )
    knowledge_approve = auth_client.post(
        f"/api/v1/pending/{knowledge_item['id']}/approve", json={}
    )
    assert knowledge_approve.status_code == 200, knowledge_approve.text
    knowledge = knowledge_approve.json()["data"]
    assert knowledge["kind"] == "principle"
    assert knowledge["category_path"] == "数据库/索引"


def test_combined_json_link_resolution(auth_client: TestClient) -> None:
    payload = {
        "schema_version": 1,
        "questions": [
            {
                "stem": "组合导入：RAG 的基本流程？",
                "answer": "切分、向量化、检索、生成。",
                "key_points": ["切分", "检索"],
                "category_path": ["AI-Agent", "RAG"],
                "tags": ["RAG"],
            }
        ],
        "knowledge": [
            {
                "ref": "kp-rag-flow",
                "title": "RAG 流程",
                "content": "离线切分与向量化，在线检索并拼接 Prompt 生成。",
                "kind": "process",
                "category_path": ["AI-Agent", "RAG"],
                "aliases": ["检索增强流程"],
            }
        ],
        "links": [
            {
                "question_index": 0,
                "knowledge_ref": "kp-rag-flow",
                "relation_type": "related",
            }
        ],
    }
    response = auth_client.post(
        "/api/v1/import/json",
        files={
            "file": (
                "combined.json",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["warnings"] == []

    pending = auth_client.get(
        "/api/v1/pending", params={"status": "pending"}
    ).json()["data"]["items"]
    question_item = next(row for row in pending if row["item_type"] == "question")
    knowledge_item = next(row for row in pending if row["item_type"] == "knowledge")

    k_approve = auth_client.post(
        f"/api/v1/pending/{knowledge_item['id']}/approve", json={}
    )
    assert k_approve.status_code == 200, k_approve.text
    q_approve = auth_client.post(
        f"/api/v1/pending/{question_item['id']}/approve", json={}
    )
    assert q_approve.status_code == 200, q_approve.text
    question = q_approve.json()["data"]
    assert len(question["knowledge"]) == 1
    assert question["knowledge"][0]["title"] == "RAG 流程"
    assert question["knowledge"][0]["relation_type"] == "related"


def test_export_import_roundtrip(auth_client: TestClient) -> None:
    question = _create_question(
        auth_client,
        stem="回环测试：MySQL 索引为什么用 B+ 树？",
        answer="支持范围查询，磁盘 IO 少。",
        key_points=["范围查询", "磁盘 IO"],
        notes="回环笔记",
        category_path="数据库/索引",
        tags=["MySQL", "索引"],
        companies=["阿里"],
        difficulty=4,
        frequency="high",
    )
    knowledge_response = auth_client.post(
        "/api/v1/knowledge",
        json={
            "title": "回环测试知识：B+ 树",
            "content": "B+ 树叶子节点链表连接，适合范围扫描。",
            "kind": "principle",
            "category_path": "数据库/索引",
            "aliases": ["B+Tree"],
        },
    )
    assert knowledge_response.status_code == 200, knowledge_response.text
    knowledge = knowledge_response.json()["data"]
    link = auth_client.post(
        f"/api/v1/questions/{question['id']}/knowledge",
        json={"knowledge_id": knowledge["id"], "relation_type": "prerequisite"},
    )
    assert link.status_code == 200

    export_response = auth_client.get("/api/v1/export", params={"format": "json"})
    assert export_response.status_code == 200
    exported = json.loads(export_response.content.decode("utf-8"))
    exported_question = next(
        row for row in exported["questions"] if row["stem"] == question["stem"]
    )
    assert exported_question["notes"] == "回环笔记"
    assert exported_question["companies"] == ["阿里"]
    assert exported["links"]

    auth_client.delete(f"/api/v1/questions/{question['id']}")
    auth_client.delete(f"/api/v1/knowledge/{knowledge['id']}")

    import_response = auth_client.post(
        "/api/v1/import/json",
        files={
            "file": (
                "roundtrip.json",
                json.dumps(exported, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
        },
    )
    assert import_response.status_code == 200, import_response.text

    pending = auth_client.get(
        "/api/v1/pending", params={"status": "pending", "page_size": 100}
    ).json()["data"]["items"]
    question_item = next(
        row
        for row in pending
        if row["item_type"] == "question" and row["stem"] == question["stem"]
    )
    knowledge_item = next(
        row
        for row in pending
        if row["item_type"] == "knowledge"
        and row["knowledge_title"] == knowledge["title"]
    )
    auth_client.post(f"/api/v1/pending/{knowledge_item['id']}/approve", json={})
    q_approve = auth_client.post(
        f"/api/v1/pending/{question_item['id']}/approve", json={}
    )
    assert q_approve.status_code == 200, q_approve.text
    restored = q_approve.json()["data"]
    assert restored["answer"] == "支持范围查询，磁盘 IO 少。"
    assert set(restored["key_points"]) == {"范围查询", "磁盘 IO"}
    assert {tag["name"] for tag in restored["tags"]} == {"MySQL", "索引"}
    assert restored["companies"][0]["name"] == "阿里"
    assert restored["category_path"] == "数据库/索引"
    assert restored["difficulty"] == 4
    assert restored["notes"] == "回环笔记"
    assert restored["knowledge"][0]["relation_type"] == "prerequisite"


def test_mistakes_and_bookmarks(auth_client: TestClient) -> None:
    question = _create_question(auth_client, stem="错题测试：什么是死锁？")
    rated = auth_client.post(
        "/api/v1/ratings", json={"question_id": question["id"], "q": 2}
    ).json()["data"]
    assert rated["mistake_added"] is True
    mistakes = auth_client.get("/api/v1/mistakes").json()["data"]
    assert mistakes["total"] == 1
    assert mistakes["items"][0]["id"] == question["id"]
    removed = auth_client.post(
        f"/api/v1/mistakes/{question['id']}/remove"
    ).json()["data"]
    assert removed["removed"] is True
    assert auth_client.get("/api/v1/mistakes").json()["data"]["total"] == 0

    auth_client.post("/api/v1/bookmarks", json={"question_id": question["id"]})
    bookmarks = auth_client.get("/api/v1/bookmarks").json()["data"]
    assert bookmarks["total"] == 1
    auth_client.delete(f"/api/v1/bookmarks/{question['id']}")
    assert auth_client.get("/api/v1/bookmarks").json()["data"]["total"] == 0


def test_settings_ef_initial_applies_to_new_question(auth_client: TestClient) -> None:
    updated = auth_client.patch("/api/v1/settings", json={"sm2.ef_initial": 2.0})
    assert updated.status_code == 200
    question = _create_question(auth_client, stem="EF 初值测试题")
    rating = auth_client.post(
        "/api/v1/ratings", json={"question_id": question["id"], "q": 4}
    ).json()["data"]
    assert rating["schedule_applied"] is True
    assert rating["schedule"]["ef"] == 2.0


def test_settings_and_tag_rules(auth_client: TestClient) -> None:
    settings = auth_client.get("/api/v1/settings").json()["data"]
    assert settings["sm2.interval_cap_days"] == 90
    updated = auth_client.patch(
        "/api/v1/settings", json={"sm2.daily_new_limit": 30}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["sm2.daily_new_limit"] == 30
    invalid = auth_client.patch(
        "/api/v1/settings", json={"sm2.interval_cap_days": 9999}
    )
    assert invalid.status_code == 400

    rules = auth_client.get("/api/v1/tag-rules").json()["data"]
    assert len(rules) >= 5
    created = auth_client.post(
        "/api/v1/tag-rules",
        json={"keyword": "Kubernetes", "tag_ids": [], "frequency": "mid"},
    )
    assert created.status_code == 200
    rule_id = created.json()["data"]["ids"][0]
    assert auth_client.delete(f"/api/v1/tag-rules/{rule_id}").status_code == 200


def test_backup_restore_roundtrip(auth_client: TestClient) -> None:
    first = _create_question(auth_client, stem="备份恢复保留题")
    export = auth_client.post("/api/v1/backup/export")
    assert export.status_code == 200
    second = _create_question(auth_client, stem="备份恢复后应消失题")
    assert second["id"] != first["id"]

    restore = auth_client.post(
        "/api/v1/backup/import",
        files={"file": ("backup.db", export.content, "application/octet-stream")},
        data={"confirm": "true"},
    )
    assert restore.status_code == 200, restore.text
    kept = auth_client.get(
        "/api/v1/questions", params={"q": "备份恢复保留题"}
    ).json()["data"]
    assert kept["total"] == 1
    gone = auth_client.get(
        "/api/v1/questions", params={"q": "备份恢复后应消失题"}
    ).json()["data"]
    assert gone["total"] == 0


def test_pending_suggested_knowledge_can_be_linked(auth_client: TestClient) -> None:
    knowledge = auth_client.post(
        "/api/v1/knowledge",
        json={
            "title": "关联建议：死锁四条件",
            "content": "互斥、持有并等待、不可剥夺、循环等待。",
            "kind": "principle",
            "category_path": "后端开发/操作系统/并发",
        },
    ).json()["data"]
    markdown = """## 题目：关联建议测试：死锁的四个必要条件是什么？
**答案**：互斥、持有并等待、不可剥夺、循环等待。
**标签**：死锁
**分类**：后端开发/操作系统/并发
"""
    imported = auth_client.post(
        "/api/v1/import/markdown",
        files={
            "file": (
                "suggest-knowledge.md",
                markdown.encode("utf-8"),
                "text/markdown",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    pending = auth_client.get(
        "/api/v1/pending",
        params={"item_type": "question", "status": "pending", "page_size": 100},
    ).json()["data"]["items"]
    item = next(row for row in pending if row["stem"] and "关联建议测试" in row["stem"])
    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    suggested = [row["id"] for row in detail.get("suggested_knowledge", [])]
    assert knowledge["id"] in suggested

    approved = auth_client.post(
        f"/api/v1/pending/{item['id']}/approve",
        json={"knowledge_ids": [knowledge["id"]]},
    )
    assert approved.status_code == 200, approved.text
    question = approved.json()["data"]
    assert any(link["id"] == knowledge["id"] for link in question["knowledge"])


def test_pending_duplicate_approve_then_merge(auth_client: TestClient) -> None:
    markdown = """## 题目：合并测试：什么是线程安全？
**答案**：另一个来源给出的答案。
**标签**：并发
**分类**：后端开发/操作系统/并发
"""
    response = auth_client.post(
        "/api/v1/import/markdown",
        files={"file": ("merge-test.md", markdown.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 200, response.text
    pending = auth_client.get(
        "/api/v1/pending",
        params={"item_type": "question", "status": "pending", "page_size": 100},
    ).json()["data"]["items"]
    item = next(
        row
        for row in pending
        if row["stem"] and "合并测试" in row["stem"] and row["status"] == "pending"
    )

    # 待审项创建之后，正式题库里又出现同题，通过时应当提示合并。
    existing = _create_question(
        auth_client,
        stem="合并测试：什么是线程安全？",
        answer="多线程访问共享资源结果一致。",
    )
    approve = auth_client.post(f"/api/v1/pending/{item['id']}/approve", json={})
    assert approve.status_code == 409
    assert approve.json()["data"]["question_id"] == existing["id"]

    merged = auth_client.post(
        f"/api/v1/pending/{item['id']}/merge",
        json={"target_type": "question", "target_id": existing["id"]},
    )
    assert merged.status_code == 200, merged.text
    detail = auth_client.get(f"/api/v1/questions/{existing['id']}").json()["data"]
    refs = [origin["origin_ref"] for origin in detail["origins"]]
    assert any(ref and ref.startswith("merge-test.md:") for ref in refs)
    after = auth_client.get(
        "/api/v1/pending",
        params={"item_type": "question", "status": "merged", "page_size": 100},
    ).json()["data"]["items"]
    assert any(row["id"] == item["id"] for row in after)


def test_backup_export(auth_client: TestClient) -> None:
    _create_question(auth_client, stem="备份测试题")
    response = auth_client.post("/api/v1/backup/export")
    assert response.status_code == 200
    assert response.content.startswith(b"SQLite format 3\x00")
    backups = auth_client.get("/api/v1/backup/list").json()["data"]
    assert backups
    bad = auth_client.post(
        "/api/v1/backup/import",
        files={"file": ("bad.db", b"not a database", "application/octet-stream")},
        data={"confirm": "true"},
    )
    assert bad.status_code == 400


def test_crawl_parse_and_dry_run(client: TestClient, monkeypatch) -> None:
    assert crawler.parse_github_source("https://github.com/owner/repo").owner == "owner"
    assert crawler.parse_github_source(
        "https://github.com/owner/repo/tree/main/docs"
    ).path == "docs"
    try:
        crawler.parse_github_source("https://evil.example.com/repo")
        raise AssertionError("应拒绝非白名单 URL")
    except Exception as exc:  # ApiError
        assert "github" in str(exc)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def list_files(self, _target, _max_files):
            return ["https://raw.githubusercontent.com/owner/repo/main/a.md"]

        def fetch_text(self, _url):
            return 200, """## 题目：爬虫测试题：HTTPS 和 HTTP 的区别？
**答案**：HTTPS 多了 TLS 加密。
**标签**：HTTPS,网络
**难度**：2
**频率**：high

## 知识：TLS
**类型**：concept
**内容**：TLS 负责加密、身份认证与完整性校验。
"""

    monkeypatch.setattr(crawler, "GitHubClient", FakeClient)
    with SessionLocal() as db:
        source = CrawlSource(
            name="fixture",
            source_kind="github",
            url="https://github.com/owner/repo",
            interval_sec=0,
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
        assert task.status == "success"
        assert task.success_files == 1
        pending = db.scalars(select(PendingItem)).all()
        assert any(item.stem and "HTTPS" in item.stem for item in pending)
        assert any(
            item.knowledge_title == "TLS" for item in pending
        )


def test_mistake_markdown_export(auth_client: TestClient) -> None:
    question = _create_question(auth_client, stem="错题导出：HTTP 与 HTTPS 的区别？")
    auth_client.post("/api/v1/ratings", json={"question_id": question["id"], "q": 2})
    response = auth_client.get("/api/v1/mistakes/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert text.startswith("# 错题本")
    # 题干入库时经过 NFKC 归一化，全角冒号会变为半角。
    assert "错题导出:HTTP 与 HTTPS 的区别?" in text
    assert "**答案**：确认双方收发能力，防止历史连接。" in text
    assert "自评不熟自动收录" in text
    assert "**掌握度**：unfamiliar" in text

    auth_client.post(f"/api/v1/mistakes/{question['id']}/remove")
    empty = auth_client.get("/api/v1/mistakes/export").content.decode("utf-8")
    assert "共 0 道" in empty
