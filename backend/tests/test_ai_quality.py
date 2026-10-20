"""M3a Slice 1：AI 质检 + 人工质检双通道。"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import ApiError
from app.models import AiCall
from app.services.ai import quality as quality_service
from app.services.ai.gateway import AIConfig, AIGateway
from app.services.ai.quality import QualityOutput, _build_payload


class FakeGateway:
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def complete_json(self, **_kwargs):  # noqa: ANN003
        if self.error is not None:
            raise self.error
        return self.result


def _pending_knowledge(auth_client: TestClient, title: str = "AI 质检待审知识") -> dict:
    response = auth_client.post(
        "/api/v1/knowledge",
        json={
            "title": title,
            "content": "这是一条用于 AI 质检测试的知识条目，包含概念与示例。",
            "send_to_pending": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["item"]


def _valid_output(item_id: int, risk: str = "medium") -> dict:
    return {
        "target_type": "pending",
        "target_id": item_id,
        "issues": [
            {
                "type": "incomplete",
                "severity": risk,
                "description": "内容缺少边界条件说明",
                "evidence": "包含概念与示例",
                "suggestion": "补充适用场景",
                "confidence": 0.8,
            }
        ],
        "overall_risk": risk,
        "summary": "建议补充边界条件。",
    }


def test_manual_quality_check_and_pending_badge(auth_client: TestClient) -> None:
    item = _pending_knowledge(auth_client, "人工质检测试知识")
    response = auth_client.post(
        f"/api/v1/pending/{item['id']}/quality-check",
        json={
            "mode": "manual",
            "issues": [
                {
                    "type": "incomplete",
                    "severity": "high",
                    "description": "缺少示例",
                    "evidence": "原文只有概念",
                    "suggestion": "补充一个示例",
                }
            ],
            "summary": "人工检查完成",
        },
    )
    assert response.status_code == 200, response.text
    check = response.json()["data"]
    assert check["status"] == "success"
    assert check["model"] == "manual"
    assert check["overall_risk"] == "high"
    assert check["issues"][0]["type"] == "incomplete"
    assert check["reviewed_at"]

    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["status"] == "pending"
    assert detail["quality"]["status"] == "checked"
    assert detail["quality"]["risk"] == "high"
    assert detail["quality"]["source"] == "manual"
    assert len(detail["quality_checks"]) == 1

    listing = auth_client.get("/api/v1/pending").json()["data"]
    row = next(row for row in listing["items"] if row["id"] == item["id"])
    assert row["quality"]["status"] == "checked"


def test_ai_quality_check_success(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    item = _pending_knowledge(auth_client, "AI 成功测试知识")
    fake = FakeGateway(result=_valid_output(item["id"], "medium"))
    monkeypatch.setattr(quality_service, "get_ai_gateway", lambda _db: fake)

    response = auth_client.post(
        f"/api/v1/pending/{item['id']}/quality-check",
        json={"mode": "ai"},
    )
    assert response.status_code == 200, response.text
    check = response.json()["data"]
    assert check["status"] == "success"
    assert check["overall_risk"] == "medium"
    assert check["model"]
    assert check["prompt_version_id"]

    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["quality"]["status"] == "checked"
    assert detail["quality"]["source"] == "ai"


def test_ai_failure_marks_needs_manual_and_retry(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _pending_knowledge(auth_client, "AI 失败测试知识")
    failing = FakeGateway(error=ApiError(503, "AI_UNAVAILABLE", "AI 服务暂不可用"))
    monkeypatch.setattr(quality_service, "get_ai_gateway", lambda _db: failing)

    response = auth_client.post(
        f"/api/v1/pending/{item['id']}/quality-check",
        json={"mode": "ai"},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "AI_UNAVAILABLE"
    failed = payload["data"]["check"]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "AI_UNAVAILABLE"

    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["quality"]["status"] == "needs_manual"
    assert detail["quality"]["error_code"] == "AI_UNAVAILABLE"

    success = FakeGateway(result=_valid_output(item["id"], "low"))
    monkeypatch.setattr(quality_service, "get_ai_gateway", lambda _db: success)
    retried = auth_client.post(f"/api/v1/quality-checks/{failed['id']}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "success"

    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["quality"]["status"] == "checked"
    assert len(detail["quality_checks"]) == 2


def test_ai_not_configured_falls_back_to_manual(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _pending_knowledge(auth_client, "未配置 AI 测试知识")
    unconfigured = AIGateway_placeholder()
    monkeypatch.setattr(quality_service, "get_ai_gateway", lambda _db: unconfigured)

    response = auth_client.post(
        f"/api/v1/pending/{item['id']}/quality-check",
        json={"mode": "ai"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "AI_NOT_CONFIGURED"
    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["quality"]["status"] == "needs_manual"

    manual = auth_client.post(
        f"/api/v1/pending/{item['id']}/quality-check",
        json={"mode": "manual", "issues": [], "summary": "无问题"},
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["data"]["overall_risk"] == "low"
    detail = auth_client.get(f"/api/v1/pending/{item['id']}").json()["data"]
    assert detail["quality"]["status"] == "checked"
    assert detail["quality"]["source"] == "manual"


class AIGateway_placeholder:
    def complete_json(self, **_kwargs):  # noqa: ANN003
        raise ApiError(503, "AI_NOT_CONFIGURED", "AI 未配置")


def test_quality_check_existing_question_and_knowledge(auth_client: TestClient) -> None:
    question = auth_client.post(
        "/api/v1/questions",
        json={"stem": "M3 质检：TCP 为什么三次握手？", "answer": "为了确认双方收发能力。"},
    ).json()["data"]
    knowledge = auth_client.post(
        "/api/v1/knowledge",
        json={"title": "M3 质检知识", "content": "用于已有知识条目的质检测试。"},
    ).json()["data"]

    for target_type, target_id in (("question", question["id"]), ("knowledge", knowledge["id"])):
        response = auth_client.post(
            "/api/v1/quality/check",
            json={"target_type": target_type, "target_id": target_id, "mode": "manual"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["target_type"] == target_type


def test_quality_payload_excludes_personal_notes(auth_client: TestClient) -> None:
    question = auth_client.post(
        "/api/v1/questions",
        json={
            "stem": "隐私测试：什么是 JVM？",
            "answer": "Java 虚拟机。",
            "notes": "我的私人笔记，不应发送给 AI",
        },
    ).json()["data"]
    db = SessionLocal()
    try:
        payload = _build_payload(db, "question", question["id"])
    finally:
        db.close()
    text = json.dumps(payload, ensure_ascii=False)
    assert "私人笔记" not in text
    assert "notes" not in payload


def test_ai_status_endpoint_hides_key(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/ai/status")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "configured" in data
    assert "usage" in data
    assert "api_key" not in json.dumps(data)
    assert data["env"] == ["BAJIU_AI_BASE_URL", "BAJIU_AI_API_KEY", "BAJIU_AI_MODEL"]


def _gateway(db, handler, **overrides):
    config = AIConfig(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="fake-model",
        timeout_sec=5,
        max_output_tokens=200,
        monthly_token_limit=overrides.pop("monthly_token_limit", 100000),
        cache_ttl_days=1,
        json_mode=overrides.pop("json_mode", "auto"),
        **overrides,
    )
    return AIGateway(db, config_obj=config, transport=httpx.MockTransport(handler))


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_gateway_cache_and_usage(auth_client: TestClient) -> None:
    calls = {"count": 0}
    output = {
        "target_type": "question",
        "target_id": 1,
        "issues": [],
        "overall_risk": "low",
        "summary": "无问题",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _response(output)

    db = SessionLocal()
    try:
        gateway = _gateway(db, handler)
        kwargs = {
            "purpose": "quality_check",
            "system_prompt": "test",
            "payload": {"target_type": "question", "target_id": 1},
            "schema_model": QualityOutput,
            "prompt_version_id": None,
        }
        assert gateway.complete_json(**kwargs)["overall_risk"] == "low"
        assert gateway.complete_json(**kwargs)["overall_risk"] == "low"
        assert calls["count"] == 1
        rows = db.scalars(select(AiCall).order_by(AiCall.id)).all()
        assert [row.status for row in rows] == ["success", "cache_hit"]
        assert rows[0].input_tokens == 10
        assert rows[0].output_tokens == 5
    finally:
        db.close()


def test_gateway_retries_server_errors(auth_client: TestClient) -> None:
    calls = {"count": 0}
    output = {
        "target_type": "question",
        "target_id": 1,
        "issues": [],
        "overall_risk": "low",
        "summary": "无问题",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return _response(output)

    db = SessionLocal()
    try:
        gateway = _gateway(db, handler)
        result = gateway.complete_json(
            purpose="quality_check",
            system_prompt="test",
            payload={"target_type": "question", "target_id": 1},
            schema_model=QualityOutput,
            prompt_version_id=None,
        )
        assert result["overall_risk"] == "low"
        assert calls["count"] == 2
    finally:
        db.close()


def test_gateway_schema_invalid(auth_client: TestClient) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "这不是 JSON"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    db = SessionLocal()
    try:
        gateway = _gateway(db, handler)
        with pytest.raises(ApiError) as excinfo:
            gateway.complete_json(
                purpose="quality_check",
                system_prompt="test",
                payload={"target_type": "question", "target_id": 1},
                schema_model=QualityOutput,
                prompt_version_id=None,
            )
        assert excinfo.value.code == "AI_SCHEMA_INVALID"
        assert calls["count"] == 2
        row = db.scalars(select(AiCall).order_by(AiCall.id.desc())).first()
        assert row is not None and row.status == "failed"
        assert row.error_code == "AI_SCHEMA_INVALID"
    finally:
        db.close()


def test_gateway_budget_stops_calls(auth_client: TestClient) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500)

    db = SessionLocal()
    try:
        db.add(
            AiCall(
                purpose="quality_check",
                model="fake-model",
                input_tokens=30,
                output_tokens=0,
                cost=0,
                latency_ms=1,
                status="success",
            )
        )
        db.commit()
        gateway = _gateway(db, handler, monthly_token_limit=20)
        with pytest.raises(ApiError) as excinfo:
            gateway.complete_json(
                purpose="quality_check",
                system_prompt="test",
                payload={"target_type": "question", "target_id": 1},
                schema_model=QualityOutput,
                prompt_version_id=None,
            )
        assert excinfo.value.code == "AI_BUDGET_EXCEEDED"
        assert calls["count"] == 0
    finally:
        db.close()
