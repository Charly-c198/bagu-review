"""知识图谱基础版（M2）：由题-知识关联推导知识节点与共现边。"""

from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import (
    KnowledgePoint,
    Question,
    QuestionKnowledge,
    ReviewSchedule,
    User,
)
from ..security import get_current_user
from ..services.categories import category_map, category_path, descendant_ids
from ..services.serializers import mastery_from_q
from ..utils.text import truncate

router = APIRouter(prefix="/graph", tags=["graph"])


def _knowledge_label(knowledge: KnowledgePoint) -> str:
    return truncate(knowledge.title, 42)


def _build_nodes(db: Session, selected: list[int], limit: int):
    knowledge_rows = db.scalars(
        select(KnowledgePoint).where(
            KnowledgePoint.id.in_(selected),
            KnowledgePoint.is_deleted == 0,
        )
    ).all()
    cmap = category_map(db)
    nodes = [
        {
            "id": f"k{knowledge.id}",
            "type": "knowledge",
            "label": _knowledge_label(knowledge),
            "kind": knowledge.kind,
            "category_path": category_path(knowledge.category_id, cmap)
            if knowledge.category_id
            else "",
        }
        for knowledge in knowledge_rows
    ]
    return nodes[:limit]


@router.get("")
def knowledge_graph(
    knowledge_id: int | None = None,
    category_id: int | None = None,
    include_questions: bool = False,
    limit: int = Query(default=50, ge=10, le=150),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    allowed_ids: set[int] | None = None
    if category_id:
        cat_ids = descendant_ids(db, category_id)
        if not cat_ids:
            return ok({"nodes": [], "edges": [], "stats": {"knowledge": 0, "questions": 0}})
        allowed_ids = set(
            db.scalars(
                select(KnowledgePoint.id).where(
                    KnowledgePoint.category_id.in_(cat_ids),
                    KnowledgePoint.status == "active",
                    KnowledgePoint.is_deleted == 0,
                )
            ).all()
        )

    link_counts = dict(
        db.execute(
            select(
                QuestionKnowledge.knowledge_id,
                func.count(func.distinct(QuestionKnowledge.question_id)),
            )
            .join(Question, Question.id == QuestionKnowledge.question_id)
            .where(Question.status == "active", Question.is_deleted == 0)
            .group_by(QuestionKnowledge.knowledge_id)
        ).all()
    )

    seed_ids: list[int]
    if knowledge_id:
        knowledge = db.get(KnowledgePoint, knowledge_id)
        if knowledge is None or knowledge.is_deleted:
            raise ApiError(404, "NOT_FOUND", "知识条目不存在")
        seed_ids = [knowledge.id]
        # 一跳：与该知识共享题目的其他知识。
        shared_question_ids = select(QuestionKnowledge.question_id).where(
            QuestionKnowledge.knowledge_id == knowledge.id
        )
        neighbors = db.scalars(
            select(QuestionKnowledge.knowledge_id)
            .where(QuestionKnowledge.question_id.in_(shared_question_ids))
            .distinct()
        ).all()
        seed_ids.extend(int(item) for item in neighbors if int(item) != knowledge.id)
    else:
        ranked = sorted(
            (
                (kid, count)
                for kid, count in link_counts.items()
                if allowed_ids is None or kid in allowed_ids
            ),
            key=lambda item: (-item[1], item[0]),
        )
        seed_ids = [kid for kid, _ in ranked[:limit]]
        if not seed_ids:
            # 没有关联时，退回最近更新的知识条目，保证图谱页可用。
            recent = db.scalars(
                select(KnowledgePoint.id)
                .where(
                    KnowledgePoint.status == "active",
                    KnowledgePoint.is_deleted == 0,
                )
                .order_by(KnowledgePoint.updated_at.desc(), KnowledgePoint.id.desc())
                .limit(limit)
            ).all()
            seed_ids = [
                int(kid)
                for kid in recent
                if allowed_ids is None or int(kid) in allowed_ids
            ]

    if allowed_ids is not None:
        seed_ids = [kid for kid in seed_ids if kid in allowed_ids]
    # 按关联题数排序后截断，保证重点知识优先出现。
    seed_ids = sorted(
        set(seed_ids), key=lambda kid: (-link_counts.get(kid, 0), kid)
    )[:limit]

    links = db.execute(
        select(
            QuestionKnowledge.question_id,
            QuestionKnowledge.knowledge_id,
            QuestionKnowledge.relation_type,
        ).where(QuestionKnowledge.knowledge_id.in_(seed_ids))
    ).all()
    by_question: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for question_id, kid, relation in links:
        by_question[int(question_id)].append((int(kid), relation))

    edge_weights: Counter[tuple[int, int]] = Counter()
    for pairs in by_question.values():
        ids = sorted({kid for kid, _ in pairs})
        for index, left in enumerate(ids):
            for right in ids[index + 1 :]:
                edge_weights[(left, right)] += 1

    nodes = _build_nodes(db, seed_ids, limit)
    selected_set = set(seed_ids)
    edges = [
        {
            "id": f"k{left}-k{right}",
            "source": f"k{left}",
            "target": f"k{right}",
            "type": "co_occurrence",
            "relation": "shared_question",
            "weight": weight,
        }
        for (left, right), weight in edge_weights.items()
        if left in selected_set and right in selected_set
    ]

    question_nodes = 0
    if include_questions:
        question_ids = [qid for qid in by_question if qid][:limit]
        questions = db.scalars(
            select(Question).where(
                Question.id.in_(question_ids),
                Question.status == "active",
                Question.is_deleted == 0,
            )
        ).all()
        schedules = {
            row.question_id: row
            for row in db.scalars(
                select(ReviewSchedule).where(
                    ReviewSchedule.question_id.in_(question_ids)
                )
            ).all()
        }
        for question in questions:
            nodes.append(
                {
                    "id": f"q{question.id}",
                    "type": "question",
                    "label": truncate(question.stem, 34),
                    "kind": "",
                    "category_path": "",
                    "mastery": mastery_from_q(
                        schedules[question.id].last_q
                        if question.id in schedules
                        else None
                    ),
                }
            )
            question_nodes += 1
            for kid, relation in by_question.get(question.id, []):
                if kid in selected_set:
                    edges.append(
                        {
                            "id": f"q{question.id}-k{kid}",
                            "source": f"q{question.id}",
                            "target": f"k{kid}",
                            "type": "question_knowledge",
                            "relation": relation,
                            "weight": 1,
                        }
                    )

    return ok(
        {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "knowledge": len(nodes) - question_nodes,
                "questions": question_nodes,
                "edges": len(edges),
            },
            "definitions_version": "V0.4-1.5",
        }
    )
