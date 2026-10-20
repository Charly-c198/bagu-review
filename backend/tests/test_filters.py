"""M2 多维筛选验收：维度间 AND、维度内 OR，题库与组卷共用。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create(auth_client: TestClient, **payload) -> dict:
    response = auth_client.post("/api/v1/questions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _setup(auth_client: TestClient) -> dict[str, dict]:
    return {
        "a": _create(
            auth_client,
            stem="TCP 三次握手的流程？",
            difficulty=1,
            frequency="high",
            tags=["TCP", "网络"],
            companies=["腾讯"],
            category_path="后端开发/计算机网络/TCP",
        ),
        "b": _create(
            auth_client,
            stem="Redis 缓存雪崩怎么解决？",
            difficulty=5,
            frequency="low",
            tags=["Redis", "缓存"],
            companies=["阿里"],
            category_path="后端开发/缓存/Redis",
        ),
        "c": _create(
            auth_client,
            stem="进程和线程的区别？",
            difficulty=3,
            frequency="mid",
            tags=["操作系统"],
            companies=["腾讯"],
            category_path="后端开发/操作系统/进程管理",
        ),
    }


def test_multi_value_filters(auth_client: TestClient) -> None:
    items = _setup(auth_client)
    url = "/api/v1/questions"

    both = auth_client.get(
        url, params={"difficulties": "1,5", "status": "active"}
    ).json()["data"]
    assert {row["id"] for row in both["items"]} == {items["a"]["id"], items["b"]["id"]}

    high_low = auth_client.get(
        url, params={"frequencies": "high,low", "status": "active"}
    ).json()["data"]
    assert {row["id"] for row in high_low["items"]} == {items["a"]["id"], items["b"]["id"]}

    tag_ids = ",".join(str(tag["id"]) for tag in items["a"]["tags"] + items["b"]["tags"])
    tagged = auth_client.get(
        url, params={"tag_ids": tag_ids, "status": "active"}
    ).json()["data"]
    assert {row["id"] for row in tagged["items"]} == {items["a"]["id"], items["b"]["id"]}

    tencent = items["a"]["companies"][0]["id"]
    company = auth_client.get(
        url, params={"company_ids": str(tencent), "status": "active"}
    ).json()["data"]
    assert {row["id"] for row in company["items"]} == {items["a"]["id"], items["c"]["id"]}

    # 维度之间 AND：难度 1/5 且公司腾讯 → 只有 a。
    combined = auth_client.get(
        url,
        params={
            "difficulties": "1,5",
            "company_ids": str(tencent),
            "status": "active",
        },
    ).json()["data"]
    assert [row["id"] for row in combined["items"]] == [items["a"]["id"]]

    # 分类多选：两个分类路径 OR。
    category_ids = ",".join(
        str(item["categories"][0]["id"]) for item in (items["a"], items["b"])
    )
    by_category = auth_client.get(
        url, params={"category_ids": category_ids, "status": "active"}
    ).json()["data"]
    assert {row["id"] for row in by_category["items"]} == {
        items["a"]["id"],
        items["b"]["id"],
    }


def test_multi_mastery_filter_and_practice(auth_client: TestClient) -> None:
    items = _setup(auth_client)
    rated = auth_client.post(
        "/api/v1/ratings", json={"question_id": items["a"]["id"], "q": 5}
    )
    assert rated.status_code == 200, rated.text

    mastered = auth_client.get(
        "/api/v1/questions",
        params={"masteries": "mastered", "status": "active"},
    ).json()["data"]
    assert [row["id"] for row in mastered["items"]] == [items["a"]["id"]]

    unlearned = auth_client.get(
        "/api/v1/questions",
        params={"masteries": "unlearned", "status": "active"},
    ).json()["data"]
    assert {row["id"] for row in unlearned["items"]} == {
        items["b"]["id"],
        items["c"]["id"],
    }

    quiz = auth_client.post(
        "/api/v1/practice/quiz",
        json={
            "difficulties": [1, 5],
            "frequencies": ["high", "low"],
            "limit": 20,
            "mode": "practice",
        },
    )
    assert quiz.status_code == 200, quiz.text
    assert {row["id"] for row in quiz.json()["data"]["items"]} == {
        items["a"]["id"],
        items["b"]["id"],
    }

    mastery_quiz = auth_client.post(
        "/api/v1/practice/quiz",
        json={"masteries": ["mastered"], "limit": 20, "mode": "practice"},
    )
    assert [row["id"] for row in mastery_quiz.json()["data"]["items"]] == [
        items["a"]["id"]
    ]
