"""M3a Slice 2/3：AI 打标建议、错题解析、答案润色与题库生产。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import ApiError
from app.services.ai import suggestions as suggestions_service


class FakeGateway:
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def complete_json(self, **_kwargs):  # noqa: ANN003
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _pending_knowledge(auth_client: TestClient, title: str = "Zeta 待审样例") -> dict:
    response = auth_client.post(
        "/api/v1/knowledge",
        json={
            "title": title,
            "content": "Zeta 内容样例，用于 AI 打标建议测试。",
            "send_to_pending": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item"]


def _question(
    auth_client: TestClient,
    stem: str = "M3 润色测试：TCP 三次握手为什么需要三次？",
    answer: str = "为了确认双方收发能力并同步初始序列号。",
    key_points: list[str] | None = None,
    **extra,
) -> dict:
    payload = {
        "stem": stem,
        "answer": answer,
        "key_points": key_points or ["确认收发能力", "同步序列号"],
        **extra,
    }
    response = auth_client.post("/api/v1/questions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _tag_result() -> dict:
    return {
        "category_path": "Zeta测试/网络/TCP",
        "tags": ["TCP", "握手"],
        "difficulty": 3,
        "frequency": "high",
        "confidence": 0.82,
        "rationale": "题干围绕 TCP 握手。",
    }


def test_tag_suggestion_success_and_apply(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    item = _pending_knowledge(auth_client)
    before = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    fake = FakeGateway(result=_tag_result())
    monkeypatch.setattr(suggestions_service, "get_ai_gateway", lambda _db: fake)

    response = auth_client.post(
        "/api/v1/ai/suggestions",
        json={"kind": "tagging", "target_type": "pending", "target_id": item["id"]},
    )
    assert response.status_code == 200, response.text
    suggestion = response.json()["data"]
    assert suggestion["status"] == "success"
    assert suggestion["result"]["tags"] == ["TCP", "握手"]
    assert suggestion["prompt_version_id"]

    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["ai_suggestions"][0]["kind"] == "tagging"
    # 生成建议本身不修改建议元数据。
    assert detail["suggested_meta"] == before["suggested_meta"]

    applied = auth_client.post(f"/api/v1/ai/suggestions/{suggestion['id']}/apply")
    assert applied.status_code == 200, applied.text
    target = applied.json()["data"]["target"]
    assert "TCP" in target["suggested_meta"]["tags"]
    assert target["suggested_meta"]["difficulty"] == 3
    assert target["suggested_meta"]["frequency"] == "high"
    assert target["suggested_meta"]["category_path"] == "Zeta测试/网络/TCP"
    assert target["suggested_meta"]["ai_tagging"]["confidence"] == 0.82
    assert applied.json()["data"]["suggestion"]["applied_at"]

    again = auth_client.post(f"/api/v1/ai/suggestions/{suggestion['id']}/apply")
    assert again.status_code == 409

    listing = auth_client.get(
        "/api/v1/ai/suggestions?kind=tagging",
        params={"target_type": "pending", "target_id": item["id"]},
    ).json()["data"]
    assert listing["total"] == 1


def test_tag_suggestion_failure_keeps_meta_and_can_retry(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _pending_knowledge(auth_client, "Zeta 失败样例")
    before = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    failing = FakeGateway(error=ApiError(503, "AI_UNAVAILABLE", "AI 服务暂不可用"))
    monkeypatch.setattr(suggestions_service, "get_ai_gateway", lambda _db: failing)

    response = auth_client.post(
        "/api/v1/ai/suggestions",
        json={"kind": "tagging", "target_type": "pending", "target_id": item["id"]},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "AI_UNAVAILABLE"
    failed = payload["data"]["suggestion"]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "AI_UNAVAILABLE"

    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["suggested_meta"] == before["suggested_meta"]
    assert detail["ai_suggestions"][0]["status"] == "failed"

    cannot_apply = auth_client.post(f"/api/v1/ai/suggestions/{failed['id']}/apply")
    assert cannot_apply.status_code == 409

    success = FakeGateway(result=_tag_result())
    monkeypatch.setattr(suggestions_service, "get_ai_gateway", lambda _db: success)
    retried = auth_client.post(
        "/api/v1/ai/suggestions",
        json={"kind": "tagging", "target_type": "pending", "target_id": item["id"]},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "success"


def test_answer_polish_apply_updates_question(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = _question(auth_client)
    polish = {
        "polished_answer": "先说结论：三次握手确认双方收发能力并同步初始序列号。\n再讲过程与边界。",
        "key_points": ["确认收发能力", "同步序列号", "防止历史连接"],
        "changes": ["补充结论先行", "增加边界说明"],
        "confidence": 0.9,
    }
    fake = FakeGateway(result=polish)
    monkeypatch.setattr(suggestions_service, "get_ai_gateway", lambda _db: fake)

    response = auth_client.post(
        "/api/v1/ai/suggestions",
        json={
            "kind": "answer_polish",
            "target_type": "question",
            "target_id": question["id"],
        },
    )
    assert response.status_code == 200, response.text
    suggestion = response.json()["data"]

    applied = auth_client.post(f"/api/v1/ai/suggestions/{suggestion['id']}/apply")
    assert applied.status_code == 200, applied.text
    target = applied.json()["data"]["target"]
    assert target["answer"] == polish["polished_answer"]
    assert target["key_points"] == polish["key_points"]

    detail = auth_client.get(f"/api/v1/questions/{question['id']}").json()["data"]
    assert detail["answer"] == polish["polished_answer"]


def test_mistake_analysis_privacy_and_storage(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = _question(
        auth_client,
        stem="M3 隐私测试：什么是 JVM？",
        answer="Java 虚拟机。",
        notes="我的私人笔记，不应发送给 AI",
    )
    analysis = {
        "explanation": "JVM 负责字节码加载、解释与即时编译。",
        "pitfalls": ["把 JVM 等同于 JDK"],
        "follow_ups": ["JVM 内存区域有哪些？", "类加载何时发生？"],
        "related_knowledge": [{"title": "类加载机制", "why": "理解 JVM 生命周期"}],
        "confidence": 0.8,
    }
    fake = FakeGateway(result=analysis)
    monkeypatch.setattr(suggestions_service, "get_ai_gateway", lambda _db: fake)

    response = auth_client.post(
        "/api/v1/ai/suggestions",
        json={
            "kind": "mistake_analysis",
            "target_type": "question",
            "target_id": question["id"],
        },
    )
    assert response.status_code == 200, response.text
    suggestion = response.json()["data"]
    assert suggestion["result"]["follow_ups"]
    assert suggestion["applied_at"] is None

    # 解析只作参考，不能“应用”到题目。
    cannot_apply = auth_client.post(f"/api/v1/ai/suggestions/{suggestion['id']}/apply")
    assert cannot_apply.status_code == 400

    db = SessionLocal()
    try:
        payload = suggestions_service._mistake_payload(
            db, question["id"], user_answer=None, consent=False
        )
        text = json.dumps(payload, ensure_ascii=False)
        assert "私人笔记" not in text
        assert "notes" not in payload
        assert "user_answer" not in payload

        consented = suggestions_service._mistake_payload(
            db, question["id"], user_answer="我的作答", consent=True
        )
        assert consented["user_answer"] == "我的作答"
        without_consent = suggestions_service._mistake_payload(
            db, question["id"], user_answer="我的作答", consent=False
        )
        assert "user_answer" not in without_consent
    finally:
        db.close()


def test_question_generation_enters_pending_and_skips_duplicates(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = {
        "questions": [
            {
                "stem": "M3 生成题：Redis RDB 与 AOF 有什么区别？",
                "answer": "RDB 是快照，AOF 是追加日志。",
                "key_points": ["RDB 快照", "AOF 日志"],
                "difficulty": 3,
                "frequency": "high",
                "category_path": "Zeta测试/Redis/持久化",
                "tags": ["Redis", "持久化"],
                "confidence": 0.85,
            },
            {
                "stem": "M3 生成题：AOF 重写解决什么问题？",
                "answer": "压缩日志体积，避免无限增长。",
                "key_points": ["日志压缩"],
                "difficulty": 4,
                "frequency": "mid",
                "category_path": "Zeta测试/Redis/持久化",
                "tags": ["Redis", "AOF"],
                "confidence": 0.8,
            },
        ]
    }
    fake = FakeGateway(result=generated)
    monkeypatch.setattr(
        "app.services.ai.generation.get_ai_gateway", lambda _db: fake
    )

    response = auth_client.post(
        "/api/v1/ai/generate-questions",
        json={"topic": "Redis 持久化", "count": 2},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["generated"] == 2
    assert data["skipped"] == 0
    assert all(item["source_type"] == "ai" for item in data["items"])
    first = data["items"][0]
    assert first["status"] == "pending"
    assert first["suggested_meta"]["key_points"]
    assert first["suggested_meta"]["ai_generated"] is True

    listing = auth_client.get("/api/v1/pending?item_type=question&status=pending").json()["data"]
    stems = {row["stem"] for row in listing["items"]}
    assert generated["questions"][0]["stem"] in stems

    duplicate = auth_client.post(
        "/api/v1/ai/generate-questions",
        json={"topic": "Redis 持久化", "count": 2},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["data"]["generated"] == 0
    assert duplicate.json()["data"]["skipped"] == 2


def test_question_generation_failure_creates_no_pending(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = auth_client.get("/api/v1/pending?item_type=question&status=pending").json()["data"]["total"]
    failing = FakeGateway(error=ApiError(503, "AI_UNAVAILABLE", "AI 服务暂不可用"))
    monkeypatch.setattr(
        "app.services.ai.generation.get_ai_gateway", lambda _db: failing
    )
    response = auth_client.post(
        "/api/v1/ai/generate-questions",
        json={"topic": "不会成功的主题", "count": 2},
    )
    assert response.status_code == 503
    after = auth_client.get("/api/v1/pending?item_type=question&status=pending").json()["data"]["total"]
    assert after == before


def test_question_generation_requires_topic_or_knowledge(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/ai/generate-questions", json={"count": 2}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
