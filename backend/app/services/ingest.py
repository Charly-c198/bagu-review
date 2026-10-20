"""导入/爬虫共用的清洗、去重、待审写入管线。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    KnowledgeOrigin,
    PendingItem,
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionOrigin,
    QuestionTag,
    ReviewSchedule,
)
from ..utils.text import (
    knowledge_hash,
    question_hash,
    simhash64,
)
from .categories import (
    get_or_create_category_path,
    get_or_create_company,
    get_or_create_tag,
)
from .dedupe import (
    find_exact_knowledge,
    find_exact_pending_knowledge,
    find_exact_pending_question,
    find_exact_question,
    find_near_knowledge,
    find_near_pending,
    find_near_questions,
)
from .import_parsers import ParsedKnowledge, ParsedQuestion, ParseResult
from .settings_service import get_settings
from .tagging import suggest_meta


@dataclass
class IngestOutcome:
    pending_created: int = 0
    questions_created: int = 0
    knowledge_created: int = 0
    duplicates: int = 0
    warnings: list[dict] = field(default_factory=list)
    question_ids: list[int] = field(default_factory=list)
    knowledge_ids: list[int] = field(default_factory=list)


def _ref(prefix: str, line: int) -> str:
    return f"{prefix}:{line}" if prefix else str(line)


def _merge_meta(
    db: Session,
    parsed: ParsedQuestion | ParsedKnowledge,
    item_type: str,
) -> dict[str, Any]:
    text = (
        f"{parsed.stem}\n{parsed.answer}"  # type: ignore[union-attr]
        if isinstance(parsed, ParsedQuestion)
        else f"{parsed.title}\n{parsed.content}"
    )
    meta = suggest_meta(db, text, item_type=item_type)
    if isinstance(parsed, ParsedQuestion):
        parsed_tags = parsed.tags
        parsed_difficulty = parsed.difficulty
        parsed_frequency = parsed.frequency
        parsed_path = parsed.category_path
    else:
        parsed_tags = []
        parsed_difficulty = None
        parsed_frequency = None
        parsed_path = parsed.category_path

    tags = list(dict.fromkeys([*meta.get("tags", []), *parsed_tags]))
    tag_ids = list(dict.fromkeys(meta.get("tag_ids", [])))
    if parsed_tags:
        # 显式标签优先，避免导入回环时多出规则建议标签。
        tags = list(dict.fromkeys(parsed_tags))
        tag_ids = []
    for name in parsed_tags:
        tag = get_or_create_tag(db, name)
        if tag.id not in tag_ids:
            tag_ids.append(tag.id)
    meta["tags"] = tags
    meta["tag_ids"] = tag_ids

    if parsed_path:
        category = get_or_create_category_path(db, parsed_path)
        meta["category_path"] = "/".join(parsed_path)
        if item_type == "knowledge":
            meta["knowledge_category_id"] = category.id
        else:
            meta["category_id"] = category.id
    if parsed_difficulty is not None:
        meta["difficulty"] = parsed_difficulty
    if parsed_frequency is not None:
        meta["frequency"] = parsed_frequency
    if isinstance(parsed, ParsedQuestion):
        meta["key_points"] = parsed.key_points
        meta["companies"] = parsed.companies
        meta["notes"] = parsed.notes
    else:
        meta["aliases"] = parsed.aliases
        meta["kind"] = parsed.kind
    meta["item_type"] = item_type
    return meta


def _add_question_origin(
    db: Session,
    question_id: int,
    source_type: str,
    *,
    origin_ref: str | None,
    raw_snapshot: str | None,
    content_hash: str | None,
    import_batch_id: int | None = None,
    crawl_task_id: int | None = None,
    source_id: int | None = None,
) -> None:
    if origin_ref:
        exists = db.scalar(
            select(QuestionOrigin.id).where(
                QuestionOrigin.question_id == question_id,
                QuestionOrigin.source_type == source_type,
                QuestionOrigin.origin_ref == origin_ref,
            )
        )
        if exists:
            return
    db.add(
        QuestionOrigin(
            question_id=question_id,
            source_type=source_type,
            source_id=source_id,
            import_batch_id=import_batch_id,
            crawl_task_id=crawl_task_id,
            origin_ref=origin_ref,
            raw_snapshot=raw_snapshot,
            content_hash=content_hash,
        )
    )


def _add_knowledge_origin(
    db: Session,
    knowledge_id: int,
    source_type: str,
    *,
    origin_ref: str | None,
    raw_snapshot: str | None,
    content_hash: str | None,
    import_batch_id: int | None = None,
    crawl_task_id: int | None = None,
    source_id: int | None = None,
) -> None:
    if origin_ref:
        exists = db.scalar(
            select(KnowledgeOrigin.id).where(
                KnowledgeOrigin.knowledge_id == knowledge_id,
                KnowledgeOrigin.source_type == source_type,
                KnowledgeOrigin.origin_ref == origin_ref,
            )
        )
        if exists:
            return
    db.add(
        KnowledgeOrigin(
            knowledge_id=knowledge_id,
            source_type=source_type,
            source_id=source_id,
            import_batch_id=import_batch_id,
            crawl_task_id=crawl_task_id,
            origin_ref=origin_ref,
            raw_snapshot=raw_snapshot,
            content_hash=content_hash,
        )
    )


def apply_meta_to_question(
    db: Session, question: Question, meta: dict[str, Any], parsed: ParsedQuestion | None = None
) -> None:
    category_ids: list[int] = []
    if parsed and parsed.category_path:
        category_ids.append(get_or_create_category_path(db, parsed.category_path).id)
    if meta.get("category_id"):
        category_ids.append(int(meta["category_id"]))
    if not category_ids and meta.get("category_path"):
        category_ids.append(
            get_or_create_category_path(db, str(meta["category_path"]).split("/")).id
        )
    for category_id in dict.fromkeys(category_ids):
        if db.get(QuestionCategory, (question.id, category_id)) is None:
            db.add(
                QuestionCategory(question_id=question.id, category_id=category_id)
            )

    tag_ids: list[int] = list(meta.get("tag_ids") or [])
    for name in meta.get("tags") or []:
        tag_ids.append(get_or_create_tag(db, str(name)).id)
    if parsed:
        for name in parsed.tags:
            tag_ids.append(get_or_create_tag(db, name).id)
    for tag_id in dict.fromkeys(tag_ids):
        if db.get(QuestionTag, (question.id, tag_id)) is None:
            db.add(QuestionTag(question_id=question.id, tag_id=tag_id))

    company_names = list(parsed.companies) if parsed else []
    for name in company_names:
        company = get_or_create_company(db, name)
        if db.get(QuestionCompany, (question.id, company.id)) is None:
            db.add(
                QuestionCompany(question_id=question.id, company_id=company.id)
            )

    if question.difficulty is None:
        question.difficulty = parsed.difficulty if parsed and parsed.difficulty else meta.get("difficulty")
    if question.frequency is None:
        question.frequency = parsed.frequency if parsed and parsed.frequency else meta.get("frequency")


def create_active_question(
    db: Session,
    parsed: ParsedQuestion,
    meta: dict[str, Any],
    *,
    source_type: str,
    origin_ref: str | None,
    import_batch_id: int | None = None,
    crawl_task_id: int | None = None,
    source_id: int | None = None,
) -> Question:
    content_hash = question_hash(parsed.stem)
    question = Question(
        stem=parsed.stem,
        answer=parsed.answer or None,
        key_points=json.dumps(parsed.key_points, ensure_ascii=False)
        if parsed.key_points
        else None,
        notes=parsed.notes or None,
        difficulty=parsed.difficulty or meta.get("difficulty"),
        frequency=parsed.frequency or meta.get("frequency"),
        status="active",
        source_type=source_type,
        content_hash=content_hash,
        simhash=simhash64(parsed.stem),
    )
    db.add(question)
    db.flush()
    apply_meta_to_question(db, question, meta, parsed)
    db.add(ReviewSchedule(question_id=question.id))
    _add_question_origin(
        db,
        question.id,
        source_type,
        origin_ref=origin_ref,
        raw_snapshot=parsed.raw,
        content_hash=content_hash,
        import_batch_id=import_batch_id,
        crawl_task_id=crawl_task_id,
        source_id=source_id,
    )
    return question


def ingest_parse_result(
    db: Session,
    parsed: ParseResult,
    *,
    source_type: str,
    origin_prefix: str,
    import_batch_id: int | None = None,
    crawl_task_id: int | None = None,
    source_id: int | None = None,
    origin_is_url: bool = False,
) -> IngestOutcome:
    outcome = IngestOutcome()
    settings = get_settings(db)
    direct_to_active = bool(settings.get("import.direct_to_active")) and source_type == "import"
    if parsed.links:
        # 组合格式含题-知识关联，需要保留待审记录以便审核后建立关联。
        direct_to_active = False
    threshold = int(settings.get("dedupe.simhash_threshold", 3))

    # 组合 JSON 的关联引用。
    knowledge_links: dict[int, list[dict]] = {}
    question_links: dict[str, list[dict]] = {}
    for link in parsed.links:
        q_index = link["question_index"]
        k_ref = link["knowledge_ref"]
        relation = link.get("relation_type", "related")
        knowledge_links.setdefault(q_index, []).append(
            {"ref": k_ref, "relation_type": relation}
        )
        question_links.setdefault(k_ref, []).append(
            {"ref": f"q{q_index}", "relation_type": relation}
        )

    for index, item in enumerate(parsed.questions):
        content_hash = question_hash(item.stem)
        simhash = simhash64(item.stem)
        origin_ref = (
            origin_prefix
            if origin_is_url and origin_prefix
            else _ref(origin_prefix, item.line)
        )
        meta = _merge_meta(db, item, "question")
        if parsed.links:
            meta["question_ref"] = f"q{index}"
            if knowledge_links.get(index):
                meta["link_knowledge_refs"] = knowledge_links[index]

        exact = find_exact_question(db, content_hash)
        if exact is not None:
            _add_question_origin(
                db,
                exact.id,
                source_type,
                origin_ref=origin_ref,
                raw_snapshot=item.raw,
                content_hash=content_hash,
                import_batch_id=import_batch_id,
                crawl_task_id=crawl_task_id,
                source_id=source_id,
            )
            db.add(
                PendingItem(
                    item_type="question",
                    source_type=source_type,
                    import_batch_id=import_batch_id,
                    crawl_task_id=crawl_task_id,
                    origin_ref=origin_ref,
                    raw_text=item.raw,
                    stem=item.stem,
                    answer=item.answer,
                    suggested_meta=json.dumps(meta, ensure_ascii=False),
                    parse_confidence=item.confidence,
                    content_hash=content_hash,
                    simhash=simhash,
                    dup_of=exact.id,
                    created_question_id=exact.id,
                    status="merged",
                    reviewer_note="导入时命中已有题目的精确哈希，已追加来源",
                )
            )
            outcome.duplicates += 1
            db.flush()
            continue

        pending_exact = find_exact_pending_question(db, content_hash)
        if pending_exact is not None:
            db.add(
                PendingItem(
                    item_type="question",
                    source_type=source_type,
                    import_batch_id=import_batch_id,
                    crawl_task_id=crawl_task_id,
                    origin_ref=origin_ref,
                    raw_text=item.raw,
                    stem=item.stem,
                    answer=item.answer,
                    suggested_meta=json.dumps(meta, ensure_ascii=False),
                    parse_confidence=item.confidence,
                    content_hash=content_hash,
                    simhash=simhash,
                    dup_of_pending_id=pending_exact.id,
                    status="merged",
                    reviewer_note="导入时命中待审区的精确哈希",
                )
            )
            outcome.duplicates += 1
            db.flush()
            continue

        near = find_near_questions(db, simhash, threshold=threshold)
        near_pending = find_near_pending(
            db, simhash, "question", threshold=threshold
        )
        if direct_to_active:
            question = create_active_question(
                db,
                item,
                meta,
                source_type=source_type,
                origin_ref=origin_ref,
                import_batch_id=import_batch_id,
                crawl_task_id=crawl_task_id,
                source_id=source_id,
            )
            outcome.questions_created += 1
            outcome.question_ids.append(question.id)
        else:
            pending = PendingItem(
                item_type="question",
                source_type=source_type,
                import_batch_id=import_batch_id,
                crawl_task_id=crawl_task_id,
                origin_ref=origin_ref,
                raw_text=item.raw,
                stem=item.stem,
                answer=item.answer,
                suggested_meta=json.dumps(meta, ensure_ascii=False),
                parse_confidence=item.confidence,
                content_hash=content_hash,
                simhash=simhash,
                dup_of=near[0][0].id if near else None,
                dup_of_pending_id=near_pending[0][0].id if near_pending else None,
                status="pending",
            )
            db.add(pending)
            outcome.pending_created += 1
            if near:
                outcome.warnings.append(
                    {
                        "origin_ref": origin_ref,
                        "message": f"与题目 #{near[0][0].id} 近似（汉明距离 {near[0][1]}）",
                    }
                )
            if near_pending:
                outcome.warnings.append(
                    {
                        "origin_ref": origin_ref,
                        "message": f"与待审题目 #{near_pending[0][0].id} 近似（汉明距离 {near_pending[0][1]}）",
                    }
                )
        db.flush()

    for item in parsed.knowledge:
        content_hash = knowledge_hash(item.title, item.content)
        simhash = simhash64(f"{item.title}\n{item.content}")
        origin_ref = (
            origin_prefix
            if origin_is_url and origin_prefix
            else _ref(origin_prefix, item.line)
        )
        meta = _merge_meta(db, item, "knowledge")
        if item.ref:
            meta["knowledge_ref"] = item.ref
        if item.ref and question_links.get(item.ref):
            meta["link_question_refs"] = question_links[item.ref]

        exact = find_exact_knowledge(db, content_hash)
        if exact is not None:
            _add_knowledge_origin(
                db,
                exact.id,
                source_type,
                origin_ref=origin_ref,
                raw_snapshot=item.raw,
                content_hash=content_hash,
                import_batch_id=import_batch_id,
                crawl_task_id=crawl_task_id,
                source_id=source_id,
            )
            db.add(
                PendingItem(
                    item_type="knowledge",
                    source_type=source_type,
                    import_batch_id=import_batch_id,
                    crawl_task_id=crawl_task_id,
                    origin_ref=origin_ref,
                    raw_text=item.raw,
                    knowledge_title=item.title,
                    knowledge_content=item.content,
                    suggested_meta=json.dumps(meta, ensure_ascii=False),
                    parse_confidence=item.confidence,
                    content_hash=content_hash,
                    simhash=simhash,
                    dup_of_knowledge_id=exact.id,
                    created_knowledge_id=exact.id,
                    status="merged",
                    reviewer_note="导入时命中已有知识的精确哈希，已追加来源",
                )
            )
            outcome.duplicates += 1
            db.flush()
            continue

        pending_exact = find_exact_pending_knowledge(db, content_hash)
        if pending_exact is not None:
            db.add(
                PendingItem(
                    item_type="knowledge",
                    source_type=source_type,
                    import_batch_id=import_batch_id,
                    crawl_task_id=crawl_task_id,
                    origin_ref=origin_ref,
                    raw_text=item.raw,
                    knowledge_title=item.title,
                    knowledge_content=item.content,
                    suggested_meta=json.dumps(meta, ensure_ascii=False),
                    parse_confidence=item.confidence,
                    content_hash=content_hash,
                    simhash=simhash,
                    dup_of_pending_id=pending_exact.id,
                    status="merged",
                    reviewer_note="导入时命中待审区的精确哈希",
                )
            )
            outcome.duplicates += 1
            db.flush()
            continue

        near = find_near_knowledge(db, simhash, threshold=threshold)
        near_pending = find_near_pending(
            db, simhash, "knowledge", threshold=threshold
        )
        pending = PendingItem(
            item_type="knowledge",
            source_type=source_type,
            import_batch_id=import_batch_id,
            crawl_task_id=crawl_task_id,
            origin_ref=origin_ref,
            raw_text=item.raw,
            knowledge_title=item.title,
            knowledge_content=item.content,
            suggested_meta=json.dumps(meta, ensure_ascii=False),
            parse_confidence=item.confidence,
            content_hash=content_hash,
            simhash=simhash,
            dup_of_knowledge_id=near[0][0].id if near else None,
            dup_of_pending_id=near_pending[0][0].id if near_pending else None,
            status="pending",
        )
        db.add(pending)
        outcome.pending_created += 1
        if near:
            outcome.warnings.append(
                {
                    "origin_ref": origin_ref,
                    "message": f"与知识 #{near[0][0].id} 近似（汉明距离 {near[0][1]}）",
                }
            )
        if near_pending:
            outcome.warnings.append(
                {
                    "origin_ref": origin_ref,
                    "message": f"与待审知识 #{near_pending[0][0].id} 近似（汉明距离 {near_pending[0][1]}）",
                }
            )
        db.flush()

    return outcome
