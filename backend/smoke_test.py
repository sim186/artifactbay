"""End-to-end smoke test against the app via TestClient. Run: uv run python smoke_test.py"""
from __future__ import annotations

import base64
import json
import os

os.environ.setdefault("FOUNDRY_DATABASE_URL", "sqlite:///./smoke.db")

from fastapi.testclient import TestClient  # noqa: E402

from sqlmodel import SQLModel  # noqa: E402

from app import models as _models  # noqa: E402,F401  (populate metadata)
from app.auth import bootstrap_auth  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402

# Clean slate so the test is isolated on a persistent DB (Postgres volume).
SQLModel.metadata.drop_all(engine)
init_db()
bootstrap_auth()  # seed admin user + register the bootstrap API key
H = {"Authorization": f"Bearer {settings.api_key}"}
client = TestClient(app, headers=H)  # authenticated via bootstrap API key by default
anon = TestClient(app)               # no credentials

PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f6f0000000049454e44ae426082"
)).decode()


def main() -> None:
    # meta
    assert client.get("/v0/meta").json()["version"] == "0"

    # auth required (anonymous → 401)
    r = anon.post("/v0/sessions", json={"name": "x", "agent": "claude-code"})
    assert r.status_code == 401, r.status_code

    # create
    body = {
        "name": "Database redesign",
        "agent": "claude-code",
        "model": "claude-opus-4-8",
        "project": "Inspector",
        "git": {"repository": "git@github.com:acme/inspector.git", "branch": "main", "commit": "abc123"},
        "tags": ["database", "api"],
        "artifacts": [
            {"name": "architecture.html", "type": "html",
             "content": "<html><body><h1>Hi</h1><script>alert(1)</script></body></html>",
             "allow_scripts": False},
            {"name": "diagram.png", "type": "png", "encoding": "base64", "content": PNG_1PX},
        ],
    }
    r = client.post("/v0/sessions", json=body, headers={**H, "Idempotency-Key": "run-1"})
    assert r.status_code == 201, (r.status_code, r.text)
    sid = r.json()["id"]
    assert r.json()["version"] == 1
    html_art = next(a for a in r.json()["artifacts"] if a["name"] == "architecture.html")

    # idempotency: same key + body -> same session
    r2 = client.post("/v0/sessions", json=body, headers={**H, "Idempotency-Key": "run-1"})
    assert r2.json()["id"] == sid, "idempotency duplicated session"

    # idempotency conflict: same key, different body
    r3 = client.post("/v0/sessions", json={**body, "name": "changed"},
                     headers={**H, "Idempotency-Key": "run-1"})
    assert r3.status_code == 409, r3.status_code

    # get session
    r = client.get(f"/v0/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["version"] == 1
    assert len(r.json()["artifacts"]) == 2

    # new version
    body_v2 = {**body, "artifacts": body["artifacts"][:1]}
    r = client.post(f"/v0/sessions/{sid}/versions", json=body_v2, headers=H)
    assert r.status_code == 201 and r.json()["version"] == 2, r.text
    r = client.get(f"/v0/sessions/{sid}")
    assert r.json()["version"] == 2
    assert len(r.json()["artifacts"]) == 1  # v2 has 1 artifact
    r = client.get(f"/v0/sessions/{sid}?version=1")
    assert len(r.json()["artifacts"]) == 2  # v1 still intact

    # list sessions
    r = client.get("/v0/sessions")
    assert r.status_code == 200
    lst = r.json()
    assert lst["total"] >= 1
    mine = next(s for s in lst["sessions"] if s["id"] == sid)
    assert mine["artifact_count"] == 1  # current version (v2) has 1
    assert mine["version"] == 2
    # filter by agent
    r = client.get("/v0/sessions?agent=claude-code")
    assert any(s["id"] == sid for s in r.json()["sessions"])
    # naive q match (name)
    r = client.get("/v0/sessions?q=redesign")
    assert any(s["id"] == sid for s in r.json()["sessions"])
    # q matches tags too
    r = client.get("/v0/sessions?q=database")
    assert any(s["id"] == sid for s in r.json()["sessions"]), "tag search failed"
    # full-text search hits ARTIFACT CONTENT (the <h1>Hi</h1> in architecture.html v1)
    # v2 dropped that artifact, so search the v1 content via a fresh session below.
    fts_body = {
        "name": "Observability session", "agent": "claude-code",
        "artifacts": [{"name": "page.html", "type": "html",
                       "content": "<html><body><h1>Telemetry</h1>"
                                  "<p>distributed tracing with OpenTelemetry spans</p></body></html>"}],
    }
    r = client.post("/v0/sessions", json=fts_body, headers={**H, "Idempotency-Key": "fts-1"})
    fts_id = r.json()["id"]
    # word only present in artifact body, not metadata:
    r = client.get("/v0/sessions?q=OpenTelemetry")
    hit = next((s for s in r.json()["sessions"] if s["id"] == fts_id), None)
    assert hit is not None, "full-text search over artifact content failed"
    is_pg = settings.database_url.startswith("postgresql")
    if is_pg:
        assert hit["snippet"] and "@@HLS@@" in hit["snippet"], "missing highlighted snippet"
        # stemming: 'spans' query matches 'spans' stem in body
        r = client.get("/v0/sessions?q=tracing")
        assert any(s["id"] == fts_id for s in r.json()["sessions"]), "stemming search failed"

    # PATCH favorite
    r = client.patch(f"/v0/sessions/{sid}", json={"favorite": True}, headers=H)
    assert r.status_code == 200 and r.json()["favorite"] is True, r.text
    r = client.get("/v0/sessions?favorite=true")
    assert any(s["id"] == sid for s in r.json()["sessions"])
    # PATCH unauth rejected
    assert anon.patch(f"/v0/sessions/{sid}", json={"favorite": False}).status_code == 401

    # raw artifact
    aid = html_art["id"]
    r = client.get(f"/v0/artifacts/{aid}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "<h1>Hi</h1>" in r.text  # byte-for-byte

    # sandboxed view: scripts blocked (allow_scripts False)
    r = client.get(f"/v0/artifacts/{aid}/view")
    assert "script-src 'none'" in r.headers["content-security-policy"], r.headers
    assert r.headers["x-content-type-options"] == "nosniff"

    # ── auth ──────────────────────────────────────────────────────────────
    # bootstrap key still works (seeded as hashed ApiKey)
    assert client.get("/v0/auth/check", headers=H).status_code == 200
    assert anon.get("/v0/auth/check").status_code == 401  # no creds
    # password login → cookie
    r = client.post("/v0/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin", r.text
    assert client.get("/v0/auth/me").json()["username"] == "admin"  # cookie persisted by client
    assert client.post("/v0/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    # mint a write key, use it to push (as an anonymous client carrying only that key)
    r = client.post("/v0/auth/keys", json={"label": "ci", "scope": "write"})
    assert r.status_code == 201
    new_key = r.json()
    key_id, new_token = new_key["id"], new_key["token"]
    assert new_token.startswith("fdy_")
    assert all("token" not in k for k in client.get("/v0/auth/keys").json())  # never re-exposed
    KH = {"Authorization": f"Bearer {new_token}"}
    assert anon.post("/v0/sessions", json={"name": "via new key", "agent": "codex"},
                     headers=KH).status_code == 201
    # revoke THIS key → now rejected (bootstrap key untouched). Revoked = no principal → 401.
    assert client.delete(f"/v0/auth/keys/{key_id}").status_code == 204
    assert anon.post("/v0/sessions", json={"name": "x", "agent": "codex"},
                     headers=KH).status_code == 401

    # ── empty-query collection = manual-only (pins), NOT "match everything" ──
    r = client.post("/v0/collections", json={"name": "Manual picks", "query": {}})
    mc = r.json()["id"]
    assert client.get(f"/v0/collections/{mc}/sessions").json()["total"] == 0, "empty query matched everything"
    client.put(f"/v0/collections/{mc}/sessions/{sid}")
    m = client.get(f"/v0/collections/{mc}/sessions").json()
    assert m["total"] == 1 and m["sessions"][0]["id"] == sid, "manual-only collection wrong"
    client.delete(f"/v0/collections/{mc}")

    # ── collections (hybrid: saved query + manual pins, login required) ───
    r = client.post("/v0/collections", json={"name": "DB work", "query": {"q": "database"}})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert any(c["id"] == cid for c in client.get("/v0/collections").json())
    # resolve = query matches (sid matches q=database via tags)
    members = client.get(f"/v0/collections/{cid}/sessions").json()["sessions"]
    assert any(s["id"] == sid for s in members), "query membership failed"
    # manually pin a session that does NOT match the query (fts_id has no 'database')
    r = client.put(f"/v0/collections/{cid}/sessions/{fts_id}")
    assert r.status_code == 200 and fts_id in r.json()["pinned"]
    members = client.get(f"/v0/collections/{cid}/sessions").json()["sessions"]
    assert any(s["id"] == fts_id for s in members), "pinned session not in collection"
    # unpin
    r = client.delete(f"/v0/collections/{cid}/sessions/{fts_id}")
    assert fts_id not in r.json()["pinned"]
    members = client.get(f"/v0/collections/{cid}/sessions").json()["sessions"]
    assert not any(s["id"] == fts_id for s in members), "unpin failed"
    assert client.delete(f"/v0/collections/{cid}").status_code == 204

    # ── conversation artifact ─────────────────────────────────────────────
    convo = json.dumps([
        {"role": "user", "content": "refactor the auth module"},
        {"role": "assistant", "content": "extracted JWT verification into middleware"},
    ])
    r = client.post("/v0/sessions", json={
        "name": "Chat session", "agent": "claude-code",
        "artifacts": [{"name": "conversation.json", "type": "conversation", "content": convo}],
    }, headers=H, )
    assert r.status_code == 201, r.text
    convo_sid = r.json()["id"]
    if is_pg:
        # conversation content is searchable
        r = client.get("/v0/sessions?q=middleware")
        assert any(s["id"] == convo_sid for s in r.json()["sessions"]), "conversation not searchable"

    # ── visibility ────────────────────────────────────────────────────────
    r = client.post("/v0/sessions", json={"name": "secret", "agent": "codex", "visibility": "private"},
                    headers=H)
    priv_id = r.json()["id"]
    r = client.post("/v0/sessions", json={"name": "shared-pub", "agent": "codex", "visibility": "public"},
                    headers=H)
    pub_id = r.json()["id"]
    # anonymous client sees only public sessions
    anon_ids = {s["id"] for s in anon.get("/v0/sessions").json()["sessions"]}
    assert pub_id in anon_ids and priv_id not in anon_ids, "visibility filter failed"
    assert anon.get(f"/v0/sessions/{priv_id}").status_code == 404
    assert anon.get(f"/v0/sessions/{pub_id}").status_code == 200

    print("ALL SMOKE TESTS PASSED ✅")


if __name__ == "__main__":
    main()
