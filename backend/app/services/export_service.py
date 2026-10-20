"""题库/知识库导出（Markdown 与组合 JSON，可回环导入）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Company,
    KnowledgePoint,
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionKnowledge,
    QuestionOrigin,
    QuestionTag,
    Tag,
)
from .categories import category_map, category_path, descendant_ids
from .serializers import json_list, mastery_from_q


def _category_parts(db: Session, question_id: int, mapping) -> list[str]:
    category_ids = db.scalars(
        select(QuestionCategory.category_id).where(
            QuestionCategory.question_id == question_id
        )
    ).all()
    if not category_ids:
        return []
    paths = [category_path(category_id, mapping) for category_id in category_ids]
    path = max(paths, key=lambda item: (item.count("/"), len(item)))
    return [part for part in path.split("/") if part]


def _tag_names(db: Session, question_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Tag.name)
            .join(QuestionTag, QuestionTag.tag_id == Tag.id)
            .where(QuestionTag.question_id == question_id)
            .order_by(Tag.name)
        ).all()
    )


def _company_names(db: Session, question_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Company.name)
            .join(QuestionCompany, QuestionCompany.company_id == Company.id)
            .where(QuestionCompany.question_id == question_id)
            .order_by(Company.name)
        ).all()
    )


def _scope_questions(db: Session, category_id: int | None) -> list[Question]:
    stmt = select(Question).where(
        Question.status == "active", Question.is_deleted == 0
    )
    if category_id:
        ids = descendant_ids(db, category_id)
        if not ids:
            return []
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCategory.question_id).where(
                    QuestionCategory.category_id.in_(ids)
                )
            )
        )
    return list(db.scalars(stmt.order_by(Question.id)).all())


def export_json(db: Session, category_id: int | None = None) -> dict[str, Any]:
    mapping = category_map(db)
    questions = _scope_questions(db, category_id)
    knowledge = list(
        db.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.status == "active", KnowledgePoint.is_deleted == 0)
            .order_by(KnowledgePoint.id)
        ).all()
    )
    question_payload = []
    for question in questions:
        question_payload.append(
            {
                "stem": question.stem,
                "answer": question.answer or "",
                "key_points": json_list(question.key_points),
                "category_path": _category_parts(db, question.id, mapping),
                "tags": _tag_names(db, question.id),
                "difficulty": question.difficulty,
                "frequency": question.frequency,
                "companies": _company_names(db, question.id),
                "notes": question.notes or "",
            }
        )
    knowledge_payload = []
    for item in knowledge:
        knowledge_payload.append(
            {
                "ref": f"kp-{item.id}",
                "title": item.title,
                "content": item.content,
                "kind": item.kind,
                "category_path": [
                    part
                    for part in category_path(item.category_id, mapping).split("/")
                    if part
                ],
                "aliases": json_list(item.aliases),
            }
        )
    index_by_question = {question.id: index for index, question in enumerate(questions)}
    knowledge_refs = {item.id: f"kp-{item.id}" for item in knowledge}
    links = []
    for question_id, knowledge_id, relation in db.execute(
        select(
            QuestionKnowledge.question_id,
            QuestionKnowledge.knowledge_id,
            QuestionKnowledge.relation_type,
        )
    ).all():
        if question_id in index_by_question and knowledge_id in knowledge_refs:
            links.append(
                {
                    "question_index": index_by_question[question_id],
                    "knowledge_ref": knowledge_refs[knowledge_id],
                    "relation_type": relation,
                }
            )
    return {
        "schema_version": 1,
        "questions": question_payload,
        "knowledge": knowledge_payload,
        "links": links,
    }


def _md_line(label: str, value: Any) -> str:
    if value is None or value == "" or value == []:
        return ""
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    return f"**{label}**：{value}"


def export_markdown(db: Session, category_id: int | None = None) -> str:
    mapping = category_map(db)
    questions = _scope_questions(db, category_id)
    knowledge = list(
        db.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.status == "active", KnowledgePoint.is_deleted == 0)
            .order_by(KnowledgePoint.id)
        ).all()
    )
    lines: list[str] = []
    for question in questions:
        lines.append(f"## 题目：{question.stem}")
        if question.answer:
            lines.append(f"**答案**：{question.answer}")
        key_points = json_list(question.key_points)
        if key_points:
            lines.append(_md_line("要点", "；".join(key_points)))
        tags = _tag_names(db, question.id)
        if tags:
            lines.append(_md_line("标签", tags))
        if question.difficulty:
            lines.append(_md_line("难度", question.difficulty))
        if question.frequency:
            lines.append(_md_line("频率", question.frequency))
        companies = _company_names(db, question.id)
        if companies:
            lines.append(_md_line("公司", companies))
        parts = _category_parts(db, question.id, mapping)
        if parts:
            lines.append(_md_line("分类", "/".join(parts)))
        if question.notes:
            lines.append(_md_line("笔记", question.notes))
        lines.append("")
    for item in knowledge:
        lines.append(f"## 知识：{item.title}")
        lines.append(_md_line("类型", item.kind))
        path = category_path(item.category_id, mapping)
        if path:
            lines.append(_md_line("分类", path))
        aliases = json_list(item.aliases)
        if aliases:
            lines.append(_md_line("别名", aliases))
        lines.append(_md_line("内容", item.content))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


MISTAKE_REASON_LABELS = {
    "unfamiliar": "自评不熟自动收录",
    "manual": "手动加入",
    "auto_pass_twice": "连续通过后自动移出",
}


def mistake_markdown(db: Session, items: list[dict[str, Any]]) -> str:
    """错题本 Markdown：按最近收录时间倒序，带掌握度、原因与来源。"""
    lines = ["# 错题本", f"共 {len(items)} 道", ""]
    origin_lines: dict[int, list[str]] = {}
    if items:
        for question_id, source_type, origin_ref in db.execute(
            select(
                QuestionOrigin.question_id,
                QuestionOrigin.source_type,
                QuestionOrigin.origin_ref,
            )
            .where(QuestionOrigin.question_id.in_([item["id"] for item in items]))
            .order_by(QuestionOrigin.id.desc())
        ).all():
            origin_lines.setdefault(question_id, []).append(f"{source_type}:{origin_ref}")
    for index, item in enumerate(items, start=1):
        question = db.get(Question, item["id"])
        lines.append(f"## {index}. {item['stem']}")
        lines.append(_md_line("掌握度", mastery_from_q(item["schedule"]["last_q"])))
        lines.append(_md_line("收录时间", item["added_at"]))
        lines.append(_md_line("收录原因", MISTAKE_REASON_LABELS.get(item["reason"], item["reason"])))
        if item.get("category_path"):
            lines.append(_md_line("分类", item["category_path"]))
        tags = [tag["name"] for tag in item.get("tags", [])]
        if tags:
            lines.append(_md_line("标签", tags))
        if question is not None and question.answer:
            lines.append(f"**答案**：{question.answer}")
        origins = origin_lines.get(item["id"], [])[:5]
        if origins:
            lines.append(_md_line("来源", origins))
        lines.append(_md_line("下次复习", item["schedule"].get("next_review_date")))
        lines.append("")
    return "\n".join(lines).strip() + "\n"
