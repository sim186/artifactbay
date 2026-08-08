"""Request/response models (the wire contract, separate from DB tables)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .models import ArtifactType, SessionStatus, Visibility


class GitInfo(BaseModel):
    repository: str | None = None
    branch: str | None = None
    commit: str | None = None


class ArtifactIn(BaseModel):
    name: str
    type: ArtifactType
    encoding: str = "utf8"  # "utf8" | "base64"
    content: str
    allow_scripts: bool = False
    # None = use the default for the type: conversation slices are owner-only,
    # everything else follows the session. Set explicitly to override.
    owner_only: bool | None = None


class ArtifactsIn(BaseModel):
    """Append artifacts to a session's current version (no new snapshot)."""

    artifacts: list[ArtifactIn] = Field(default_factory=list)


class SessionIn(BaseModel):
    name: str
    description: str | None = None
    agent: str
    model: str | None = None
    project: str | None = None  # project NAME; server upserts
    git: GitInfo | None = None
    tags: list[str] = Field(default_factory=list)
    visibility: Visibility = Visibility.private
    favorite: bool = False
    artifacts: list[ArtifactIn] = Field(default_factory=list)


# Partial mutation of an active session (no new version). PATCH semantics.
class SessionPatch(BaseModel):
    favorite: bool | None = None
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    status: SessionStatus | None = None
    visibility: Visibility | None = None


class ArtifactRef(BaseModel):
    id: str
    name: str
    url: str


class CreateSessionOut(BaseModel):
    id: str
    version: int
    url: str
    artifacts: list[ArtifactRef]


class ArtifactOut(BaseModel):
    id: str
    name: str
    type: ArtifactType
    size_bytes: int
    allow_scripts: bool
    url: str
    owner_only: bool = False
    # Per-artifact capability link; only ever populated for the owner.
    share_url: str | None = None


class ArtifactDetailOut(ArtifactOut):
    content_hash: str
    session_id: str
    session_name: str
    version: int


class VersionOut(BaseModel):
    """One snapshot in a session's history."""

    version: int
    artifact_count: int
    total_bytes: int
    created_at: str


class VersionListOut(BaseModel):
    versions: list[VersionOut]
    current: int


class ProjectOut(BaseModel):
    id: str
    name: str
    session_count: int


class TagOut(BaseModel):
    tag: str
    session_count: int


class SessionSummary(BaseModel):
    id: str
    name: str
    agent: str
    model: str | None
    status: str
    version: int
    favorite: bool
    tags: list[str]
    git: GitInfo
    artifact_count: int
    updated_at: str
    url: str
    snippet: str | None = None  # highlighted FTS match fragment, when q is given


class SessionListOut(BaseModel):
    sessions: list[SessionSummary]
    total: int


class SessionOut(BaseModel):
    id: str
    name: str
    description: str | None
    status: str
    agent: str
    model: str | None
    project_id: str | None
    git: GitInfo
    tags: list[str]
    favorite: bool
    visibility: str
    version: int
    requested_version: int
    created_at: str
    updated_at: str
    share_url: str | None = None  # capability link; only present for authenticated owners
    # Whether the caller owns this session. Drives owner-only UI (share, delete)
    # instead of the client guessing from "is anyone logged in".
    is_owner: bool = False
    artifacts: list[ArtifactOut]


class ShareOut(BaseModel):
    url: str
