"""Foundry API entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import bootstrap_auth
from .config import settings
from .db import init_db
from .routers import artifacts, auth, collections, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_auth()
    yield


app = FastAPI(title="Foundry", version="0", lifespan=lifespan)

# Frontend SPA (Vite dev server) talks to this API cross-origin in dev.
# allow_credentials=True so the session cookie flows; origins must be explicit (not "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(collections.router)
app.include_router(sessions.router)
app.include_router(artifacts.router)


@app.get("/v0/meta")
def meta() -> dict:
    return {
        "version": "0",
        "max_artifact_bytes": settings.max_artifact_bytes,
        "max_artifacts": settings.max_artifacts,
        "accepts": ["html", "markdown", "json", "svg", "png", "pdf", "zip", "text", "conversation"],
        "auth": "bearer",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
