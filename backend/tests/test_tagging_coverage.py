"""1.3 规则打标验收：用未参与规则设计的 20 条面经题干衡量覆盖率。

文档门槛：20 条样例至少 15 条能给出建议标签/分类。
本文件的三组样例：
- SET_C 为最终验收数据，规则设计阶段未使用；
- 断言只要求“有建议”，不要求标签完全正确（人工审核时可改）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.services.tagging import suggest_meta

SET_C = [
    "Redis 的哨兵模式和集群模式有什么区别？",
    "JVM 调优一般关注哪些参数？",
    "Java 的 ArrayList 和 LinkedList 有什么区别？",
    "Spring MVC 的请求处理流程？",
    "Spring Boot 自动配置的原理？",
    "MySQL 的 binlog 有哪几种格式？",
    "MySQL 的聚簇索引和非聚簇索引有什么区别？",
    "MySQL 如何优化慢查询？",
    "Redis 的缓存一致性问题如何解决？",
    "RocketMQ 的事务消息原理？",
    "消息队列如何保证顺序消费？",
    "Java 的 volatile 关键字有什么作用？",
    "HTTPS 如何防止中间人攻击？",
    "HTTP/2 的多路复用是什么？",
    "什么是 BASE 理论？",
    "分布式锁有哪些实现方式？",
    "如何保证接口的幂等性？",
    "K8s 中 Service 的作用是什么？",
    "Git 如何回滚一次提交？",
    "如何设计一个短链接系统？",
]


def test_rule_coverage_on_independent_sample(client: TestClient) -> None:
    with SessionLocal() as db:
        hits: list[tuple[str, dict]] = []
        misses: list[str] = []
        for stem in SET_C:
            meta = suggest_meta(db, stem, item_type="question")
            if meta["tags"] or meta["category_path"]:
                hits.append((stem, meta))
            else:
                misses.append(stem)
    assert len(hits) >= 15, f"覆盖率不足：{len(hits)}/20，未命中 {misses}"
    # 抽查两条：建议不能只是空壳字段。
    by_stem = dict(hits)
    redis_meta = by_stem["Redis 的哨兵模式和集群模式有什么区别？"]
    assert "Redis" in redis_meta["tags"]
    assert (redis_meta["category_path"] or "").startswith("后端开发/")
    https_meta = by_stem["HTTPS 如何防止中间人攻击？"]
    assert "计算机网络" in https_meta["tags"]
    assert "HTTP" in https_meta["category_path"]
