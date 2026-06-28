"""Session endpoints: create, version, get, list, patch. See docs/01 §3."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from ..auth import Principal, optional_principal, require_writer, session_readable
from ..config import settings
from ..db import get_session
from ..models import Artifact, IdempotencyRecord, Session, SessionStatus, Visibility
from ..schemas import (
    ArtifactOut,
    ArtifactRef,
    CreateSessionOut,
    GitInfo,
    SessionIn,
    SessionListOut,
    SessionOut,
    SessionPatch,
    SessionSummary,
    ShareOut,
)
from ..store import (
    body_hash,
    build_search_text,
    delete_session_and_cleanup_blobs,
    recompute_search_text,
    upsert_project,
    write_artifacts,
)

router = APIRouter(prefix="/v0", tags=["sessions"])


def _artifact_url(aid: str) -> str:
    return f"{settings.base_url}/v0/artifacts/{aid}"


def _session_url(sid: str) -> str:
    return f"{settings.base_url}/s/{sid}"


def _share_url(sid: str, token: str) -> str:
    return f"{settings.base_url}/s/{sid}?t={token}"


@router.post("/sessions", response_model=CreateSessionOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_writer)])
def create_session(
    payload: SessionIn,
    db: DBSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CreateSessionOut:
    bh = body_hash(payload)

    if idempotency_key:
        existing = db.get(IdempotencyRecord, idempotency_key)
        if existing:
            if existing.body_hash != bh:
                raise HTTPException(status.HTTP_409_CONFLICT, "idempotency_conflict")
            sess = db.get(Session, existing.session_id)
            arts = db.exec(
                select(Artifact).where(Artifact.session_id == sess.id, Artifact.version == sess.version)
            ).all()
            return CreateSessionOut(
                id=sess.id, version=sess.version, url=_session_url(sess.id),
                artifacts=[ArtifactRef(id=a.id, name=a.name, url=_artifact_url(a.id)) for a in arts],
            )

    git = payload.git or GitInfo()
    sess = Session(
        name=payload.name, description=payload.description, agent=payload.agent, model=payload.model,
        project_id=upsert_project(db, payload.project),
        git_repository=git.repository, git_branch=git.branch, git_commit=git.commit,
        tags=payload.tags, visibility=payload.visibility, favorite=payload.favorite, version=1,
    )
    db.add(sess)
    db.flush()  # assign sess.id

    arts, texts = write_artifacts(db, sess.id, version=1, payload=payload)
    sess.search_text = build_search_text(sess, texts)
    db.add(sess)

    if idempotency_key:
        db.add(IdempotencyRecord(key=idempotency_key, session_id=sess.id, body_hash=bh))

    db.commit()
    db.refresh(sess)
    return CreateSessionOut(
        id=sess.id, version=sess.version, url=_session_url(sess.id),
        artifacts=[ArtifactRef(id=a.id, name=a.name, url=_artifact_url(a.id)) for a in arts],
    )


@router.post("/sessions/{session_id}/versions", response_model=CreateSessionOut,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_writer)])
def new_version(
    session_id: str,
    payload: SessionIn,
    db: DBSession = Depends(get_session),
) -> CreateSessionOut:
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if sess.status == SessionStatus.finalized:
        raise HTTPException(status.HTTP_409_CONFLICT, "session finalized; immutable")

    new_ver = sess.version + 1
    # Mutable identity/metadata refresh on new snapshot.
    sess.name = payload.name or sess.name
    sess.description = payload.description
    sess.tags = payload.tags
    sess.version = new_ver
    git = payload.git or GitInfo()
    sess.git_repository, sess.git_branch, sess.git_commit = git.repository, git.branch, git.commit
    db.add(sess)

    arts, texts = write_artifacts(db, sess.id, version=new_ver, payload=payload)
    sess.search_text = build_search_text(sess, texts)
    db.add(sess)
    db.commit()
    return CreateSessionOut(
        id=sess.id, version=new_ver, url=_session_url(sess.id),
        artifacts=[ArtifactRef(id=a.id, name=a.name, url=_artifact_url(a.id)) for a in arts],
    )


def summarize(db: DBSession, s: Session, snippet: str | None = None) -> SessionSummary:
    """Build a SessionSummary for a session row (current-version artifact count)."""
    count = len(db.exec(
        select(Artifact).where(Artifact.session_id == s.id, Artifact.version == s.version)
    ).all())
    return SessionSummary(
        id=s.id, name=s.name, agent=s.agent, model=s.model, status=s.status.value,
        version=s.version, favorite=s.favorite, tags=s.tags,
        git=GitInfo(repository=s.git_repository, branch=s.git_branch, commit=s.git_commit),
        artifact_count=count, updated_at=s.updated_at.isoformat(), url=_session_url(s.id),
        snippet=snippet,
    )


def query_sessions(
    db: DBSession,
    principal: Principal | None,
    *,
    agent: str | None = None,
    project_id: str | None = None,
    favorite: bool | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SessionSummary], int]:
    """Shared session query (visibility + filters + FTS). Reused by list + collections."""
    stmt = select(Session)
    if principal is None:  # anonymous → public only
        stmt = stmt.where(Session.visibility == Visibility.public)
    if agent:
        stmt = stmt.where(Session.agent == agent)
    if project_id:
        stmt = stmt.where(Session.project_id == project_id)
    if favorite is not None:
        stmt = stmt.where(Session.favorite == favorite)

    is_pg = settings.database_url.startswith("postgresql")
    tsquery = None
    if q:
        if is_pg:
            tsquery = func.websearch_to_tsquery("english", q)
            tsvector = func.to_tsvector("english", col(Session.search_text))
            stmt = stmt.where(tsvector.op("@@")(tsquery)).order_by(func.ts_rank(tsvector, tsquery).desc())
        else:
            stmt = stmt.where(col(Session.search_text).ilike(f"%{q}%")).order_by(col(Session.updated_at).desc())
    else:
        stmt = stmt.order_by(col(Session.updated_at).desc())

    rows = db.exec(stmt).all()
    if tag:  # tag membership applied in Python (tags is a JSON array)
        rows = [s for s in rows if tag in (s.tags or [])]
    total = len(rows)
    page = rows[offset:offset + limit]

    out: list[SessionSummary] = []
    for s in page:
        snippet = None
        if q and is_pg:
            snippet = db.exec(
                # Sentinel delimiters (not HTML): client escapes then swaps for <mark> (no XSS).
                select(func.ts_headline(
                    "english", col(Session.search_text), tsquery,
                    "StartSel=@@HLS@@,StopSel=@@HLE@@,MaxFragments=1,MaxWords=18,MinWords=5",
                )).where(Session.id == s.id)
            ).first()
        out.append(summarize(db, s, snippet))
    return out, total


@router.get("/sessions", response_model=SessionListOut)
def list_sessions(
    db: DBSession = Depends(get_session),
    principal: Principal | None = Depends(optional_principal),
    agent: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    favorite: bool | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None, description="full-text search over metadata + artifact text"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> SessionListOut:
    summaries, total = query_sessions(
        db, principal, agent=agent, project_id=project_id, favorite=favorite,
        tag=tag, q=q, limit=limit, offset=offset,
    )
    return SessionListOut(sessions=summaries, total=total)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session_detail(
    session_id: str,
    version: int | None = Query(default=None),
    t: str | None = Query(default=None, description="capability link token"),
    db: DBSession = Depends(get_session),
    principal: Principal | None = Depends(optional_principal),
) -> SessionOut:
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if not session_readable(sess, principal, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    req_ver = version or sess.version
    arts = db.exec(
        select(Artifact).where(Artifact.session_id == sess.id, Artifact.version == req_ver)
    ).all()
    # Only an authenticated owner sees the secret link; never exposed to anon readers.
    share_url = _share_url(sess.id, sess.share_token) if (principal and sess.share_token) else None
    return SessionOut(
        id=sess.id, name=sess.name, description=sess.description, status=sess.status.value,
        agent=sess.agent, model=sess.model, project_id=sess.project_id,
        git=GitInfo(repository=sess.git_repository, branch=sess.git_branch, commit=sess.git_commit),
        tags=sess.tags, favorite=sess.favorite, visibility=sess.visibility.value,
        version=sess.version, requested_version=req_ver,
        created_at=sess.created_at.isoformat(), updated_at=sess.updated_at.isoformat(),
        share_url=share_url,
        artifacts=[
            ArtifactOut(id=a.id, name=a.name, type=a.type, size_bytes=a.size_bytes,
                        allow_scripts=a.allow_scripts, url=_artifact_url(a.id))
            for a in arts
        ],
    )


@router.post("/sessions/{session_id}/share", response_model=ShareOut,
             dependencies=[Depends(require_writer)])
def create_share_link(
    session_id: str,
    rotate: bool = Query(default=False, description="mint a fresh token, invalidating the old link"),
    db: DBSession = Depends(get_session),
) -> ShareOut:
    """Mint (or return existing) capability link for anon viewers. `rotate=1` revokes the old."""
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if sess.share_token is None or rotate:
        sess.share_token = secrets.token_urlsafe(32)
        db.add(sess)
        db.commit()
        db.refresh(sess)
    return ShareOut(url=_share_url(sess.id, sess.share_token))


@router.delete("/sessions/{session_id}/share", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_writer)])
def revoke_share_link(
    session_id: str,
    db: DBSession = Depends(get_session),
) -> Response:
    """Revoke the capability link; existing URLs stop working immediately."""
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    sess.share_token = None
    db.add(sess)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/sessions/{session_id}", response_model=SessionSummary,
              dependencies=[Depends(require_writer)])
def patch_session(
    session_id: str,
    patch: SessionPatch,
    db: DBSession = Depends(get_session),
) -> SessionSummary:
    """Partial in-place edit (favorite, name, tags, status…). No new version."""
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(sess, field, value)
    sess.updated_at = datetime.now(timezone.utc)
    # Metadata (name/desc/tags) feeds search — rebuild the search doc.
    if data.keys() & {"name", "description", "tags"}:
        recompute_search_text(db, sess)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    count = len(db.exec(
        select(Artifact).where(Artifact.session_id == sess.id, Artifact.version == sess.version)
    ).all())
    return SessionSummary(
        id=sess.id, name=sess.name, agent=sess.agent, model=sess.model, status=sess.status.value,
        version=sess.version, favorite=sess.favorite, tags=sess.tags,
        git=GitInfo(repository=sess.git_repository, branch=sess.git_branch, commit=sess.git_commit),
        artifact_count=count, updated_at=sess.updated_at.isoformat(), url=_session_url(sess.id),
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_writer)])
def delete_session(
    session_id: str,
    db: DBSession = Depends(get_session),
) -> Response:
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    delete_session_and_cleanup_blobs(db, session_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
