"""Collections = saved query + manually pinned sessions (hybrid). Owner-scoped."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from ..auth import Principal, optional_principal, require_user
from ..db import get_session
from ..models import Collection, Session, Visibility
from ..schemas import SessionListOut
from .sessions import query_sessions, summarize

router = APIRouter(prefix="/v0/collections", tags=["collections"])


class CollectionIn(BaseModel):
    name: str
    query: dict = {}  # {agent?, favorite?, tag?, q?}


class CollectionOut(BaseModel):
    id: str
    name: str
    query: dict
    pinned: list[str]
    created_at: str


class PinIn(BaseModel):
    session_id: str


def _out(c: Collection) -> CollectionOut:
    return CollectionOut(id=c.id, name=c.name, query=c.query, pinned=c.pinned,
                         created_at=c.created_at.isoformat())


def _owned(db: DBSession, collection_id: str, p: Principal) -> Collection:
    c = db.get(Collection, collection_id)
    if c is None or c.owner_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return c


@router.get("", response_model=list[CollectionOut])
def list_collections(p: Principal = Depends(require_user),
                     db: DBSession = Depends(get_session)) -> list[CollectionOut]:
    rows = db.exec(
        select(Collection).where(Collection.owner_id == p.id).order_by(col(Collection.created_at))
    ).all()
    return [_out(c) for c in rows]


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
def create_collection(body: CollectionIn, p: Principal = Depends(require_user),
                      db: DBSession = Depends(get_session)) -> CollectionOut:
    c = Collection(name=body.name, query=body.query, owner_id=p.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _out(c)


@router.get("/{collection_id}", response_model=CollectionOut)
def get_collection(collection_id: str, p: Principal = Depends(require_user),
                   db: DBSession = Depends(get_session)) -> CollectionOut:
    return _out(_owned(db, collection_id, p))


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(collection_id: str, p: Principal = Depends(require_user),
                      db: DBSession = Depends(get_session)) -> Response:
    db.delete(_owned(db, collection_id, p))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{collection_id}/sessions/{session_id}", response_model=CollectionOut)
def pin_session(collection_id: str, session_id: str, p: Principal = Depends(require_user),
                db: DBSession = Depends(get_session)) -> CollectionOut:
    c = _owned(db, collection_id, p)
    if db.get(Session, session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if session_id not in c.pinned:
        c.pinned = [*c.pinned, session_id]  # reassign so SQLAlchemy detects the change
        db.add(c)
        db.commit()
        db.refresh(c)
    return _out(c)


@router.delete("/{collection_id}/sessions/{session_id}", response_model=CollectionOut)
def unpin_session(collection_id: str, session_id: str, p: Principal = Depends(require_user),
                  db: DBSession = Depends(get_session)) -> CollectionOut:
    c = _owned(db, collection_id, p)
    if session_id in c.pinned:
        c.pinned = [x for x in c.pinned if x != session_id]
        db.add(c)
        db.commit()
        db.refresh(c)
    return _out(c)


@router.get("/{collection_id}/sessions", response_model=SessionListOut)
def resolve_collection(collection_id: str, p: Principal = Depends(require_user),
                       db: DBSession = Depends(get_session)) -> SessionListOut:
    """Members = sessions matching the saved query ∪ manually pinned sessions."""
    c = _owned(db, collection_id, p)
    q = c.query or {}
    # Only run the saved query if it actually has a filter — an empty query means
    # "manual-only" (just the pins), NOT "match everything".
    has_filter = any(q.get(k) for k in ("agent", "project_id", "favorite", "tag", "q"))
    matched = []
    if has_filter:
        matched, _ = query_sessions(
            db, p, agent=q.get("agent"), favorite=q.get("favorite"),
            tag=q.get("tag"), q=q.get("q"), limit=200,
        )
    seen = {s.id for s in matched}
    # pinned first (so manual picks lead), then query matches not already present
    pinned_summaries = []
    for sid in c.pinned:
        if sid in seen:
            continue
        s = db.get(Session, sid)
        if s and (s.visibility == Visibility.public or p is not None):
            pinned_summaries.append(summarize(db, s))
            seen.add(sid)
    members = pinned_summaries + matched
    return SessionListOut(sessions=members, total=len(members))
