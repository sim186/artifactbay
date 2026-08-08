"""Session endpoints: create, version, get, list, patch. See docs/01 §3."""
from __future__ import annotations

import io
import json
import secrets
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, or_
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from .. import standalone
from ..auth import (
    Principal,
    optional_principal,
    require_writer,
    session_owned_by,
    session_readable,
)
from ..config import settings
from ..db import get_session
from ..models import Artifact, Blob, IdempotencyRecord, Role, Session, SessionStatus, Visibility
from ..schemas import (
    ArtifactOut,
    ArtifactRef,
    ArtifactsIn,
    CreateSessionOut,
    GitInfo,
    SessionIn,
    SessionListOut,
    SessionOut,
    SessionPatch,
    SessionSummary,
    ShareOut,
    VersionListOut,
    VersionOut,
)
from ..store import (
    add_artifacts,
    body_hash,
    build_search_text,
    delete_session_and_cleanup_blobs,
    recompute_search_text,
    set_tags,
    upsert_project,
    write_artifacts,
)
from ..urls import artifact_share_url, artifact_url, session_url, share_url

router = APIRouter(prefix="/v0", tags=["sessions"])


def _owned_or_404(db: DBSession, session_id: str, principal: Principal) -> Session:
    """Fetch a session the principal may MUTATE. 404 (not 403) so a probing
    caller can't map which session ids exist."""
    sess = db.get(Session, session_id)
    if sess is None or not session_owned_by(sess, principal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return sess


def _artifact_out(request: Request, a: Artifact, is_owner: bool) -> ArtifactOut:
    return ArtifactOut(
        id=a.id, name=a.name, type=a.type, size_bytes=a.size_bytes,
        allow_scripts=a.allow_scripts, url=artifact_url(request, a.id),
        owner_only=a.owner_only,
        # The secret is only ever handed to whoever owns the thing.
        share_url=artifact_share_url(request, a.id, a.share_token)
        if (is_owner and a.share_token) else None,
    )


def _visible_artifacts(db: DBSession, sess: Session, version: int,
                       principal: Principal | None) -> list[Artifact]:
    """Artifacts of a version that this reader may see.

    Owner-only rows (conversation slices) drop out for everyone but the owner, so
    a capability link shares the work without shipping the transcript behind it.
    """
    stmt = select(Artifact).where(Artifact.session_id == sess.id, Artifact.version == version)
    if not session_owned_by(sess, principal):
        stmt = stmt.where(col(Artifact.owner_only) == False)  # noqa: E712 (SQL, not Python truthiness)
    return list(db.exec(stmt.order_by(col(Artifact.created_at), col(Artifact.id))).all())


@router.post("/sessions", response_model=CreateSessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionIn,
    request: Request,
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
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
                id=sess.id, version=sess.version, url=session_url(request, sess.id),
                artifacts=[ArtifactRef(id=a.id, name=a.name, url=artifact_url(request, a.id))
                           for a in arts],
            )

    git = payload.git or GitInfo()
    sess = Session(
        name=payload.name, description=payload.description, agent=payload.agent, model=payload.model,
        project_id=upsert_project(db, payload.project),
        git_repository=git.repository, git_branch=git.branch, git_commit=git.commit,
        visibility=payload.visibility, favorite=payload.favorite, version=1,
        owner_id=principal.user_id,
    )
    set_tags(sess, payload.tags)
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
        id=sess.id, version=sess.version, url=session_url(request, sess.id),
        artifacts=[ArtifactRef(id=a.id, name=a.name, url=artifact_url(request, a.id)) for a in arts],
    )


@router.post("/sessions/{session_id}/versions", response_model=CreateSessionOut,
             status_code=status.HTTP_201_CREATED)
def new_version(
    session_id: str,
    payload: SessionIn,
    request: Request,
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
) -> CreateSessionOut:
    sess = _owned_or_404(db, session_id, principal)
    if sess.status == SessionStatus.finalized:
        raise HTTPException(status.HTTP_409_CONFLICT, "session finalized; immutable")

    new_ver = sess.version + 1
    # Mutable identity/metadata refresh on new snapshot.
    sess.name = payload.name or sess.name
    sess.description = payload.description
    set_tags(sess, payload.tags)
    sess.version = new_ver
    sess.updated_at = datetime.now(timezone.utc)
    git = payload.git or GitInfo()
    sess.git_repository, sess.git_branch, sess.git_commit = git.repository, git.branch, git.commit
    db.add(sess)

    arts, texts = write_artifacts(db, sess.id, version=new_ver, payload=payload)
    sess.search_text = build_search_text(sess, texts)
    db.add(sess)
    db.commit()
    return CreateSessionOut(
        id=sess.id, version=new_ver, url=session_url(request, sess.id),
        artifacts=[ArtifactRef(id=a.id, name=a.name, url=artifact_url(request, a.id)) for a in arts],
    )


