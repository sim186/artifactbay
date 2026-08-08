"""Outbound URL construction.

Every link the API hands out (session URLs, artifact URLs, share links) used to be
built from one global `settings.base_url`. That breaks the moment the same instance
is reached over more than one hostname — localhost during setup, a LAN IP from a
laptop, a public domain through a reverse proxy — because the minted link points at
whatever the operator configured, not at the host the caller actually used.

So: when the request arrived through a proxy (`X-Forwarded-Host` is set, as the
bundled nginx does), derive the origin from that request. Otherwise fall back to the
configured value.

The fallback matters. `base_url` is the origin of the *web app*, and in the split dev
setup (Vite on :5173, API on :8000) those differ — a bare `Host` header there is the
API, and building `/s/<id>` links from it would 404 with a JSON body. A forwarded host
is unambiguous: something is proxying both halves onto one origin.
"""
from __future__ import annotations

from fastapi import Request

from .config import settings


def _first(value: str) -> str:
    """`X-Forwarded-*` may be a comma-separated chain; the client-facing hop is first."""
    return value.split(",")[0].strip()


def base_url(request: Request | None = None) -> str:
    """Public origin to build links from, for this request."""
    fallback = settings.base_url.rstrip("/")
    if request is None or not settings.trust_forwarded_host:
        return fallback

    forwarded_host = request.headers.get("x-forwarded-host")
    if not forwarded_host:
        return fallback

    host = _first(forwarded_host)
    if not host:
        return fallback
    proto = _first(request.headers.get("x-forwarded-proto") or request.url.scheme or "http")
    return f"{proto}://{host}"


def session_url(request: Request | None, session_id: str) -> str:
    return f"{base_url(request)}/s/{session_id}"


def artifact_url(request: Request | None, artifact_id: str) -> str:
    return f"{base_url(request)}/v0/artifacts/{artifact_id}"


def share_url(request: Request | None, session_id: str, token: str) -> str:
    return f"{base_url(request)}/s/{session_id}?t={token}"


def artifact_share_url(request: Request | None, artifact_id: str, token: str) -> str:
    return f"{base_url(request)}/a/{artifact_id}?t={token}"
