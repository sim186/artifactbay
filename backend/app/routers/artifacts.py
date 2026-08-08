"""Artifact retrieval: raw bytes + sandboxed HTML render. See docs/01 §3.4-3.5, §4."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session as DBSession

from ..auth import (
    Principal,
    artifact_readable,
    optional_principal,
    require_writer,
    session_owned_by,
)
from ..db import get_session
from ..models import Artifact, ArtifactType, Blob, Session
from ..schemas import ArtifactDetailOut, ShareOut
from ..store import delete_artifact, recompute_search_text
from ..urls import artifact_share_url, artifact_url

router = APIRouter(prefix="/v0/artifacts", tags=["artifacts"])

_MIME = {
    ArtifactType.html: "text/html; charset=utf-8",
    ArtifactType.markdown: "text/markdown; charset=utf-8",
    ArtifactType.json: "application/json",
    ArtifactType.svg: "image/svg+xml",
    ArtifactType.png: "image/png",
    ArtifactType.pdf: "application/pdf",
    ArtifactType.zip: "application/zip",
    ArtifactType.text: "text/plain; charset=utf-8",
    ArtifactType.conversation: "application/json",
}


def _readable_or_404(db: DBSession, artifact_id: str, principal: Principal | None,
                     token: str | None) -> tuple[Artifact, Session | None]:
    art = db.get(Artifact, artifact_id)
    if art is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    sess = db.get(Session, art.session_id)
    if not artifact_readable(art, sess, principal, token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return art, sess


def _owned_or_404(db: DBSession, artifact_id: str, principal: Principal) -> tuple[Artifact, Session]:
    art = db.get(Artifact, artifact_id)
    if art is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    sess = db.get(Session, art.session_id)
    if sess is None or not session_owned_by(sess, principal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return art, sess


def _load(db: DBSession, artifact_id: str, principal: Principal | None,
          token: str | None) -> tuple[Artifact, bytes]:
    art, _ = _readable_or_404(db, artifact_id, principal, token)
    blob = db.get(Blob, art.content_hash)
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blob_missing")
    return art, blob.data


@router.get("/{artifact_id}/meta", response_model=ArtifactDetailOut)
def get_artifact_meta(artifact_id: str, request: Request, db: DBSession = Depends(get_session),
                      t: str | None = Query(default=None),
                      principal: Principal | None = Depends(optional_principal)) -> ArtifactDetailOut:
    art, sess = _readable_or_404(db, artifact_id, principal, t)
    is_owner = sess is not None and session_owned_by(sess, principal)
    return ArtifactDetailOut(
        id=art.id, name=art.name, type=art.type, size_bytes=art.size_bytes,
        allow_scripts=art.allow_scripts, url=artifact_url(request, art.id),
        owner_only=art.owner_only,
        share_url=artifact_share_url(request, art.id, art.share_token)
        if (is_owner and art.share_token) else None,
        content_hash=art.content_hash, session_id=art.session_id,
        session_name=sess.name if sess else "", version=art.version,
    )


@router.get("/{artifact_id}")
def get_artifact_raw(artifact_id: str, db: DBSession = Depends(get_session),
                     t: str | None = Query(default=None),
                     principal: Principal | None = Depends(optional_principal)) -> Response:
    """Original bytes. Never executes — this route just serves content."""
    art, data = _load(db, artifact_id, principal, t)
    return Response(
        content=data,
        media_type=_MIME.get(art.type, "application/octet-stream"),
        headers={
            "Content-Disposition": f'inline; filename="{art.name}"',
            # Defense-in-depth even on the raw route.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            # Keep the capability token out of outbound referrers from rendered content.
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/{artifact_id}/view")
def view_artifact(artifact_id: str, request: Request, db: DBSession = Depends(get_session),
                  t: str | None = Query(default=None),
                  principal: Principal | None = Depends(optional_principal)) -> Response:
    """Sandboxed render target for the iframe. HTML only; else redirect to raw."""
    art, data = _load(db, artifact_id, principal, t)
    if art.type != ArtifactType.html:
        suffix = f"?t={t}" if t else ""
        return RedirectResponse(url=f"{artifact_url(request, artifact_id)}{suffix}")

    script_src = "'unsafe-inline'" if art.allow_scripts else "'none'"
    csp = (
        "default-src 'none'; "
        "img-src data: blob: https:; "
        "style-src 'unsafe-inline'; "
        "font-src data:; "
        f"script-src {script_src}"
    )
    return Response(
        content=data,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": csp,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            # Keep the capability token out of outbound referrers from rendered content.
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/{artifact_id}/share", response_model=ShareOut)
def create_artifact_share(artifact_id: str, request: Request,
                          rotate: bool = Query(default=False),
                          db: DBSession = Depends(get_session),
                          principal: Principal = Depends(require_writer)) -> ShareOut:
    """Capability link for ONE artifact.

    The common ask is "look at this dashboard", not "here is my whole session".
    Session-level sharing forced the second; this gives the first, and it works
    on owner-only artifacts too — sharing one deliberately is a different act
    from a link leaking everything.
    """
    art, _ = _owned_or_404(db, artifact_id, principal)
    if art.share_token is None or rotate:
        art.share_token = secrets.token_urlsafe(32)
        db.add(art)
        db.commit()
        db.refresh(art)
    return ShareOut(url=artifact_share_url(request, art.id, art.share_token))


@router.delete("/{artifact_id}/share", status_code=status.HTTP_204_NO_CONTENT)
def revoke_artifact_share(artifact_id: str, db: DBSession = Depends(get_session),
                          principal: Principal = Depends(require_writer)) -> Response:
    art, _ = _owned_or_404(db, artifact_id, principal)
    art.share_token = None
    db.add(art)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_artifact(artifact_id: str, db: DBSession = Depends(get_session),
                    principal: Principal = Depends(require_writer)) -> Response:
    """Delete one artifact (and release its blob), leaving the session intact."""
    art, sess = _owned_or_404(db, artifact_id, principal)
    in_current_version = art.version == sess.version
    delete_artifact(db, art)
    db.flush()
    if in_current_version:
        recompute_search_text(db, sess)
        db.add(sess)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
