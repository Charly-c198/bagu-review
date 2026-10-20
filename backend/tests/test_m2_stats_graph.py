"""M2 统计可视化增强与知识图谱基础版验收。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_question(auth_client: TestClient, stem: str, category_path: str | None = None) -> dict:
    response = auth_client.post(
        "/api/v1/questions",
        json={"stem": stem, "category_path": category_path},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _create_knowledge(auth_client: TestClient, title: str) -> dict:
    response = auth_client.post(
        "/api/v1/knowledge",
        json={"title": title, "content": f"{title} 的完整说明，用于图谱测试。"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _link(auth_client: TestClient, question_id: int, knowledge_id: int) -> None:
    response = auth_client.post(
        f"/api/v1/questions/{question_id}/knowledge",
        json={"knowledge_id": knowledge_id, "relation_type": "related"},
    )
    assert response.status_code == 200, response.text


def test_review_heatmap_and_category_mastery(auth_client: TestClient) -> None:
    question = _create_question(
        auth_client, "M2 统计测试：TCP 为什么三次握手？", "后端开发/计算机网络/TCP"
    )
    rated = auth_client.post(
        "/api/v1/ratings", json={"question_id": question["id"], "q": 5}
    )
    assert rated.status_code == 200, rated.text

    heatmap = auth_client.get(
        "/api/v1/stats/review-heatmap", params={"days": 7}
    ).json()["data"]
    assert heatmap["days"] == 7
    assert len(heatmap["items"]) == 7
    assert heatmap["total_reviews"] >= 1
    today = heatmap["items"][-1]
    assert today["reviews"] >= 1
    assert today["accuracy"] == 100.0

    categories = auth_client.get("/api/v1/stats/category-mastery").json()["data"]
    row = next(item for item in categories if item["label"] == "计算机网络")
    assert row["mastered"] >= 1
    assert row["total"] >= 1


def test_knowledge_graph_nodes_edges_and_focus(auth_client: TestClient) -> None:
    k1 = _create_knowledge(auth_client, "图谱知识 A")
    k2 = _create_knowledge(auth_client, "图谱知识 B")
    q1 = _create_question(auth_client, "图谱问题一：A 和 B 的关系？")
    q2 = _create_question(auth_client, "图谱问题二：B 如何应用？")
    q3 = _create_question(auth_client, "图谱问题三：A 的原理？")
    _link(auth_client, q1["id"], k1["id"])
    _link(auth_client, q1["id"], k2["id"])
    _link(auth_client, q2["id"], k2["id"])
    _link(auth_client, q3["id"], k1["id"])

    data = auth_client.get(
        "/api/v1/graph", params={"include_questions": "true", "limit": 20}
    ).json()["data"]
    node_ids = {node["id"] for node in data["nodes"]}
    assert {f"k{k1['id']}", f"k{k2['id']}", f"q{q1['id']}"} <= node_ids
    co_edges = [
        edge
        for edge in data["edges"]
        if edge["type"] == "co_occurrence"
        and {edge["source"], edge["target"]} == {f"k{k1['id']}", f"k{k2['id']}"}
    ]
    assert co_edges and co_edges[0]["weight"] == 1
    q_edges = [edge for edge in data["edges"] if edge["type"] == "question_knowledge"]
    assert len(q_edges) == 4

    focused = auth_client.get(
        "/api/v1/graph", params={"knowledge_id": k1["id"], "limit": 20}
    ).json()["data"]
    focused_ids = {node["id"] for node in focused["nodes"]}
    # 一跳邻居：与 A 共享题目的 B 应被带出。
    assert f"k{k1['id']}" in focused_ids and f"k{k2['id']}" in focused_ids
