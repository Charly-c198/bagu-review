"""FTS5 全文搜索（M2）验收。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_question(auth_client: TestClient, stem: str, answer: str = "") -> dict:
    response = auth_client.post(
        "/api/v1/questions", json={"stem": stem, "answer": answer or None}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _create_knowledge(auth_client: TestClient, title: str, content: str) -> dict:
    response = auth_client.post(
        "/api/v1/knowledge", json={"title": title, "content": content}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_fts_question_search_and_sync(auth_client: TestClient) -> None:
    tcp = _create_question(
        auth_client, "TCP 三次握手为什么需要三次？", "防止历史连接，确认双方收发能力。"
    )
    _create_question(auth_client, "Redis 持久化 RDB 和 AOF 的区别？", "RDB 快照，AOF 日志。")

    hit = auth_client.get("/api/v1/questions", params={"q": "三次握手"}).json()["data"]
    assert [item["id"] for item in hit["items"]] == [tcp["id"]]

    english = auth_client.get("/api/v1/questions", params={"q": "AOF"}).json()["data"]
    assert len(english["items"]) == 1
    assert "AOF" in english["items"][0]["stem"]

    # 2 个字符低于 trigram 长度，退回 LIKE 仍应命中。
    short = auth_client.get("/api/v1/questions", params={"q": "握手"}).json()["data"]
    assert len(short["items"]) == 1

    # 更新与删除由触发器同步索引。
    auth_client.patch(
        f"/api/v1/questions/{tcp['id']}", json={"stem": "HTTP 长连接与短连接？"}
    )
    old = auth_client.get("/api/v1/questions", params={"q": "三次握手"}).json()["data"]
    assert old["items"] == []
    new = auth_client.get("/api/v1/questions", params={"q": "长连接"}).json()["data"]
    assert [item["id"] for item in new["items"]] == [tcp["id"]]

    auth_client.delete(f"/api/v1/questions/{tcp['id']}")
    gone = auth_client.get("/api/v1/questions", params={"q": "长连接"}).json()["data"]
    assert gone["items"] == []


def test_fts_knowledge_search(auth_client: TestClient) -> None:
    _create_knowledge(auth_client, "TCP 三次握手", "SYN、SYN-ACK、ACK 的完整流程说明。")
    _create_knowledge(auth_client, "Redis 缓存雪崩", "大量 key 同时过期导致数据库压力骤增。")

    data = auth_client.get("/api/v1/knowledge", params={"q": "SYN-ACK"}).json()["data"]
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "TCP 三次握手"

    data = auth_client.get("/api/v1/knowledge", params={"q": "缓存雪崩"}).json()["data"]
    assert len(data["items"]) == 1


def test_fts_tables_exist(client: TestClient) -> None:
    from sqlalchemy import text

    from app.database import SessionLocal

    with SessionLocal() as db:
        names = {
            row[0]
            for row in db.execute(
                text("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")
            ).all()
        }
    assert {"question_fts", "knowledge_fts"} <= names
    assert {"question_fts_ai", "question_fts_au", "question_fts_ad"} <= names
