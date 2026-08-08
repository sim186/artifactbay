"""Auth: password hashing, JWT cookies, API-key hashing, principal dependencies.

Two principals can authenticate a request:
- a **user** via JWT in an httpOnly cookie (the web UI), or
- an **API key** via `Authorization: Bearer ab_...` (agents).

Write endpoints accept either. Reads are gated by visibility (public = anon ok).
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session as DBSession
from sqlmodel import select

from .config import settings
from .db import get_session
from .models import ApiKey, Role, Scope, Session, User, Visibility


# ── password + token primitives ──────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_token() -> str:
    return "ab_" + secrets.token_urlsafe(32)


def make_jwt(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


# ── principal ────────────────────────────────────────────────────────────────
@dataclass
class Principal:
    kind: str  # "user" | "apikey"
    id: str  # user id, or the API-key row id
    role: Role | None = None
    scope: Scope | None = None
    username: str | None = None
    # The human behind the request. For a cookie session that's the user; for an
    # API key it's the user the key was minted for. Ownership is always checked
    # against this, never against `id` — otherwise every key would be its own
    # tenant and could never read back what its owner pushed from the UI.
    user_id: str | None = None

    @property
    def can_write(self) -> bool:
        if self.kind == "user":
            return True  # both roles can write; admin-only checks are explicit
        return self.scope == Scope.write


def _user_from_cookie(request: Request, db: DBSession) -> Principal | None:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = db.get(User, payload.get("sub"))
    if user is None:
        return None
    return Principal(kind="user", id=user.id, role=user.role, username=user.username,
                     user_id=user.id)


def _principal_from_apikey(request: Request, db: DBSession) -> Principal | None:
    authz = request.headers.get("authorization")
    if not authz or not authz.startswith("Bearer "):
        return None
    token = authz.removeprefix("Bearer ").strip()
    row = db.exec(select(ApiKey).where(ApiKey.key_hash == hash_token(token))).first()
    if row is None or row.revoked:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    # An API key inherits the role of the user it belongs to, so an admin's key
    # can administer and a member's key cannot.
    owner = db.get(User, row.user_id) if row.user_id else None
    return Principal(kind="apikey", id=row.id, scope=row.scope,
                     role=owner.role if owner else None, user_id=row.user_id)


def session_owned_by(sess: Session, principal: Principal | None) -> bool:
    """True if this principal owns the session (or is an admin, or the session
    predates ownership and so belongs to everyone authenticated)."""
    if principal is None:
        return False
    if principal.role == Role.admin:
        return True
    if sess.owner_id is None:
        # Rows written before ownership existed. Treating them as unowned keeps
        # single-user installs working across the upgrade instead of hiding
        # every existing session from its own creator.
        return True
    return principal.user_id is not None and principal.user_id == sess.owner_id


def session_readable(sess: Session, principal: Principal | None, token: str | None) -> bool:
    """Whether a reader may see this session at all.

    Owner (or admin) always; anyone for a public session; anyone holding the
    session's capability token. Note this is coarse — it says nothing about
    *which* artifacts come back. Owner-only artifacts (transcripts) are filtered
    separately, so a share link never hands a stranger the conversation.
    """
    if session_owned_by(sess, principal):
        return True
    if sess.visibility == Visibility.public:
        return True
    if token and sess.share_token and secrets.compare_digest(token, sess.share_token):
        return True
    return False


def artifact_readable(art, sess: Session | None, principal: Principal | None,
                      token: str | None) -> bool:
    """Whether a reader may see one specific artifact.

    Beyond session readability there are two extra rules:
    - an artifact's own capability token unlocks just that artifact, and
    - `owner_only` artifacts (conversation slices) are withheld from everyone
      except the owner, however the session itself was reached.
    """
    if token and art.share_token and secrets.compare_digest(token, art.share_token):
        return True
    if sess is not None and not session_readable(sess, principal, token):
        return False
    if art.owner_only:
        return sess is not None and session_owned_by(sess, principal)
    return True


def optional_principal(request: Request, db: DBSession = Depends(get_session)) -> Principal | None:
    """Whoever is calling, if anyone. Used for visibility-gated reads."""
    return _user_from_cookie(request, db) or _principal_from_apikey(request, db)


def require_writer(request: Request, db: DBSession = Depends(get_session)) -> Principal:
    """A user (cookie) or a write-scoped API key. Used for all mutations."""
    p = _user_from_cookie(request, db) or _principal_from_apikey(request, db)
    if p is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    if not p.can_write:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "write scope required")
    return p


def require_user(request: Request, db: DBSession = Depends(get_session)) -> Principal:
    """A logged-in human (cookie only). For UI-only endpoints (keys, collections)."""
    p = _user_from_cookie(request, db)
    if p is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return p


def require_admin(p: Principal = Depends(require_user)) -> Principal:
    if p.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return p


def bootstrap_auth() -> None:
    """On startup: ensure an admin user exists + register the configured API key
    (so existing agents/CLI keep working without manual key creation)."""
    from .db import engine

    with DBSession(engine) as db:
        admin = db.exec(select(User).where(User.username == settings.admin_username)).first()
        if admin is None:
            admin = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role=Role.admin,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)

        if settings.api_key:
            kh = hash_token(settings.api_key)
            if db.exec(select(ApiKey).where(ApiKey.key_hash == kh)).first() is None:
                db.add(ApiKey(
                    key_hash=kh, prefix=settings.api_key[:8], label="bootstrap",
                    scope=Scope.write, user_id=admin.id,
                ))
                db.commit()