@router.post("/sessions/{session_id}/artifacts", response_model=CreateSessionOut,
             status_code=status.HTTP_201_CREATED)
def append_artifacts(
    session_id: str,
    payload: ArtifactsIn,
    request: Request,
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
) -> CreateSessionOut:
    """Add artifacts to the CURRENT version in place — no new snapshot.

    The incremental write path: attaching one more file (a transcript slice, a
    late screenshot) no longer means re-uploading the whole session just to bump
    the version number.
    """
    sess = _owned_or_404(db, session_id, principal)
    if sess.status == SessionStatus.finalized:
        raise HTTPException(status.HTTP_409_CONFLICT, "session finalized; immutable")
    if not payload.artifacts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no artifacts")

    rows = add_artifacts(db, sess, payload.artifacts)
    db.flush()
    recompute_search_text(db, sess)
    sess.updated_at = datetime.now(timezone.utc)
    db.add(sess)
    db.commit()
    return CreateSessionOut(
        id=sess.id, version=sess.version, url=session_url(request, sess.id),
        artifacts=[ArtifactRef(id=a.id, name=a.name, url=artifact_url(request, a.id)) for a in rows],
    )


def _artifact_counts(db: DBSession, rows: list[Session],
                     principal: Principal | None) -> dict[str, int]:
    """Current-version artifact count for a page of sessions, in ONE query.

    Was a per-session round trip inside summarize(); at 50 rows that was 50
    queries per list call.
    """
    if not rows:
        return {}
    pairs = [and_(Artifact.session_id == s.id, Artifact.version == s.version) for s in rows]
    stmt = select(Artifact.session_id, func.count()).where(or_(*pairs))
    if principal is None:
        stmt = stmt.where(col(Artifact.owner_only) == False)  # noqa: E712
    stmt = stmt.group_by(col(Artifact.session_id))
    return {sid: n for sid, n in db.exec(stmt).all()}


def summarize(db: DBSession, s: Session, request: Request | None = None,
              snippet: str | None = None, count: int | None = None) -> SessionSummary:
    """Build a SessionSummary for a session row."""
    if count is None:
        count = len(db.exec(
            select(Artifact).where(Artifact.session_id == s.id, Artifact.version == s.version)
        ).all())
    return SessionSummary(
        id=s.id, name=s.name, agent=s.agent, model=s.model, status=s.status.value,
        version=s.version, favorite=s.favorite, tags=s.tags,
        git=GitInfo(repository=s.git_repository, branch=s.git_branch, commit=s.git_commit),
        artifact_count=count, updated_at=s.updated_at.isoformat(),
        url=session_url(request, s.id), snippet=snippet,
    )


def _visibility_filter(stmt, principal: Principal | None):
    """Restrict a session query to what this principal may list.

    Anonymous sees public only. A normal user sees their own, plus pre-ownership
    rows, plus anything public. Admins see everything. Capability links are
    deliberately absent — a shared session stays unlisted, reachable only by URL.
    """
    if principal is None:
        return stmt.where(Session.visibility == Visibility.public)
    if principal.role == Role.admin:
        return stmt
    return stmt.where(or_(
        col(Session.owner_id) == principal.user_id,
        col(Session.owner_id).is_(None),
        Session.visibility == Visibility.public,
    ))


