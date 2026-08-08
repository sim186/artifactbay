"""Link previews (Open Graph / Twitter cards) for shared URLs.

A share link used to unfurl as a bare URL in Slack, iMessage or a PR comment,
because `/s/<id>` is a client-rendered SPA route: a crawler fetches it, gets an
empty `<div id="root">`, and has nothing to show. For a feature whose entire job
is handing someone a link, that unfurl *is* the first impression.

Crawlers get this server-rendered stub instead (nginx routes them here by
user-agent); humans keep getting the SPA. The stub carries the card metadata and
a link onward, so a human who lands here anyway isn't stranded.

Readability is enforced exactly as everywhere else: an unreadable session yields
a generic card that reveals nothing — no name, no description, no confirmation
that the id exists.
"""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from ..auth import Principal, artifact_readable, optional_principal, session_owned_by, session_readable
from ..db import get_session
from ..models import Artifact, Session
from ..urls import base_url

router = APIRouter(prefix="/v0/preview", tags=["preview"])

_SITE = "ArtifactBay"


def _page(title: str, description: str, canonical: str, *, kind: str = "website") -> HTMLResponse:
    t, d, c = escape(title), escape(description), escape(canonical, quote=True)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{t} · {_SITE}</title>
<meta name="description" content="{d}">
<meta property="og:site_name" content="{_SITE}">
<meta property="og:type" content="{kind}">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{c}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<link rel="canonical" href="{c}">
<meta name="robots" content="noindex">
</head>
<body>
<h1>{t}</h1>
<p>{d}</p>
<p><a href="{c}">Open in {_SITE}</a></p>
</body>
</html>
"""
    return HTMLResponse(
        content=html,
        headers={
            "X-Content-Type-Options": "nosniff",
            # Never let a capability token ride along to wherever the card links.
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "public, max-age=300",
        },
    )


def _generic(request: Request, path: str) -> HTMLResponse:
    """Card for anything the caller may not read. Deliberately says nothing."""
    return _page(_SITE, "A session artifact repository for AI coding agents.",
                 f"{base_url(request)}{path}")


@router.get("/s/{session_id}", response_class=HTMLResponse)
def preview_session(session_id: str, request: Request,
                    t: str | None = Query(default=None),
                    db: DBSession = Depends(get_session),
                    principal: Principal | None = Depends(optional_principal)) -> HTMLResponse:
    canonical = f"{base_url(request)}/s/{session_id}" + (f"?t={t}" if t else "")
    sess = db.get(Session, session_id)
    if sess is None or not session_readable(sess, principal, t):
        return _generic(request, f"/s/{session_id}")

    stmt = select(func.count()).select_from(Artifact).where(
        Artifact.session_id == sess.id, Artifact.version == sess.version
    )
    if not session_owned_by(sess, principal):
        stmt = stmt.where(col(Artifact.owner_only) == False)  # noqa: E712
    count = db.exec(stmt).one()

    bits = [f"{count} artifact{'s' if count != 1 else ''}", sess.agent]
    if sess.model:
        bits.append(sess.model)
    bits.append(f"v{sess.version}")
    desc = sess.description or " · ".join(bits)
    return _page(sess.name, desc, canonical, kind="article")


@router.get("/a/{artifact_id}", response_class=HTMLResponse)
def preview_artifact(artifact_id: str, request: Request,
                     t: str | None = Query(default=None),
                     db: DBSession = Depends(get_session),
                     principal: Principal | None = Depends(optional_principal)) -> HTMLResponse:
    canonical = f"{base_url(request)}/a/{artifact_id}" + (f"?t={t}" if t else "")
    art = db.get(Artifact, artifact_id)
    if art is None:
        return _generic(request, f"/a/{artifact_id}")
    sess = db.get(Session, art.session_id)
    if not artifact_readable(art, sess, principal, t):
        return _generic(request, f"/a/{artifact_id}")

    kb = max(1, round(art.size_bytes / 1024))
    desc = f"{art.type.value} · {kb} KB" + (f" · from “{sess.name}”" if sess else "")
    return _page(art.name, desc, canonical, kind="article")
