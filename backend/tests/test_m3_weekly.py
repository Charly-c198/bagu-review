"""M3b：周学习报告（AI / 基础降级 / 幂等覆盖）。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.errors import ApiError
from app.services import weekly as weekly_service
from app.utils.timeutil import local_today


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


class NeverCalledGateway:
    def complete_json(self, **_kwargs):  # noqa: ANN003
        raise AssertionError("基础模式不应调用 AI")


def _prepare_week(auth_client: TestClient) -> list[dict]:
    questions = []
    for index in range(3):
        response = auth_client.post(
            "/api/v1/questions",
            json={
                "stem": f"Zeta 周报题 {index + 1}：解释 Redis 缓存穿透。",
                "answer": "布隆过滤器或空值缓存。",
                "key_points": ["布隆过滤器", "空值缓存"],
                "category_path": "Zeta周报/后端开发",
            },
        )
        assert response.status_code == 200, response.text
        question = response.json()["data"]
        questions.append(question)
        rated = auth_client.post(
            "/api/v1/ratings",
            json={"question_id": question["id"], "q": 2, "mode": "practice"},
        )
        assert rated.status_code == 200, rated.text
    return questions


def _ai_report() -> dict:
    return {
        "summary": "本周复习量稳定，但后端开发正确率偏低。",
        "highlights": ["坚持复习了 3 道题"],
        "weak_points": [
            {
                "label": "后端开发",
                "reason": "本周正确率为 0%。",
                "suggestion": "重练缓存相关题目。",
            }
        ],
        "plan": ["每天复练 10 道后端题", "整理缓存知识条目"],
    }


def test_basic_weekly_report_without_ai(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_week(auth_client)
    monkeypatch.setattr(
        weekly_service, "get_ai_gateway", lambda _db: NeverCalledGateway()
    )
    response = auth_client.post("/api/v1/reports/weekly", json={"mode": "basic"})
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["generated_by"] == "basic"
    assert report["reviews"] == 3
    assert report["accuracy"] == 0.0
    assert report["active_days"] == 1
    assert any(point["label"] == "后端开发" for point in report["weak_points"])
    assert report["plan"]
    today = local_today()
    expected_start = (today - timedelta(days=today.weekday())).isoformat()
    assert report["week_start"] == expected_start
    assert report["summary"]

    listing = auth_client.get("/api/v1/reports/weekly").json()["data"]
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == report["id"]


def test_ai_weekly_report_and_fallback_overwrite(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_week(auth_client)
    success = FakeGateway(result=_ai_report())
    monkeypatch.setattr(weekly_service, "get_ai_gateway", lambda _db: success)
    response = auth_client.post("/api/v1/reports/weekly", json={"mode": "auto"})
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["generated_by"] == "ai"
    assert report["summary"] == _ai_report()["summary"]
    assert report["weak_points"][0]["label"] == "后端开发"
    assert success.calls == 1

    # 同一周重复生成会覆盖同一条记录，不产生重复行。
    failing = FakeGateway(error=ApiError(503, "AI_UNAVAILABLE", "AI 服务暂不可用"))
    monkeypatch.setattr(weekly_service, "get_ai_gateway", lambda _db: failing)
    fallback = auth_client.post("/api/v1/reports/weekly", json={"mode": "auto"})
    assert fallback.status_code == 200, fallback.text
    data = fallback.json()["data"]
    assert data["id"] == report["id"]
    assert data["generated_by"] == "basic"
    assert data["ai_error_code"] == "AI_UNAVAILABLE"

    listing = auth_client.get("/api/v1/reports/weekly").json()["data"]
    assert listing["total"] == 1


def test_week_start_normalizes_to_monday(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/reports/weekly",
        json={"week_start": "2026-10-21", "mode": "basic"},
    )
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["week_start"] == "2026-10-19"
    assert report["week_end"] == "2026-10-25"
    detail = auth_client.get(f"/api/v1/reports/weekly/{report['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["week_start"] == "2026-10-19"
