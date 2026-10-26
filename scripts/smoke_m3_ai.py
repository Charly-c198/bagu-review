"""M3 AI 真实模型冒烟脚本。

前置：后端已启动（默认 http://127.0.0.1:8000）、.env 已配置 BAJIU_AI_*。
建议在演示库副本上运行，避免污染正式数据；脚本只创建带时间戳的测试内容。

用法：
    python scripts/smoke_m3_ai.py
    python scripts/smoke_m3_ai.py --base http://127.0.0.1:8000/api/v1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8000/api/v1")
parser.add_argument("--username", default="admin")
parser.add_argument("--password", default="admin123")
args = parser.parse_args()

client = httpx.Client(timeout=180.0)
summary: dict = {"calls": [], "failures": []}


def request(method: str, path: str, body: dict | None = None, expect: int = 200) -> dict:
    started = time.monotonic()
    response = client.request(method, args.base + path, json=body)
    elapsed = round(time.monotonic() - started, 2)
    try:
        payload = response.json()
    except ValueError:
        payload = {"code": "BAD_JSON", "message": response.text[:200]}
    entry = {
        "method": method,
        "path": path,
        "http": response.status_code,
        "code": payload.get("code"),
        "elapsed_sec": elapsed,
    }
    summary["calls"].append(entry)
    if response.status_code != expect or payload.get("code") != "OK":
        entry["message"] = payload.get("message")
        summary["failures"].append(entry)
        return {"__error__": True, **payload, "elapsed_sec": elapsed}
    data = payload.get("data")
    return data if isinstance(data, dict) else {"data": data}


def last_elapsed() -> float:
    return summary["calls"][-1]["elapsed_sec"] if summary["calls"] else 0.0


def main() -> int:
    login = request("POST", "/auth/login", {"username": args.username, "password": args.password})
    if login.get("__error__"):
        print("登录失败", login)
        return 2
    client.headers["Authorization"] = f"Bearer {login['token']}"

    status = request("GET", "/ai/status")
    if status.get("__error__"):
        print("AI 状态读取失败", status)
        return 2
    print(
        f"[INFO] AI configured={status['configured']} model={status['model']} "
        f"timeout={status['timeout_sec']}s"
    )
    if not status["configured"]:
        print("AI 未配置，冒烟终止")
        return 2

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")

    # 1) 打标建议：待审知识
    pending = request(
        "POST",
        "/knowledge",
        {
            "title": f"冒烟打标-{stamp}",
            "content": "Zeta 冒烟内容：TCP 三次握手用于确认双方收发能力并同步初始序列号。",
            "send_to_pending": True,
        },
    )
    if pending.get("__error__"):
        return 2
    pending_id = pending["item"]["id"]

    tagging = request(
        "POST",
        "/ai/suggestions",
        {"kind": "tagging", "target_type": "pending", "target_id": pending_id},
    )
    print(f"[TAG] suggestion status={tagging.get('status')} error={tagging.get('error_code')}")
    if tagging.get("result"):
        result = tagging["result"]
        print(
            "      category=", result.get("category_path"),
            "tags=", result.get("tags"),
            "difficulty=", result.get("difficulty"),
            "frequency=", result.get("frequency"),
            "confidence=", result.get("confidence"),
        )
        print("      rationale=", (result.get("rationale") or "")[:120])

    # 1b) 相同请求验证缓存
    tagging2 = request(
        "POST",
        "/ai/suggestions",
        {"kind": "tagging", "target_type": "pending", "target_id": pending_id},
    )
    print(f"[TAG-CACHE] status={tagging2.get('status')} elapsed={last_elapsed()}s")

    # 1c) 应用打标建议
    if tagging.get("status") == "success":
        applied = request("POST", f"/ai/suggestions/{tagging['id']}/apply")
        meta = (applied.get("target") or {}).get("suggested_meta") or {}
        print(
            "[TAG-APPLY] tags=", meta.get("tags"),
            "category=", meta.get("category_path"),
            "difficulty=", meta.get("difficulty"),
            "confidence=", (meta.get("ai_tagging") or {}).get("confidence"),
        )

    # 2) 题目 + 错题解析 + 答案润色
    question = request(
        "POST",
        "/questions",
        {
            "stem": f"冒烟题-{stamp}：为什么 TIME_WAIT 需要等待 2MSL？",
            "answer": "为了确保最后一个 ACK 能到达对端，并让旧连接报文消散。",
            "key_points": ["最后一个 ACK", "旧报文消散"],
            "notes": "冒烟私人笔记，不应发送给 AI",
        },
    )
    if question.get("__error__"):
        return 2
    question_id = question["id"]

    analysis = request(
        "POST",
        "/ai/suggestions",
        {"kind": "mistake_analysis", "target_type": "question", "target_id": question_id},
    )
    if analysis.get("result"):
        result = analysis["result"]
        print(
            "[ANALYSIS] explanation_len=", len(result.get("explanation") or ""),
            "pitfalls=", len(result.get("pitfalls") or []),
            "follow_ups=", len(result.get("follow_ups") or []),
            "related=", len(result.get("related_knowledge") or []),
        )
        print("      first_follow_up=", (result.get("follow_ups") or [""])[0][:100])
    else:
        print(f"[ANALYSIS] failed code={analysis.get('code')} error={analysis.get('error_code')}")

    polish = request(
        "POST",
        "/ai/suggestions",
        {"kind": "answer_polish", "target_type": "question", "target_id": question_id},
    )
    if polish.get("result"):
        result = polish["result"]
        print(
            "[POLISH] answer_len=", len(result.get("polished_answer") or ""),
            "key_points=", len(result.get("key_points") or []),
            "changes=", len(result.get("changes") or []),
        )
        applied = request("POST", f"/ai/suggestions/{polish['id']}/apply")
        print("[POLISH-APPLY] new_answer_prefix=", (applied.get("target") or {}).get("answer", "")[:80])
    else:
        print(f"[POLISH] failed code={polish.get('code')} error={polish.get('error_code')}")

    # 3) AI 出题
    generated = request(
        "POST",
        "/ai/generate-questions",
        {"topic": "Redis 持久化（RDB 与 AOF）", "count": 1},
    )
    print(
        "[GENERATE] requested=", generated.get("requested"),
        "generated=", generated.get("generated"),
        "skipped=", generated.get("skipped"),
    )
    for item in generated.get("items") or []:
        print("      stem=", (item.get("stem") or "")[:80])
        print(
            "      pending_id=", item.get("id"),
            "meta_tags=", (item.get("suggested_meta") or {}).get("tags"),
        )

    # 4) 仿真面试：1 题，AI 评分 + 复盘
    session = request(
        "POST",
        "/interview/sessions",
        {
            "count": 1,
            "duration_min": 10,
            "category_ids": [],
            "difficulties": [],
            "frequencies": [],
            "ai_consent": True,
        },
    )
    if session.get("__error__"):
        return 2
    session_id = session["id"]
    question_payload = session["questions"][0]
    print("[INTERVIEW] session=", session_id, "question=", question_payload["id"])

    # 随机抽题后按该题参考答案作答，避免固定答案与题目不匹配导致 0 分。
    detail = request("GET", f"/questions/{question_payload['id']}")
    reference = (detail.get("answer") or "").strip()
    key_points = detail.get("key_points") or []
    answer_text = "参考答案要点：" + reference
    if key_points:
        answer_text += "\n关键点：" + "；".join(key_points)
    print("      stem=", (detail.get("stem") or "")[:80])
    print("      answer_chars=", len(answer_text))

    answer = request(
        "POST",
        f"/interview/sessions/{session_id}/answers",
        {
            "question_id": question_payload["id"],
            "answer_text": answer_text,
        },
    )
    if answer.get("__error__"):
        print("[INTERVIEW-SCORE] failed:", answer.get("code"), answer.get("message"))
        turn = (answer.get("data") or {}).get("turn") or {}
        print("      answer_saved=", bool(turn), "turn_id=", turn.get("id"))
        if turn.get("id"):
            request(
                "PATCH",
                f"/interview/sessions/{session_id}/turns/{turn['id']}",
                {"score": 3, "feedback": "冒烟手动兜底评分"},
            )
    else:
        print(
            "[INTERVIEW-SCORE] score=", answer.get("score"),
            "scored_by=", answer.get("scored_by"),
            "gaps=", len(answer.get("gaps") or []),
        )
        print("      feedback=", (answer.get("feedback") or "")[:160])

    report = request("POST", f"/interview/sessions/{session_id}/finish")
    if report.get("__error__"):
        print("[INTERVIEW-REPORT] failed:", report.get("code"), report.get("message"))
    else:
        body = report["report"]
        print(
            "[INTERVIEW-REPORT] generated_by=", body.get("generated_by"),
            "total=", body.get("total_score"),
            "average=", body.get("average_score"),
            "weak_ids=", body.get("weak_question_ids"),
            "ai_error=", body.get("ai_error_code"),
        )
        print("      summary=", (body.get("summary") or "")[:180])

    # 5) 周报告（auto：AI 失败会自动降级）
    weekly = request("POST", "/reports/weekly", {"mode": "auto"})
    if weekly.get("__error__"):
        print("[WEEKLY] failed:", weekly.get("code"), weekly.get("message"))
    else:
        print(
            "[WEEKLY] generated_by=", weekly.get("generated_by"),
            "ai_error=", weekly.get("ai_error_code"),
            "reviews=", weekly.get("reviews"),
            "accuracy=", weekly.get("accuracy"),
            "weak_points=", len(weekly.get("weak_points") or []),
            "plan=", len(weekly.get("plan") or []),
        )
        print("      summary=", (weekly.get("summary") or "")[:180])

    after = request("GET", "/ai/status")
    print("[USAGE]", json.dumps(after.get("usage"), ensure_ascii=False))
    print("[PROMPTS]", json.dumps(after.get("prompt_versions"), ensure_ascii=False))

    total_elapsed = round(sum(call["elapsed_sec"] for call in summary["calls"]), 2)
    print(
        "[SUMMARY] calls=", len(summary["calls"]),
        "failures=", len(summary["failures"]),
        "elapsed_sum=", total_elapsed,
    )
    for call in summary["calls"]:
        print(
            f"  {call['http']} {call['method']} {call['path']} "
            f"{call['elapsed_sec']}s {call['code']}"
        )
    if summary["failures"]:
        print("[FAILURES]", json.dumps(summary["failures"], ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
