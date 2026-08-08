"""Catalog endpoints: the vocabularies the list filters are built from.

`GET /v0/sessions` has always accepted `project_id` and `tag`, but nothing told a
client which projects or tags exist — and the CLI sends a project *name*, not an id,
so the filter was effectively unreachable from outside the database.
"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from ..auth import Principal, optional_principal
from ..db import get_session
from ..models import Project, Session
from ..schemas import ProjectOut, TagOut
from .sessions import _visibility_filter

router = APIRouter(prefix="/v0", tags=["catalog"])


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: DBSession = Depends(get_session),
                  principal: Principal | None = Depends(optional_principal)) -> list[ProjectOut]:
    """Projects that have at least one session this caller can see, with counts."""
    visible = _visibility_filter(select(Session.project_id), principal).subquery()
    stmt = (
        select(Project.id, Project.name, func.count(visible.c.project_id))
        .join(visible, visible.c.project_id == Project.id)
        .group_by(col(Project.id), col(Project.name))
        .order_by(func.count(visible.c.project_id).desc(), col(Project.name))
    )
    return [ProjectOut(id=pid, name=name, session_count=n) for pid, name, n in db.exec(stmt).all()]


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DBSession = Depends(get_session),
              principal: Principal | None = Depends(optional_principal),
              limit: int = Query(default=100, le=500)) -> list[TagOut]:
    """Tags in use, most common first.

    Tags live in a JSON array, so the tally happens in Python — but only over the
    one narrow `tags_text` column, never whole session rows.
    """
    stmt = _visibility_filter(select(Session.tags_text), principal)
    counter: Counter[str] = Counter()
    for text in db.exec(stmt).all():
        if text:
            counter.update(t for t in text.split("|") if t)
    return [TagOut(tag=tag, session_count=n) for tag, n in counter.most_common(limit)]
