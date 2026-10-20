"""演示数据初始化：把前端原型中的 35 道题、知识条目与样例任务写入本地 SQLite。

用法：
    python -m app.seed_demo            # 空库时写入；已有题目则跳过
    python -m app.seed_demo --reset    # 删除当前数据库后重新写入（谨慎）
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from .config import DB_PATH
from .database import SessionLocal, engine, init_db
from .models import (
    AuditLog,
    Bookmark,
    CrawlSource,
    CrawlTask,
    CrawlTaskFile,
    ImportBatch,
    KnowledgeOrigin,
    KnowledgePoint,
    MasteryRecord,
    MistakeBook,
    PendingItem,
    Question,
    QuestionKnowledge,
    QuestionOrigin,
    ReviewSchedule,
)
from .security import ensure_default_user
from .services.categories import (
    get_or_create_category_path,
)
from .services.tagging import load_seed_rules
from .services.taxonomy import set_question_taxonomy
from .utils.text import (
    knowledge_hash,
    question_hash,
    simhash64,
)
from .utils.timeutil import TZ, local_today

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "demo_seed.json"

BOARDS = {
    "backend": ("后端开发", "网络 / 操作系统 / 数据库 / 并发 / 分布式"),
    "frontend": ("前端开发", "浏览器 / CSS / JS / 工程化"),
    "fullstack": ("全栈", "前后端贯通 / 接口设计 / 认证"),
    "agent": ("AI-Agent", "RAG / 工具调用 / 大模型应用"),
    "algo": ("算法ML", "数据结构 / 复杂度 / 缓存策略"),
    "qa": ("测试质量", "用例设计 / 测试分层 / 缺陷管理"),
    "client": ("客户端C++", "内存 / 智能指针 / 面向对象"),
    "devops": ("运维DevOps", "容器 / 流水线 / 代理与部署"),
}

SOURCE_MAP = {
    "crawler": "crawler",
    "import": "import",
    "manual": "manual",
}


def _local_utc(day_offset: int, hour: int = 20, minute: int = 0) -> datetime:
    day = local_today() - timedelta(days=day_offset)
    local = datetime.combine(day, time(hour, minute), tzinfo=TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _category_parts(board_key: str, cat: str) -> list[str]:
    board_name = BOARDS[board_key][0]
    parts = [p.strip() for p in cat.split("/") if p.strip()]
    if parts and parts[0] == board_name:
        return parts[:3]
    return ([board_name] + parts)[:3]


def _schedule_for(mastery: str, due_offset: int) -> dict:
    today = local_today()
    if mastery == "mastered":
        return {
            "reps": 4,
            "ef": 2.6,
            "interval_days": 15,
            "lapses": 0,
            "next_review_date": (today + timedelta(days=max(due_offset, 10))).isoformat(),
            "last_q": 5,
            "first_reviewed_at": (today - timedelta(days=20)).isoformat(),
            "last_schedule_date": (today - timedelta(days=1)).isoformat(),
        }
    if mastery == "unfamiliar":
        return {
            "reps": 0,
            "ef": 2.5,
            "interval_days": 1,
            "lapses": 1,
            "next_review_date": (today + timedelta(days=due_offset)).isoformat(),
            "last_q": 2,
            "first_reviewed_at": (today - timedelta(days=1)).isoformat(),
            "last_schedule_date": (today - timedelta(days=1)).isoformat(),
        }
    return {
        "reps": 2,
        "ef": 2.5,
        "interval_days": 6,
        "lapses": 0,
        "next_review_date": (today + timedelta(days=due_offset)).isoformat(),
        "last_q": 4,
        "first_reviewed_at": (today - timedelta(days=8)).isoformat(),
        "last_schedule_date": (today - timedelta(days=1)).isoformat(),
    }


def _reset_database() -> None:
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    init_db()


def seed(reset: bool = False) -> None:
    if reset:
        _reset_database()
    else:
        init_db()
    ensure_default_user()

    with SessionLocal() as db:
        load_seed_rules(db)
        if db.scalar(select(Question.id).limit(1)) is not None and not reset:
            print("数据库已有题目，跳过演示数据。需要重建请使用 --reset")
            return

        data = json.loads(SEED_FILE.read_text(encoding="utf-8"))

        board_roots = {}
        for index, (key, (name, _desc)) in enumerate(BOARDS.items()):
            root = get_or_create_category_path(db, [name])
            root.sort_order = index
            board_roots[key] = root.id

        question_objs: list[Question] = []
        for index, item in enumerate(data["questions"]):
            boards = item.get("boards") or ["backend"]
            parts = _category_parts(boards[0], item["cat"])
            primary_category = get_or_create_category_path(db, parts)
            source_type = SOURCE_MAP.get(item.get("source", "manual"), "manual")
            stem = item["stem"]
            question = Question(
                stem=stem,
                answer=item.get("answer") or None,
                key_points=json.dumps(item.get("key_points", []), ensure_ascii=False)
                if item.get("key_points")
                else None,
                difficulty=item.get("difficulty"),
                frequency=item.get("frequency"),
                status="active",
                source_type=source_type,
                content_hash=question_hash(stem),
                simhash=simhash64(stem),
            )
            db.add(question)
            db.flush()
            category_ids = [primary_category.id]
            for board_key in boards:
                if board_key in board_roots:
                    category_ids.append(board_roots[board_key])
            set_question_taxonomy(
                db,
                question.id,
                category_ids=list(dict.fromkeys(category_ids)),
                tags=item.get("tags", []),
                companies=item.get("companies", []),
                replace=True,
            )
            db.add(
                QuestionOrigin(
                    question_id=question.id,
                    source_type=source_type,
                    origin_ref=f"demo:question:{index + 1}",
                    raw_snapshot=item.get("answer"),
                    content_hash=question.content_hash,
                )
            )

            mastery = item.get("mastery", "familiar")
            schedule_values = _schedule_for(mastery, int(item.get("due_offset", 1)))
            db.add(
                ReviewSchedule(
                    question_id=question.id,
                    last_rated_at=_local_utc(1),
                    **schedule_values,
                )
            )

            # 让最近 7 天都有掌握记录，形成连续打卡。
            offsets = [(index % 6) + 1]
            if mastery in ("familiar", "mastered"):
                offsets.append(min(6, (index % 6) + 3))
            for offset in sorted(set(offsets)):
                db.add(
                    MasteryRecord(
                        question_id=question.id,
                        q=schedule_values["last_q"],
                        mode="practice",
                        created_at=_local_utc(offset),
                    )
                )
            if mastery == "unfamiliar":
                db.add(
                    MistakeBook(
                        question_id=question.id,
                        action="added",
                        reason="unfamiliar",
                        created_at=_local_utc(1),
                    )
                )
            question_objs.append(question)

        # 今天有 5 条记录，保证连续打卡从今天开始计算。
        for question in question_objs:
            schedule = db.get(ReviewSchedule, question.id)
            if schedule and schedule.last_q == 5:
                db.add(
                    MasteryRecord(
                        question_id=question.id,
                        q=5,
                        mode="review",
                        created_at=_local_utc(0, 9),
                    )
                )

        for index in (0, 3, 13, 19, 31):
            if index < len(question_objs):
                db.add(Bookmark(question_id=question_objs[index].id))

        knowledge_objs: list[KnowledgePoint] = []
        for index, item in enumerate(data["knowledge"]):
            category = get_or_create_category_path(db, item["category_path"])
            content_hash = knowledge_hash(item["title"], item["content"])
            knowledge = KnowledgePoint(
                title=item["title"],
                content=item["content"],
                kind=item.get("kind", "concept"),
                category_id=category.id,
                aliases=json.dumps(item.get("aliases", []), ensure_ascii=False)
                if item.get("aliases")
                else None,
                status="active",
                source_type="manual",
                content_hash=content_hash,
                simhash=simhash64(f"{item['title']}\n{item['content']}"),
            )
            db.add(knowledge)
            db.flush()
            db.add(
                KnowledgeOrigin(
                    knowledge_id=knowledge.id,
                    source_type="manual",
                    origin_ref=f"demo:knowledge:{index + 1}",
                    raw_snapshot=item["content"],
                    content_hash=content_hash,
                )
            )
            for q_index in item.get("question_indexes", []):
                if 0 <= q_index < len(question_objs):
                    db.add(
                        QuestionKnowledge(
                            question_id=question_objs[q_index].id,
                            knowledge_id=knowledge.id,
                            relation_type="related",
                        )
                    )
            knowledge_objs.append(knowledge)

        # 导入批次样例
        batches = []
        for idx, (name, fmt, total, ok, fail, days) in enumerate(
            [
                ("2026秋招面经汇总.csv", "csv", 86, 79, 7, 2),
                ("network-baGu.md", "md", 34, 31, 3, 3),
                ("os-questions.json", "json", 52, 52, 0, 4),
            ]
        ):
            batch = ImportBatch(
                filename=name,
                format=fmt,
                status="success" if fail == 0 else "partial",
                total_rows=total,
                ok_rows=ok,
                fail_rows=fail,
                operator="admin",
                file_hash=f"demo-file-hash-{idx + 1}",
                error_log=json.dumps(
                    {"errors": [], "warnings": []}, ensure_ascii=False
                ),
                created_at=_local_utc(days),
                finished_at=_local_utc(days),
            )
            db.add(batch)
            db.flush()
            batches.append(batch)

        # 爬虫源与任务样例
        github_source = CrawlSource(
            name="GitHub · CS-Notes 面经仓库",
            source_kind="github",
            url="https://github.com/CyC2018/CS-Notes",
            enabled=1,
            interval_sec=10,
            timeout_sec=15,
            max_retries=3,
            max_files_per_run=100,
            last_run_at=_local_utc(1),
        )
        nowcoder_source = CrawlSource(
            name="牛客公开面经列表(M2)",
            source_kind="nowcoder",
            url="https://www.nowcoder.com/discuss",
            enabled=0,
        )
        db.add_all([github_source, nowcoder_source])
        db.flush()
        task = CrawlTask(
            source_id=github_source.id,
            status="success",
            attempt=1,
            total_files=3,
            success_files=3,
            failed_files=0,
            log="演示任务：3 个示例 Markdown 文件。真实仓库采集请在采集页运行。",
            created_at=_local_utc(2),
            started_at=_local_utc(2),
            finished_at=_local_utc(2),
        )
        db.add(task)
        db.flush()
        for file_index, path in enumerate(
            ["README.md", "docs/network.md", "docs/operating-system.md"]
        ):
            db.add(
                CrawlTaskFile(
                    task_id=task.id,
                    url=f"https://raw.githubusercontent.com/CyC2018/CS-Notes/master/{path}",
                    status="success",
                    http_status=200,
                    parsed_count=12 + file_index * 4,
                    fetched_at=_local_utc(2),
                )
            )

        # 待审区样例
        pending_specs = [
            {
                "item_type": "question",
                "source_type": "crawler",
                "origin_ref": "github · CS-Notes README.md 第42行",
                "stem": "什么是 HTTP 长连接与短连接？",
                "answer": "短连接每次请求新建 TCP，长连接 Keep-Alive 复用连接减少握手开销。",
                "meta": {
                    "tags": ["HTTP"],
                    "category_path": "后端开发/计算机网络/HTTP",
                    "difficulty": 2,
                    "frequency": "high",
                    "confidence": 0.75,
                },
                "confidence": 0.9,
            },
            {
                "item_type": "question",
                "source_type": "import",
                "origin_ref": "import · 面经整理.csv 第7行",
                "stem": "红黑树的特点和应用场景？",
                "answer": "近似平衡二叉树，插入删除旋转维护黑高平衡，用于 TreeMap/TreeSet、Linux 调度。",
                "meta": {
                    "tags": ["数据结构"],
                    "category_path": "算法ML/算法/数据结构",
                    "difficulty": 4,
                    "frequency": "mid",
                    "confidence": 0.7,
                },
                "confidence": 0.85,
            },
            {
                "item_type": "question",
                "source_type": "crawler",
                "origin_ref": "github · interview.md 第118行",
                "stem": "操作系统怎么处理缺页中断？",
                "answer": "触发缺页异常，操作系统选页置换，将所需页从磁盘调入，更新页表。",
                "meta": {
                    "tags": ["操作系统", "内存"],
                    "category_path": "后端开发/操作系统/内存",
                    "difficulty": 4,
                    "frequency": "high",
                    "confidence": 0.8,
                },
                "confidence": 0.9,
                "dup_of": question_objs[10].id,
            },
            {
                "item_type": "question",
                "source_type": "import",
                "origin_ref": "import · 八股.json",
                "stem": "什么是 CAP 理论？",
                "answer": "分布式系统一致性、可用性、分区容忍性三者不可兼得，网络分区必然发生，故在 CP/AP 间取舍。",
                "meta": {
                    "tags": ["分布式"],
                    "category_path": "后端开发/分布式/MQ",
                    "difficulty": 3,
                    "frequency": "high",
                    "confidence": 0.65,
                },
                "confidence": 0.9,
            },
            {
                "item_type": "question",
                "source_type": "crawler",
                "origin_ref": "crawler · 牛客公开帖(M2占位)",
                "stem": "聊聊消息队列如何保证不重复消费？",
                "answer": "唯一消费键 + 幂等表，消费端去重；配合手动 ack。",
                "meta": {
                    "tags": ["消息队列", "幂等"],
                    "category_path": "后端开发/分布式/MQ",
                    "difficulty": 3,
                    "frequency": "mid",
                    "confidence": 0.6,
                },
                "confidence": 0.85,
                "dup_of": question_objs[8].id,
            },
            {
                "item_type": "question",
                "source_type": "import",
                "origin_ref": "github · backend.md 第9行",
                "stem": "(疑似)空题/广告水印片段",
                "answer": "——",
                "meta": {
                    "tags": [],
                    "difficulty": None,
                    "frequency": None,
                    "confidence": 0.1,
                    "suggest_reject": True,
                },
                "confidence": 0.2,
            },
            {
                "item_type": "knowledge",
                "source_type": "crawler",
                "origin_ref": "github · CS-Notes network.md 第66行",
                "knowledge_title": "HTTP 长连接",
                "knowledge_content": "HTTP/1.1 默认使用 Keep-Alive 复用 TCP 连接，减少频繁握手与慢启动开销；可通过 Connection: close 关闭。",
                "meta": {
                    "tags": ["HTTP"],
                    "category_path": "后端开发/计算机网络/HTTP",
                    "knowledge_category_id": None,
                    "confidence": 0.7,
                },
                "confidence": 0.8,
            },
            {
                "item_type": "knowledge",
                "source_type": "import",
                "origin_ref": "import · 八股.json#12",
                "knowledge_title": "CAP 理论",
                "knowledge_content": "一致性、可用性、分区容忍性无法同时满足；网络分区发生时需在 CP 与 AP 之间取舍。",
                "meta": {
                    "tags": ["分布式"],
                    "category_path": "后端开发/分布式/MQ",
                    "confidence": 0.6,
                },
                "confidence": 0.85,
            },
        ]
        for spec in pending_specs:
            meta = dict(spec["meta"])
            if meta.get("category_path"):
                category = get_or_create_category_path(
                    db, meta["category_path"].split("/")
                )
                if spec["item_type"] == "knowledge":
                    meta["knowledge_category_id"] = category.id
                else:
                    meta["category_id"] = category.id
            if spec["item_type"] == "question":
                content_hash = question_hash(spec["stem"])
                simhash = simhash64(spec["stem"])
                db.add(
                    PendingItem(
                        item_type="question",
                        source_type=spec["source_type"],
                        import_batch_id=batches[0].id
                        if spec["source_type"] == "import"
                        else None,
                        crawl_task_id=task.id
                        if spec["source_type"] == "crawler"
                        else None,
                        origin_ref=spec["origin_ref"],
                        raw_text=spec["stem"],
                        stem=spec["stem"],
                        answer=spec["answer"],
                        suggested_meta=json.dumps(meta, ensure_ascii=False),
                        parse_confidence=spec["confidence"],
                        content_hash=content_hash,
                        simhash=simhash,
                        dup_of=spec.get("dup_of"),
                        status="pending",
                    )
                )
            else:
                content_hash = knowledge_hash(
                    spec["knowledge_title"], spec["knowledge_content"]
                )
                db.add(
                    PendingItem(
                        item_type="knowledge",
                        source_type=spec["source_type"],
                        import_batch_id=batches[1].id
                        if spec["source_type"] == "import"
                        else None,
                        crawl_task_id=task.id
                        if spec["source_type"] == "crawler"
                        else None,
                        origin_ref=spec["origin_ref"],
                        raw_text=spec["knowledge_content"],
                        knowledge_title=spec["knowledge_title"],
                        knowledge_content=spec["knowledge_content"],
                        suggested_meta=json.dumps(meta, ensure_ascii=False),
                        parse_confidence=spec["confidence"],
                        content_hash=content_hash,
                        simhash=simhash64(
                            f"{spec['knowledge_title']}\n{spec['knowledge_content']}"
                        ),
                        status="pending",
                    )
                )

        db.add(
            AuditLog(
                actor="system",
                action="seed_demo",
                target_type="database",
                detail=f"questions={len(question_objs)}, knowledge={len(knowledge_objs)}",
            )
        )
        db.commit()

    print(
        f"演示数据写入完成：{len(data['questions'])} 道题，{len(data['knowledge'])} 条知识，"
        f"8 个岗位板块，8 条待审，3 个导入批次，2 个爬虫源。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化八股文复习系统演示数据")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="删除当前数据库并重新生成演示数据（会丢失已有数据）",
    )
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
