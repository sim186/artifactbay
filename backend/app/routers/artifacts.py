"""Artifact retrieval: raw bytes + sandboxed HTML render. See docs/01 §3.4-3.5, §4."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session as DBSession

from ..auth import Principal, optional_principal, session_readable
from ..config import settings
from ..db import get_session
from ..models import Artifact, ArtifactType, Blob, Session
from ..schemas import ArtifactDetailOut

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


def _load(db: DBSession, artifact_id: str, principal: Principal | None,
          token: str | None) -> tuple[Artifact, bytes]:
    art = db.get(Artifact, artifact_id)
    if art is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    sess = db.get(Session, art.session_id)
    if sess and not session_readable(sess, principal, token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    blob = db.get(Blob, art.content_hash)
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blob_missing")
    return art, blob.data


@router.get("/{artifact_id}/meta", response_model=ArtifactDetailOut)
def get_artifact_meta(artifact_id: str, db: DBSession = Depends(get_session),
                      t: str | None = Query(default=None),
                      principal: Principal | None = Depends(optional_principal)) -> ArtifactDetailOut:
    art = db.get(Artifact, artifact_id)
    if art is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    sess = db.get(Session, art.session_id)
    if sess and not session_readable(sess, principal, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return ArtifactDetailOut(
        id=art.id, name=art.name, type=art.type, size_bytes=art.size_bytes,
        allow_scripts=art.allow_scripts, url=f"{settings.base_url}/v0/artifacts/{art.id}",
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
def view_artifact(artifact_id: str, db: DBSession = Depends(get_session),
                  t: str | None = Query(default=None),
                  principal: Principal | None = Depends(optional_principal)) -> Response:
    """Sandboxed render target for the iframe. HTML only; else redirect to raw."""
    art, data = _load(db, artifact_id, principal, t)
    if art.type != ArtifactType.html:
        suffix = f"?t={t}" if t else ""
        return RedirectResponse(url=f"{settings.base_url}/v0/artifacts/{artifact_id}{suffix}")

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