def query_sessions(
    db: DBSession,
    principal: Principal | None,
    request: Request | None = None,
    *,
    agent: str | None = None,
    project_id: str | None = None,
    favorite: bool | None = None,
    tag: str | None = None,
    q: str | None = None,
    exclude_ids: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SessionSummary], int]:
    """Shared session query (visibility + filters + FTS). Reused by list + collections.

    Filtering, ordering, counting and paging all happen in SQL. This used to load
    every matching row into Python and slice the list, which meant a full table
    read on every dashboard render.
    """
    stmt = _visibility_filter(select(Session), principal)
    if agent:
        stmt = stmt.where(Session.agent == agent)
    if project_id:
        stmt = stmt.where(Session.project_id == project_id)
    if favorite is not None:
        stmt = stmt.where(Session.favorite == favorite)
    if tag:
        # Exact tag match against the delimited mirror column (see store.tags_to_text).
        stmt = stmt.where(col(Session.tags_text).like(f"%|{tag}|%"))
    if exclude_ids:
        stmt = stmt.where(col(Session.id).notin_(exclude_ids))

    is_pg = settings.database_url.startswith("postgresql")
    headline = None
    if q:
        if is_pg:
            tsquery = func.websearch_to_tsquery("english", q)
            tsvector = func.to_tsvector("english", col(Session.search_text))
            stmt = stmt.where(tsvector.op("@@")(tsquery))
            stmt = stmt.order_by(func.ts_rank(tsvector, tsquery).desc(), col(Session.updated_at).desc())
            # Sentinel delimiters (not HTML): client escapes then swaps for <mark> (no XSS).
            # Selected alongside the row instead of one extra query per result.
            headline = func.ts_headline(
                "english", col(Session.search_text), tsquery,
                "StartSel=@@HLS@@,StopSel=@@HLE@@,MaxFragments=1,MaxWords=18,MinWords=5",
            )
        else:
            stmt = stmt.where(col(Session.search_text).ilike(f"%{q}%"))
            stmt = stmt.order_by(col(Session.updated_at).desc())
    else:
        stmt = stmt.order_by(col(Session.updated_at).desc())

    total = db.exec(select(func.count()).select_from(stmt.order_by(None).subquery())).one()

    if headline is None:
        rows = list(db.exec(stmt.limit(limit).offset(offset)).all())
        snippets: list[str | None] = [None] * len(rows)
    else:
        # `db.exec()` unwraps single-entity selects to scalars, which would drop the
        # headline column — go through SQLAlchemy's execute() to keep the row tuples.
        result = db.execute(stmt.add_columns(headline).limit(limit).offset(offset)).all()
        rows = [r[0] for r in result]
        snippets = [r[1] for r in result]

    counts = _artifact_counts(db, rows, principal)
    out = [
        summarize(db, s, request, snippet=snip, count=counts.get(s.id, 0))
        for s, snip in zip(rows, snippets)
    ]
    return out, total


