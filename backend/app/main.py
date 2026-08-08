"""ArtifactBay API entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import bootstrap_auth
from .config import settings
from .db import init_db
from .routers import artifacts, auth, catalog, collections, preview, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_auth()
    yield


app = FastAPI(title="ArtifactBay", version="0", lifespan=lifespan)

# Frontend SPA (Vite dev server) talks to this API cross-origin in dev.
# allow_credentials=True so the session cookie flows; origins must be explicit (not "*").
# Configurable because a self-hosted instance running the split setup on its own
# hostname could never add itself to a hardcoded localhost list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(collections.router)
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(artifacts.router)
app.include_router(preview.router)


@app.get("/v0/meta")
def meta() -> dict:
    return {
        "version": "0",
        "max_artifact_bytes": settings.max_artifact_bytes,
        "max_artifacts": settings.max_artifacts,
        "max_conversation_bytes": settings.max_conversation_bytes,
        "accepts": ["html", "markdown", "json", "svg", "png", "pdf", "zip", "text", "conversation"],
        "auth": "bearer",
        # Advertised so a client (the MCP server) can tell an upgraded instance
        # from an old one without probing endpoints for 404s.
        "capabilities": [
            "sessions.versions", "sessions.artifacts.append", "sessions.export",
            "artifacts.share", "artifacts.delete", "catalog.projects", "catalog.tags",
            "collections.patch", "conversation.owner_only",
        ],
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
