"""Database engine + session/init helpers."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings

_is_pg = settings.database_url.startswith("postgresql")
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)


def init_db() -> None:
    # Import models so SQLModel.metadata is populated before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)

    if _is_pg:
        # Enum values can't be added inside a txn that also uses them — use autocommit.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("ALTER TYPE artifacttype ADD VALUE IF NOT EXISTS 'conversation'"))
        with engine.begin() as conn:
            # create_all won't add columns to a pre-existing table — do it idempotently.
            conn.execute(text("ALTER TABLE session ADD COLUMN IF NOT EXISTS search_text text DEFAULT ''"))
            conn.execute(text("ALTER TABLE session ADD COLUMN IF NOT EXISTS share_token varchar"))
            conn.execute(text("ALTER TABLE collection ADD COLUMN IF NOT EXISTS pinned json DEFAULT '[]'"))
            # Full-text index over the search document.
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS session_search_gin "
                "ON session USING gin (to_tsvector('english', search_text))"
            ))
        _backfill_search_text()


def _backfill_search_text() -> None:
    """Populate search_text for rows that predate the column (one-time)."""
    from .models import Session as SessionModel
    from .store import recompute_search_text

    with Session(engine) as db:
        rows = db.exec(select(SessionModel).where(SessionModel.search_text == "")).all()
        for s in rows:
            recompute_search_text(db, s)
            db.add(s)
        if rows:
            db.commit()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