@router.get("/sessions", response_model=SessionListOut)
def list_sessions(
    request: Request,
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
        db, principal, request, agent=agent, project_id=project_id, favorite=favorite,
        tag=tag, q=q, limit=limit, offset=offset,
    )
    return SessionListOut(sessions=summaries, total=total)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session_detail(
    session_id: str,
    request: Request,
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
    is_owner = session_owned_by(sess, principal)
    req_ver = version or sess.version
    arts = _visible_artifacts(db, sess, req_ver, principal)
    # Only an authenticated owner sees the secret link; never exposed to anon readers.
    link = share_url(request, sess.id, sess.share_token) if (is_owner and sess.share_token) else None
    return SessionOut(
        id=sess.id, name=sess.name, description=sess.description, status=sess.status.value,
        agent=sess.agent, model=sess.model, project_id=sess.project_id,
        git=GitInfo(repository=sess.git_repository, branch=sess.git_branch, commit=sess.git_commit),
        tags=sess.tags, favorite=sess.favorite, visibility=sess.visibility.value,
        version=sess.version, requested_version=req_ver,
        created_at=sess.created_at.isoformat(), updated_at=sess.updated_at.isoformat(),
        share_url=link, is_owner=is_owner,
        artifacts=[_artifact_out(request, a, is_owner) for a in arts],
    )


@router.get("/sessions/{session_id}/versions", response_model=VersionListOut)
def list_versions(
    session_id: str,
    t: str | None = Query(default=None),
    db: DBSession = Depends(get_session),
    principal: Principal | None = Depends(optional_principal),
) -> VersionListOut:
    """Real version history, with timestamps and sizes.

    The UI used to synthesise this from the version *number* alone
    (`Array.from({length: version})`), so it could show "v3" but never when v3
    was taken or what was in it.
    """
    sess = db.get(Session, session_id)
    if sess is None or not session_readable(sess, principal, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")

    stmt = select(
        Artifact.version,
        func.count(),
        func.coalesce(func.sum(col(Artifact.size_bytes)), 0),
        func.min(col(Artifact.created_at)),
    ).where(Artifact.session_id == sess.id)
    if not session_owned_by(sess, principal):
        stmt = stmt.where(col(Artifact.owner_only) == False)  # noqa: E712
    rows = db.exec(stmt.group_by(col(Artifact.version)).order_by(col(Artifact.version))).all()

    return VersionListOut(
        versions=[
            VersionOut(version=v, artifact_count=n, total_bytes=int(size or 0),
                       created_at=(created or sess.created_at).isoformat())
            for v, n, size, created in rows
        ],
        current=sess.version,
    )


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    version: int | None = Query(default=None),
    t: str | None = Query(default=None),
    db: DBSession = Depends(get_session),
    principal: Principal | None = Depends(optional_principal),
) -> Response:
    """Download a version as a zip (artifacts + manifest.json).

    The way your data gets back out. Without it, everything pushed here is only
    retrievable one file at a time through the UI.
    """
    sess = db.get(Session, session_id)
    if sess is None or not session_readable(sess, principal, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    req_ver = version or sess.version
    arts = _visible_artifacts(db, sess, req_ver, principal)

    buf = io.BytesIO()
    manifest = {
        "id": sess.id, "name": sess.name, "description": sess.description,
        "agent": sess.agent, "model": sess.model, "version": req_ver,
        "tags": sess.tags,
        "git": {"repository": sess.git_repository, "branch": sess.git_branch,
                "commit": sess.git_commit},
        "created_at": sess.created_at.isoformat(), "updated_at": sess.updated_at.isoformat(),
        "artifacts": [],
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen: dict[str, int] = {}
        for a in arts:
            blob = db.get(Blob, a.content_hash)
            if blob is None:
                continue
            # Two artifacts in one version may share a filename; keep both.
            name = a.name
            if name in seen:
                seen[name] += 1
                stem, _, ext = name.rpartition(".")
                name = f"{stem}-{seen[name]}.{ext}" if stem else f"{name}-{seen[name]}"
            else:
                seen[name] = 0
            zf.writestr(f"artifacts/{name}", blob.data)
            manifest["artifacts"].append({
                "name": name, "type": a.type.value, "size_bytes": a.size_bytes,
                "sha256": a.content_hash,
            })
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    filename = f"{sess.id}-v{req_ver}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/sessions/{session_id}/standalone")
def standalone_session(
    session_id: str,
    version: int | None = Query(default=None),
    t: str | None = Query(default=None),
    download: bool = Query(default=True),
    db: DBSession = Depends(get_session),
    principal: Principal | None = Depends(optional_principal),
) -> Response:
    """One self-contained HTML file with every artifact inlined.

    For presenting and for handing work to people who shouldn't need an account,
    a URL, or a network. A capability link always points back at a running
    instance; this doesn't.
    """
    sess = db.get(Session, session_id)
    if sess is None or not session_readable(sess, principal, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    req_ver = version or sess.version
    arts = _visible_artifacts(db, sess, req_ver, principal)

    payload = []
    for a in arts:
        blob = db.get(Blob, a.content_hash)
        if blob is not None:
            payload.append({"name": a.name, "type": a.type.value, "data": blob.data,
                            "allow_scripts": a.allow_scripts})

    bits = [sess.agent, f"v{req_ver}", sess.updated_at.strftime("%Y-%m-%d")]
    if sess.model:
        bits.insert(1, sess.model)
    html = standalone.build(
        title=sess.name,
        subtitle=" · ".join(bits),
        artifacts=payload,
        footer=f"{sess.name} — standalone export, no network required. ← → to switch artifacts.",
    )
    headers = {"Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}
    if download:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in sess.name)[:60] or "session"
        headers["Content-Disposition"] = f'attachment; filename="{safe}-v{req_ver}.html"'
    return Response(content=html, media_type="text/html; charset=utf-8", headers=headers)


@router.post("/sessions/{session_id}/share", response_model=ShareOut)
def create_share_link(
    session_id: str,
    request: Request,
    rotate: bool = Query(default=False, description="mint a fresh token, invalidating the old link"),
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
) -> ShareOut:
    """Mint (or return existing) capability link for anon viewers. `rotate=1` revokes the old."""
    sess = _owned_or_404(db, session_id, principal)
    if sess.share_token is None or rotate:
        sess.share_token = secrets.token_urlsafe(32)
        db.add(sess)
        db.commit()
        db.refresh(sess)
    return ShareOut(url=share_url(request, sess.id, sess.share_token))


@router.delete("/sessions/{session_id}/share", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share_link(
    session_id: str,
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
) -> Response:
    """Revoke the capability link; existing URLs stop working immediately."""
    sess = _owned_or_404(db, session_id, principal)
    sess.share_token = None
    db.add(sess)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def patch_session(
    session_id: str,
    patch: SessionPatch,
    request: Request,
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
) -> SessionSummary:
    """Partial in-place edit (favorite, name, tags, status…). No new version."""
    sess = _owned_or_404(db, session_id, principal)
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "tags":
            set_tags(sess, value)
        else:
            setattr(sess, field, value)
    sess.updated_at = datetime.now(timezone.utc)
    # Metadata (name/desc/tags) feeds search — rebuild the search doc.
    if data.keys() & {"name", "description", "tags"}:
        recompute_search_text(db, sess)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return summarize(db, sess, request)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    db: DBSession = Depends(get_session),
    principal: Principal = Depends(require_writer),
) -> Response:
    sess = _owned_or_404(db, session_id, principal)
    delete_session_and_cleanup_blobs(db, sess.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
