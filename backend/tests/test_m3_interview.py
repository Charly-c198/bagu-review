"""M3b：文字仿真面试、评分降级与薄弱点回写。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import ApiError
from app.services import interview as interview_service


class RoutedGateway:
    def __init__(
        self,
        results: dict[str, dict] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.purposes: list[str] = []

    def complete_json(self, **kwargs):  # noqa: ANN003
        purpose = kwargs["purpose"]
        self.purposes.append(purpose)
        if purpose in self.errors:
            raise self.errors[purpose]
        return self.results[purpose]


class NeverCalledGateway:
    def complete_json(self, **kwargs):  # noqa: ANN003
        raise AssertionError(f"不应调用 AI：{kwargs.get('purpose')}")


def _questions(auth_client: TestClient, count: int = 3) -> list[dict]:
    result = []
    for index in range(count):
        response = auth_client.post(
            "/api/v1/questions",
            json={
                "stem": f"M3 面试题 {index + 1}：请解释 TCP 状态机中的 TIME_WAIT。",
                "answer": "主动关闭方等待 2MSL，确保旧连接报文消散。",
                "key_points": ["主动关闭方", "2MSL", "旧报文消散"],
            },
        )
        assert response.status_code == 200, response.text
        result.append(response.json()["data"])
    return result


def _create_session(auth_client: TestClient, **overrides) -> dict:
    payload = {"count": 2, "duration_min": 20, "ai_consent": True, **overrides}
    response = auth_client.post("/api/v1/interview/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _score_output(score: int = 2) -> dict:
    return {
        "score": score,
        "feedback": "结论方向正确，但遗漏了 2MSL 的原因。",
        "gaps": ["未解释 2MSL", "未说明主动关闭方"],
        "follow_up": "如果 TIME_WAIT 过多，如何排查和处理？",
        "advice": "先给结论，再解释机制。",
    }


def _report_output(question_id: int) -> dict:
    return {
        "summary": "整体方向正确，关键机制掌握不牢。",
        "highlights": ["能识别 TIME_WAIT 场景"],
        "gaps": ["2MSL 原因不熟"],
        "advice": ["复练 TCP 状态机"],
        "weak_question_ids": [question_id],
        "next_steps": ["重练本题并补充知识条目"],
    }


def test_interview_ai_flow_and_writeback(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _questions(auth_client, 3)
    session = _create_session(auth_client)
    assert session["status"] == "in_progress"
    assert len(session["questions"]) == 2
    # 组卷响应只下发题干，不下发参考答案。
    assert "answer" not in session["questions"][0]
    question_id = session["questions"][0]["id"]

    gateway = RoutedGateway(
        results={
            "interview_score": _score_output(2),
            "interview_report": _report_output(question_id),
        }
    )
    monkeypatch.setattr(interview_service, "get_ai_gateway", lambda _db: gateway)

    answer = auth_client.post(
        f"/api/v1/interview/sessions/{session['id']}/answers",
        json={"question_id": question_id, "answer_text": "主动关闭方会等待一段时间。"},
    )
    assert answer.status_code == 200, answer.text
    turn = answer.json()["data"]
    assert turn["score"] == 2
    assert turn["scored_by"] == "ai"
    assert turn["follow_up"]

    duplicate = auth_client.post(
        f"/api/v1/interview/sessions/{session['id']}/answers",
        json={"question_id": question_id, "answer_text": "再答一次"},
    )
    assert duplicate.status_code == 409

    follow_up = auth_client.post(
        f"/api/v1/interview/sessions/{session['id']}/turns/{turn['id']}/follow-up",
        json={"answer_text": "可以检查连接数并调整内核参数。"},
    )
    assert follow_up.status_code == 200, follow_up.text
    assert follow_up.json()["data"]["follow_up_answer"]

    finished = auth_client.post(f"/api/v1/interview/sessions/{session['id']}/finish")
    assert finished.status_code == 200, finished.text
    payload = finished.json()["data"]
    report = payload["report"]
    assert report["generated_by"] == "ai"
    assert report["total_score"] == 40.0
    assert report["average_score"] == 2.0
    assert report["weak_question_ids"] == [question_id]
    assert payload["session"]["status"] == "finished"

    detail = auth_client.get(f"/api/v1/interview/sessions/{session['id']}").json()["data"]
    assert detail["report"]["id"] == report["id"]
    assert detail["turns"][0]["answer_text"] == "主动关闭方会等待一段时间。"

    # 薄弱点回写：q=2 进入错题本，并写入 interview 掌握记录。
    mistakes = auth_client.get("/api/v1/mistakes").json()["data"]["items"]
    assert any(item["id"] == question_id for item in mistakes)
    question = auth_client.get(f"/api/v1/questions/{question_id}").json()["data"]
    assert any(record["mode"] == "interview" and record["q"] == 2 for record in question["history"])

    again = auth_client.post(f"/api/v1/interview/sessions/{session['id']}/finish")
    assert again.status_code == 409


def test_ai_failure_keeps_answer_then_manual_score_and_basic_report(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _questions(auth_client, 2)
    session = _create_session(auth_client, count=1)
    question_id = session["questions"][0]["id"]

    failing = RoutedGateway(
        errors={
            "interview_score": ApiError(503, "AI_UNAVAILABLE", "AI 服务暂不可用"),
            "interview_report": ApiError(503, "AI_UNAVAILABLE", "AI 服务暂不可用"),
        }
    )
    monkeypatch.setattr(interview_service, "get_ai_gateway", lambda _db: failing)

    response = auth_client.post(
        f"/api/v1/interview/sessions/{session['id']}/answers",
        json={"question_id": question_id, "answer_text": "我的作答必须保留。"},
    )
    assert response.status_code == 503
    saved = response.json()["data"]["turn"]
    assert saved["score"] is None
    assert saved["answer_text"] == "我的作答必须保留。"

    detail = auth_client.get(f"/api/v1/interview/sessions/{session['id']}").json()["data"]
    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["scored_by"] == "none"

    manual = auth_client.patch(
        f"/api/v1/interview/sessions/{session['id']}/turns/{saved['id']}",
        json={"score": 4, "feedback": "人工评分：核心正确。"},
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["data"]["scored_by"] == "manual"

    finished = auth_client.post(f"/api/v1/interview/sessions/{session['id']}/finish")
    assert finished.status_code == 200, finished.text
    report = finished.json()["data"]["report"]
    assert report["generated_by"] == "basic"
    assert report["total_score"] == 80.0
    assert report["ai_error_code"] == "AI_UNAVAILABLE"
    assert report["summary"]


def test_no_consent_never_calls_ai(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _questions(auth_client, 2)
    session = _create_session(auth_client, count=1, ai_consent=False)
    assert session["config"]["ai_consent"] is False
    question_id = session["questions"][0]["id"]

    monkeypatch.setattr(
        interview_service, "get_ai_gateway", lambda _db: NeverCalledGateway()
    )
    answer = auth_client.post(
        f"/api/v1/interview/sessions/{session['id']}/answers",
        json={"question_id": question_id, "answer_text": "手动自评作答"},
    )
    assert answer.status_code == 200, answer.text
    turn = answer.json()["data"]
    assert turn["scored_by"] == "none"
    assert turn["score"] is None

    auth_client.patch(
        f"/api/v1/interview/sessions/{session['id']}/turns/{turn['id']}",
        json={"score": 5},
    )
    finished = auth_client.post(f"/api/v1/interview/sessions/{session['id']}/finish")
    assert finished.status_code == 200, finished.text
    assert finished.json()["data"]["report"]["generated_by"] == "basic"
    assert finished.json()["data"]["report"]["total_score"] == 100.0


def test_interview_validation_and_abort(auth_client: TestClient) -> None:
    _questions(auth_client, 1)
    response = auth_client.post(
        "/api/v1/interview/sessions",
        json={"count": 5, "duration_min": 20, "ai_consent": False},
    )
    assert response.status_code == 400
    assert "题目不足" in response.json()["message"]

    session = _create_session(auth_client, count=1, ai_consent=False)
    aborted = auth_client.post(f"/api/v1/interview/sessions/{session['id']}/abort")
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["data"]["status"] == "aborted"

    question_id = session["questions"][0]["id"]
    answer = auth_client.post(
        f"/api/v1/interview/sessions/{session['id']}/answers",
        json={"question_id": question_id, "answer_text": "不能再答"},
    )
    assert answer.status_code == 409
    finish = auth_client.post(f"/api/v1/interview/sessions/{session['id']}/finish")
    assert finish.status_code == 409
