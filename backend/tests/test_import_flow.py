"""导入与去重闭环测试：CSV 逐行错误、文件哈希提示、SimHash 近似重复、待审批量通过、精确重复审计。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PendingItem, Question
from app.services.import_parsers import (
    ParsedKnowledge,
    ParsedQuestion,
    ParseResult,
    parse_csv,
)
from app.services.ingest import ingest_parse_result

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def _md(questions: list[tuple[str, str]]) -> bytes:
    text = "\n\n".join(
        f"## 题目：{stem}\n**答案**：{answer}\n**标签**：测试\n**难度**：3\n**频率**：mid"
        for stem, answer in questions
    )
    return text.encode("utf-8")


def test_parse_csv_keeps_row_errors_and_content() -> None:
    text = (SEED_DIR / "sample_import.csv").read_text(encoding="utf-8-sig")
    parsed = parse_csv(text)
    assert len(parsed.questions) == 8
    assert parsed.total_rows == 9
    assert len(parsed.errors) == 1
    assert parsed.errors[0]["record"] == 3
    first = parsed.questions[0]
    assert "三次握手" in first.stem
    assert first.tags == ["TCP", "计算机网络"]
    assert first.difficulty == 3
    assert first.frequency == "high"


def test_csv_import_api_reports_partial_batch(auth_client: TestClient) -> None:
    content = (SEED_DIR / "sample_import.csv").read_bytes()
    response = auth_client.post(
        "/api/v1/import/csv", files={"file": ("sample.csv", content, "text/csv")}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    batch = data["batch"]
    assert batch["format"] == "csv"
    assert batch["ok_rows"] == 8
    assert batch["fail_rows"] == 1
    assert batch["status"] == "partial"
    assert data["errors"] and data["errors"][0]["record"] == 3
    with SessionLocal() as db:
        pending = db.scalars(
            select(PendingItem).where(PendingItem.import_batch_id == batch["id"])
        ).all()
        assert len(pending) == 8
        assert all(item.item_type == "question" for item in pending)


def test_same_file_reimport_warns_and_merges(auth_client: TestClient) -> None:
    content = _md([("测试重复题 A：什么是测试重复？", "答案 A")])
    first = auth_client.post(
        "/api/v1/import/markdown", files={"file": ("a.md", content, "text/markdown")}
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["batch"]["status"] == "success"
    assert first.json()["data"]["batch"]["ok_rows"] == 1

    second = auth_client.post(
        "/api/v1/import/markdown", files={"file": ("a.md", content, "text/markdown")}
    )
    assert second.status_code == 200, second.text
    data = second.json()["data"]
    assert data["batch"]["ok_rows"] == 1
    messages = [w["message"] for w in data["warnings"]]
    assert any("相同文件此前已导入过" in m for m in messages)

    batches = auth_client.get("/api/v1/import/batches").json()["data"]["items"]
    assert batches[0]["file_hash"] == batches[1]["file_hash"]
    with SessionLocal() as db:
        merged = db.scalars(select(PendingItem).where(PendingItem.status == "merged")).all()
        assert len(merged) == 1
        assert merged[0].dup_of_pending_id is not None


def test_simhash_near_duplicate_links_to_pending(auth_client: TestClient) -> None:
    auth_client.post(
        "/api/v1/import/markdown",
        files={"file": ("p1.md", _md([("TCP 握手几次", "三次")]), "text/markdown")},
    )
    # SimHash 对个别改动可能差出 10+ 位；这里把阈值调大，专门验证“近似”链路本身。
    saved = auth_client.patch("/api/v1/settings", json={"dedupe.simhash_threshold": 20})
    assert saved.status_code == 200, saved.text

    second = auth_client.post(
        "/api/v1/import/markdown",
        files={"file": ("p2.md", _md([("TCP 握手需要几次呢", "三次")]), "text/markdown")},
    )
    assert second.status_code == 200, second.text
    warnings = [w["message"] for w in second.json()["data"]["warnings"]]
    assert any("近似" in m for m in warnings), warnings

    with SessionLocal() as db:
        items = db.scalars(
            select(PendingItem)
            .where(PendingItem.item_type == "question")
            .order_by(PendingItem.id)
        ).all()
        assert len(items) == 2
        assert items[0].dup_of_pending_id is None
        assert items[1].dup_of_pending_id == items[0].id


def test_bulk_approve_reports_per_item_result(auth_client: TestClient) -> None:
    created = auth_client.post(
        "/api/v1/pending/bulk-approve", json={"ids": []}
    )
    assert created.status_code == 200
    assert created.json()["data"]["results"] == []

    md = _md([("批量审核测试题：待审批量通过是否保留来源？", "会保留")])
    auth_client.post(
        "/api/v1/import/markdown", files={"file": ("bulk.md", md, "text/markdown")}
    )
    auth_client.post(
        "/api/v1/import/markdown",
        files={"file": ("bulk2.md", _md([("批量审核测试题第二道？", "是")]), "text/markdown")},
    )
    with SessionLocal() as db:
        ids = list(
            db.scalars(
                select(PendingItem.id).where(PendingItem.status == "pending").order_by(PendingItem.id)
            ).all()
        )
    assert len(ids) == 2

    # 同一 id 提交两次：第一次通过，第二次返回“已处理”，整批不失败。
    result = auth_client.post("/api/v1/pending/bulk-approve", json={"ids": [ids[0], ids[0]]})
    assert result.status_code == 200, result.text
    rows = result.json()["data"]["results"]
    assert rows[0]["ok"] is True
    assert rows[0]["question_id"]
    assert rows[1]["ok"] is False

    with SessionLocal() as db:
        question = db.get(Question, rows[0]["question_id"])
        assert question is not None and question.source_type == "import"
        assert db.get(PendingItem, ids[0]).status == "approved"
        assert db.get(PendingItem, ids[1]).status == "pending"


def test_ingest_exact_duplicate_creates_merge_audit_row() -> None:
    stem = "精确重复审计题：同一题干重复导入"
    title = "精确重复审计知识"
    content = "同样的知识内容重复导入时会产生 merged 审计行。"
    with SessionLocal() as db:
        first = ParseResult(
            questions=[ParsedQuestion(stem=stem, answer="答案")],
            knowledge=[ParsedKnowledge(title=title, content=content)],
            total_rows=2,
        )
        outcome = ingest_parse_result(db, first, source_type="import", origin_prefix="t1")
        db.commit()
        assert outcome.pending_created == 2

        again = ParseResult(
            questions=[ParsedQuestion(stem=stem, answer="答案")],
            knowledge=[ParsedKnowledge(title=title, content=content)],
            total_rows=2,
        )
        second = ingest_parse_result(db, again, source_type="import", origin_prefix="t2")
        db.commit()
        assert second.duplicates == 2
        merged = db.scalars(select(PendingItem).where(PendingItem.status == "merged")).all()
        assert len(merged) == 2
        assert all(item.dup_of_pending_id for item in merged)
        assert {item.item_type for item in merged} == {"question", "knowledge"}