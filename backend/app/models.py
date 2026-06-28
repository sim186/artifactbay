"""SQLModel tables. Mirrors docs/01-api-contract-mvp.md §2."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column
from sqlalchemy.types import JSON, Text
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(str, enum.Enum):
    active = "active"
    finalized = "finalized"
    archived = "archived"


class Visibility(str, enum.Enum):
    private = "private"
    shared = "shared"
    public = "public"


class ArtifactType(str, enum.Enum):
    html = "html"
    markdown = "markdown"
    json = "json"
    svg = "svg"
    png = "png"
    pdf = "pdf"
    zip = "zip"
    text = "text"
    conversation = "conversation"  # JSON [{role, content, ts?}] — rendered as a transcript


class Role(str, enum.Enum):
    admin = "admin"
    member = "member"


class Scope(str, enum.Enum):
    read = "read"
    write = "write"


# Content-addressed blob: stored once per sha256, referenced by many artifacts.
class Blob(SQLModel, table=True):
    sha256: str = Field(primary_key=True)
    data: bytes
    size_bytes: int
    ref_count: int = 0


class Project(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_now)


class Session(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    description: str | None = None
    status: SessionStatus = Field(default=SessionStatus.active)
    agent: str = Field(index=True)
    model: str | None = None
    project_id: str | None = Field(default=None, foreign_key="project.id", index=True)
    git_repository: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    favorite: bool = False
    visibility: Visibility = Field(default=Visibility.private)
    version: int = 1
    # Denormalized searchable text: metadata + extracted current-version artifact text.
    # Indexed with a Postgres GIN(to_tsvector) for full-text search (see db.py).
    search_text: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# One row per artifact per version. Body lives in Blob via content_hash.
class Artifact(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    version: int = Field(index=True)
    name: str
    type: ArtifactType
    content_hash: str = Field(foreign_key="blob.sha256")
    size_bytes: int
    allow_scripts: bool = False
    created_at: datetime = Field(default_factory=_now)


class User(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: Role = Field(default=Role.member)
    created_at: datetime = Field(default_factory=_now)


# API key for agents. Token shown once; only its sha256 hash is stored.
class ApiKey(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    key_hash: str = Field(index=True, unique=True)
    prefix: str  # first chars of the token, for display (e.g. "fdy_ab12")
    label: str = ""
    scope: Scope = Field(default=Scope.write)
    user_id: str | None = Field(default=None, foreign_key="user.id")
    revoked: bool = False
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


# A collection = a saved query (named filter). Dynamic grouping, not a folder.
class Collection(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    # Stored filter, e.g. {"agent": "...", "favorite": true, "tag": "...", "q": "..."}
    query: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Manually pinned session ids — membership is (query matches) ∪ (these).
    pinned: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    owner_id: str | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=_now)


# Idempotency-Key -> session_id, so retried agent pushes don't duplicate.
class IdempotencyRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    session_id: str
    body_hash: str
    created_at: datetime = Field(default_factory=_now)
