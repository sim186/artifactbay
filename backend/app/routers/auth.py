"""Auth + API-key management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..auth import (
    Principal,
    hash_token,
    make_jwt,
    new_api_token,
    require_user,
    require_writer,
    verify_password,
)
from ..config import settings
from ..db import get_session
from ..models import ApiKey, Scope, User

router = APIRouter(prefix="/v0/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    role: str


class KeyOut(BaseModel):
    id: str
    prefix: str
    label: str
    scope: str
    revoked: bool
    last_used_at: str | None
    created_at: str


class KeyCreateIn(BaseModel):
    label: str = ""
    scope: Scope = Scope.write


class KeyCreatedOut(KeyOut):
    token: str  # plaintext — shown ONCE


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        settings.cookie_name, token, httponly=True, samesite="lax",
        secure=settings.cookie_secure, max_age=settings.jwt_ttl_hours * 3600, path="/",
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: DBSession = Depends(get_session)) -> UserOut:
    user = db.exec(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    _set_cookie(response, make_jwt(user))
    return UserOut(id=user.id, username=user.username, role=user.role.value)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(p: Principal = Depends(require_user), db: DBSession = Depends(get_session)) -> UserOut:
    user = db.get(User, p.id)
    return UserOut(id=user.id, username=user.username, role=user.role.value)


@router.get("/check")
def check(p: Principal = Depends(require_writer)) -> dict:
    # Cheap authed ping for `foundry doctor` — validates a write key or session.
    return {"ok": True, "kind": p.kind, "scope": p.scope.value if p.scope else "user"}


@router.get("/keys", response_model=list[KeyOut])
def list_keys(p: Principal = Depends(require_user), db: DBSession = Depends(get_session)) -> list[KeyOut]:
    rows = db.exec(select(ApiKey).where(ApiKey.user_id == p.id)).all()
    return [
        KeyOut(id=k.id, prefix=k.prefix, label=k.label, scope=k.scope.value, revoked=k.revoked,
               last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
               created_at=k.created_at.isoformat())
        for k in rows
    ]


@router.post("/keys", response_model=KeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_key(body: KeyCreateIn, p: Principal = Depends(require_user),
               db: DBSession = Depends(get_session)) -> KeyCreatedOut:
    token = new_api_token()
    row = ApiKey(key_hash=hash_token(token), prefix=token[:8], label=body.label,
                 scope=body.scope, user_id=p.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return KeyCreatedOut(
        id=row.id, prefix=row.prefix, label=row.label, scope=row.scope.value, revoked=row.revoked,
        last_used_at=None, created_at=row.created_at.isoformat(), token=token,
    )


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(key_id: str, p: Principal = Depends(require_user),
               db: DBSession = Depends(get_session)) -> Response:
    row = db.get(ApiKey, key_id)
    if row is None or row.user_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    row.revoked = True
    db.add(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
