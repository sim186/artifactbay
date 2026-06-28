"""Persistence helpers: content-addressed blobs + version snapshots."""
from __future__ import annotations

import base64
import hashlib
import json
from html.parser import HTMLParser

from fastapi import HTTPException, status
from sqlmodel import Session as DBSession
from sqlmodel import select

from .config import settings
from .models import Artifact, Blob, Collection, IdempotencyRecord, Project, Session
from .schemas import ArtifactIn, SessionIn

# Text types whose decoded bytes are directly searchable.
_TEXT_TYPES = {"markdown", "json", "text", "svg"}


class _TextExtractor(HTMLParser):
    """Pull visible text out of HTML; ignore script/style/tags."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            s = data.strip()
            if s:
                self.parts.append(s)


def extract_text(artifact_type: str, data: bytes) -> str:
    """Best-effort searchable text from artifact bytes. Binary types → ''."""
    if artifact_type == "html":
        p = _TextExtractor()
        try:
            p.feed(data.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return ""
        return " ".join(p.parts)
    if artifact_type == "conversation":
        # JSON [{role, content, ...}] → concat message text for search.
        try:
            msgs = json.loads(data.decode("utf-8", errors="replace"))
            return "\n".join(str(m.get("content", "")) for m in msgs if isinstance(m, dict))
        except Exception:  # noqa: BLE001
            return data.decode("utf-8", errors="replace")
    if artifact_type in _TEXT_TYPES:
        return data.decode("utf-8", errors="replace")
    return ""  # png/pdf/zip — not text-searchable here


def build_search_text(sess: Session, artifact_rows: list[tuple[str, str]]) -> str:
    """Concatenate metadata + extracted artifact text into one search document.

    artifact_rows: list of (name, extracted_text).
    """
    bits = [
        sess.name or "",
        sess.description or "",
        " ".join(sess.tags or []),
        sess.agent or "",
        sess.model or "",
        sess.git_repository or "",
        sess.git_branch or "",
        sess.git_commit or "",
    ]
    for name, text in artifact_rows:
        bits.append(name)
        bits.append(text)
    return "\n".join(b for b in bits if b)


def decode_artifact(a: ArtifactIn) -> bytes:
    if a.encoding == "base64":
        try:
            return base64.b64decode(a.content, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"bad base64 in {a.name}") from exc
    return a.content.encode("utf-8")


def store_blob(db: DBSession, data: bytes) -> str:
    """Store bytes once by sha256; bump ref_count. Returns hash."""
    digest = hashlib.sha256(data).hexdigest()
    blob = db.get(Blob, digest)
    if blob is None:
        blob = Blob(sha256=digest, data=data, size_bytes=len(data), ref_count=1)
        db.add(blob)
        # Flush now so the row exists before any Artifact FK references it.
        # (No ORM relationship => unit-of-work won't auto-order blob before artifact.)
        db.flush()
    else:
        blob.ref_count += 1
        db.add(blob)
    return digest


def upsert_project(db: DBSession, name: str | None) -> str | None:
    if not name:
        return None
    proj = db.exec(select(Project).where(Project.name == name)).first()
    if proj is None:
        proj = Project(name=name)
        db.add(proj)
        db.flush()
    return proj.id


def write_artifacts(
    db: DBSession, session_id: str, version: int, payload: SessionIn
) -> tuple[list[Artifact], list[tuple[str, str]]]:
    """Persist artifacts. Returns (rows, [(name, extracted_text), ...]) for search indexing."""
    if len(payload.artifacts) > settings.max_artifacts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "too many artifacts")
    rows: list[Artifact] = []
    texts: list[tuple[str, str]] = []
    for a in payload.artifacts:
        data = decode_artifact(a)
        if len(data) > settings.max_artifact_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{a.name} exceeds size limit")
        digest = store_blob(db, data)
        row = Artifact(
            session_id=session_id,
            version=version,
            name=a.name,
            type=a.type,
            content_hash=digest,
            size_bytes=len(data),
            allow_scripts=a.allow_scripts and a.type.value == "html",
        )
        db.add(row)
        rows.append(row)
        texts.append((a.name, extract_text(a.type.value, data)))
    return rows, texts


def recompute_search_text(db: DBSession, sess: Session) -> None:
    """Rebuild sess.search_text from metadata + current-version artifacts (read from blobs)."""
    rows = db.exec(
        select(Artifact).where(Artifact.session_id == sess.id, Artifact.version == sess.version)
    ).all()
    pairs: list[tuple[str, str]] = []
    for a in rows:
        blob = db.get(Blob, a.content_hash)
        text = extract_text(a.type.value, blob.data) if blob else ""
        pairs.append((a.name, text))
    sess.search_text = build_search_text(sess, pairs)


def body_hash(payload: SessionIn) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def delete_session_and_cleanup_blobs(db: DBSession, session_id: str) -> None:
    """Delete a session, clean up its artifacts, decrement referenced blob ref_counts
    (deleting blobs that drop to 0 ref_count), delete associated idempotency records,
    and remove the session from any collection pin lists.
    """
    sess = db.get(Session, session_id)
    if not sess:
        return

    # 1. Decrement ref counts of blobs linked to this session's artifacts
    artifacts = db.exec(select(Artifact).where(Artifact.session_id == session_id)).all()
    for art in artifacts:
        blob = db.get(Blob, art.content_hash)
        if blob:
            blob.ref_count -= 1
            if blob.ref_count <= 0:
                db.delete(blob)
            else:
                db.add(blob)
        db.delete(art)

    # 2. Delete associated idempotency records
    idem_records = db.exec(select(IdempotencyRecord).where(IdempotencyRecord.session_id == session_id)).all()
    for rec in idem_records:
        db.delete(rec)

    # 3. Clean up collections that have pinned this session
    collections = db.exec(select(Collection)).all()
    for col_row in collections:
        if col_row.pinned and session_id in col_row.pinned:
            col_row.pinned = [x for x in col_row.pinned if x != session_id]
            db.add(col_row)

    # 4. Delete the session itself
    db.delete(sess)
