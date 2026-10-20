"""标签与公司字典路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import Company, QuestionCompany, QuestionTag, Tag, User
from ..schemas import CompanyCreate, TagCreate
from ..security import get_current_user
from ..services.audit import audit
from ..services.categories import get_or_create_company, get_or_create_tag

router = APIRouter(tags=["taxonomy"])


@router.get("/tags")
def list_tags(
    q: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(Tag).order_by(Tag.name)
    if q:
        stmt = stmt.where(func.lower(Tag.name).like(f"%{q.lower()}%"))
    tags = db.scalars(stmt).all()
    counts = dict(
        db.execute(
            select(QuestionTag.tag_id, func.count(QuestionTag.question_id)).group_by(
                QuestionTag.tag_id
            )
        ).all()
    )
    return ok(
        [
            {"id": t.id, "name": t.name, "question_count": int(counts.get(t.id, 0))}
            for t in tags
        ]
    )


@router.post("/tags")
def create_tag(
    payload: TagCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    tag = get_or_create_tag(db, payload.name)
    audit(db, "tag_create", "tag", tag.id, {"name": tag.name})
    db.commit()
    return ok({"id": tag.id, "name": tag.name})


@router.patch("/tags/{tag_id}")
def update_tag(
    tag_id: int,
    payload: TagCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise ApiError(404, "NOT_FOUND", "标签不存在")
    if db.scalar(
        select(Tag).where(
            func.lower(Tag.name) == payload.name.strip().lower(), Tag.id != tag_id
        )
    ):
        raise ApiError(409, "CONFLICT", "标签名已存在")
    tag.name = payload.name.strip()
    db.commit()
    return ok({"id": tag.id, "name": tag.name})


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise ApiError(404, "NOT_FOUND", "标签不存在")
    audit(db, "tag_delete", "tag", tag.id, {"name": tag.name})
    db.delete(tag)
    db.commit()
    return ok(None, "已删除")


@router.get("/companies")
def list_companies(
    q: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(Company).order_by(Company.name)
    if q:
        stmt = stmt.where(func.lower(Company.name).like(f"%{q.lower()}%"))
    companies = db.scalars(stmt).all()
    counts = dict(
        db.execute(
            select(
                QuestionCompany.company_id, func.count(QuestionCompany.question_id)
            ).group_by(QuestionCompany.company_id)
        ).all()
    )
    return ok(
        [
            {
                "id": c.id,
                "name": c.name,
                "question_count": int(counts.get(c.id, 0)),
            }
            for c in companies
        ]
    )


@router.post("/companies")
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    company = get_or_create_company(db, payload.name)
    audit(db, "company_create", "company", company.id, {"name": company.name})
    db.commit()
    return ok({"id": company.id, "name": company.name})


@router.patch("/companies/{company_id}")
def update_company(
    company_id: int,
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    company = db.get(Company, company_id)
    if company is None:
        raise ApiError(404, "NOT_FOUND", "公司不存在")
    if db.scalar(
        select(Company).where(
            func.lower(Company.name) == payload.name.strip().lower(),
            Company.id != company_id,
        )
    ):
        raise ApiError(409, "CONFLICT", "公司名已存在")
    company.name = payload.name.strip()
    db.commit()
    return ok({"id": company.id, "name": company.name})


@router.delete("/companies/{company_id}")
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    company = db.get(Company, company_id)
    if company is None:
        raise ApiError(404, "NOT_FOUND", "公司不存在")
    audit(db, "company_delete", "company", company.id, {"name": company.name})
    db.delete(company)
    db.commit()
    return ok(None, "已删除")
