#!/usr/bin/env python3
"""ArtifactBay client engine — shared by the CLI and the MCP server.

Stdlib only: no `pip install`, so it drops into any agent's shell unchanged.

What lives here (and why it isn't in the CLI any more): configuration resolution,
secret redaction, artifact packing and the HTTP calls. Both front ends — the
`artifactbay` command and the MCP server — are thin shells over this, so a fix to
redaction or session handling lands in both at once.

Configuration, highest precedence first:

  1. environment variables      ARTIFACTBAY_URL / ARTIFACTBAY_KEY / ...
  2. project config             ./.artifactbay/config.json
  3. user config                ~/.config/artifactbay/config.json

The user config is the point. Before it, every project needed its own env exports
or its own committed shim, which is what made "tell each project where to push"
a recurring chore. Run `artifactbay init` once per machine and every project on
that machine can push with no local setup at all.
"""
from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://localhost:8080"

EXT_TYPE = {
    ".html": "html", ".htm": "html", ".md": "markdown", ".markdown": "markdown",
    ".json": "json", ".svg": "svg", ".png": "png", ".pdf": "pdf",
    ".zip": "zip", ".txt": "text", ".log": "text",
}
BINARY = {"png", "pdf", "zip"}

USER_CONFIG = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "artifactbay" / "config.json"
PROJECT_CONFIG = Path(".artifactbay/config.json")


# ── configuration ────────────────────────────────────────────────────────────
def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — an unreadable config must never block a push
        return {}


def load_config(overrides: dict | None = None) -> dict:
    """Merge user config → project config → environment → explicit overrides."""
    merged: dict[str, Any] = {}
    merged.update(_read_json(USER_CONFIG))
    merged.update(_read_json(PROJECT_CONFIG))

    env_map = {
        "url": "ARTIFACTBAY_URL", "key": "ARTIFACTBAY_KEY", "project": "ARTIFACTBAY_PROJECT",
        "agent": "ARTIFACTBAY_AGENT", "model": "ARTIFACTBAY_MODEL",
        "artifacts_dir": "ARTIFACTBAY_ARTIFACTS_DIR", "tags": "ARTIFACTBAY_TAGS",
        "allow_scripts": "ARTIFACTBAY_ALLOW_SCRIPTS",
    }
    for field, var in env_map.items():
        value = os.environ.get(var)
        if value:
            merged[field] = value
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})

    def as_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value or "").split(",") if v.strip()]

    return {
        "url": str(merged.get("url") or DEFAULT_URL).rstrip("/"),
        "key": str(merged.get("key") or ""),
        "project": merged.get("project") or None,
        "agent": merged.get("agent") or "claude-code",
        "model": merged.get("model") or None,
        "artifacts_dir": Path(merged.get("artifacts_dir") or ".artifactbay/artifacts"),
        "tags": as_list(merged.get("tags")),
        "allow_scripts": as_list(merged.get("allow_scripts")),
        "redact": merged.get("redact", True),
        "state_dir": Path(".artifactbay"),
    }


def write_user_config(url: str, key: str, **extra) -> Path:
    """Persist machine-wide defaults so projects need no local setup."""
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    body = {"url": url.rstrip("/"), "key": key}
    body.update({k: v for k, v in extra.items() if v})
    USER_CONFIG.write_text(json.dumps(body, indent=2) + "\n")
    # The key is a credential — keep it out of other users' reach.
    try:
        USER_CONFIG.chmod(0o600)
    except OSError:
        pass
    return USER_CONFIG


# ── redaction ────────────────────────────────────────────────────────────────
# Deliberately conservative: catch the shapes that are unambiguously secrets.
# A transcript is the one artifact likely to contain something nobody meant to
# publish, and redaction happens client-side — before bytes leave the machine.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[abpsr]-[A-Za-z0-9-]{10,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("artifactbay-key", re.compile(r"\bab_[A-Za-z0-9_-]{20,}\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    # KEY=value / "api_key": "value" assignments of secret-ish names.
    ("assignment", re.compile(
        r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API[_-]?KEY|ACCESS[_-]?KEY)[A-Z0-9_]*)"
        r"(\s*[:=]\s*)(\"[^\"\n]{6,}\"|'[^'\n]{6,}'|[^\s,;}\n]{6,})")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Strip credential-shaped substrings. Returns (clean_text, kinds_found)."""
    found: list[str] = []
    for kind, pattern in _SECRET_PATTERNS:
        if kind == "assignment":
            def _sub(m: re.Match[str]) -> str:
                return f"{m.group(1)}{m.group(2)}[REDACTED]"
            text, n = pattern.subn(_sub, text)
        else:
            text, n = pattern.subn("[REDACTED]", text)
        if n:
            found.append(kind)
    return text, found


# ── artifact packing ─────────────────────────────────────────────────────────
def _guess_type(path: Path) -> str | None:
    if path.name == "conversation.json" or path.name.endswith(".conversation.json"):
        return "conversation"
    return EXT_TYPE.get(path.suffix.lower())


def pack_file(path: Path, allow_globs: list[str], do_redact: bool = True) -> dict | None:
    """Turn a file on disk into an artifact payload. None = unsupported type."""
    artifact_type = _guess_type(path)
    if artifact_type is None:
        return None
    raw = path.read_bytes()
    if artifact_type in BINARY:
        return {"name": path.name, "type": artifact_type, "encoding": "base64",
                "content": base64.b64encode(raw).decode()}

    content = raw.decode("utf-8", errors="replace")
    if do_redact:
        content, _ = redact(content)
    art = {"name": path.name, "type": artifact_type, "encoding": "utf8", "content": content}
    if artifact_type == "html" and any(fnmatch.fnmatch(path.name, g) for g in allow_globs):
        art["allow_scripts"] = True
    return art


def collect_artifacts(directory: Path, allow_globs: list[str] | None = None,
                      do_redact: bool = True) -> list[dict]:
    arts: list[dict] = []
    if not directory.is_dir():
        return arts
    for p in sorted(directory.rglob("*")):
        if p.is_file():
            art = pack_file(p, allow_globs or [], do_redact)
            if art is not None:  # skip unknown types — don't guess
                arts.append(art)
    return arts


def collect_paths(paths: list[str], allow_globs: list[str] | None = None,
                  do_redact: bool = True) -> tuple[list[dict], list[str]]:
    """Pack explicit file/directory paths. Returns (artifacts, skipped_descriptions).

    This is what makes `artifactbay push ./report.html` work: an agent that just
    wrote a file somewhere no longer has to copy it into a staging directory first.
    """
    arts: list[dict] = []
    skipped: list[str] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            arts.extend(collect_artifacts(p, allow_globs, do_redact))
            continue
        if not p.is_file():
            skipped.append(f"{raw} (not found)")
            continue
        art = pack_file(p, allow_globs or [], do_redact)
        if art is None:
            skipped.append(f"{raw} (unsupported type)")
        else:
            arts.append(art)
    return arts, skipped


def make_conversation_artifact(messages: list[dict], name: str = "conversation.json",
                               do_redact: bool = True) -> dict:
    """Build the provenance slice that accompanies an artifact.

    Kept deliberately small and owner-only: this is the reasoning behind one
    artifact, not an archive of everything ever said. The server trims it again
    and withholds it from anonymous readers.
    """
    clean: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = str(m.get("content", ""))
        if do_redact:
            content, _ = redact(content)
        entry = {"role": str(m.get("role", "assistant")), "content": content}
        if m.get("ts"):
            entry["ts"] = m["ts"]
        clean.append(entry)
    return {
        "name": name, "type": "conversation", "encoding": "utf8",
        "content": json.dumps(clean, ensure_ascii=False),
        "owner_only": True,
    }


# ── git context ──────────────────────────────────────────────────────────────
def git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def git_context() -> dict:
    return {
        "repository": git("config", "--get", "remote.origin.url"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "HEAD"),
    }


# ── HTTP ─────────────────────────────────────────────────────────────────────
class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status} {message}")
        self.status = status
        self.message = message


def request(method: str, url: str, key: str = "", body: Any = None,
            idem: str | None = None, timeout: int = 30) -> Any:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if idem:
        headers["Idempotency-Key"] = idem
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise ApiError(e.code, detail or e.reason) from e


class Client:
    """Thin typed-ish wrapper over the v0 API."""

    def __init__(self, cfg: dict):
        self.url = cfg["url"]
        self.key = cfg["key"]

    def _call(self, method: str, path: str, body: Any = None, idem: str | None = None) -> Any:
        return request(method, f"{self.url}{path}", key=self.key, body=body, idem=idem)

    # reads
    def meta(self) -> dict:
        return request("GET", f"{self.url}/v0/meta")

    def check(self) -> dict:
        return self._call("GET", "/v0/auth/check")

    def list_sessions(self, **params) -> dict:
        clean = {k: v for k, v in params.items() if v is not None}
        query = urllib.parse.urlencode(clean)
        return self._call("GET", f"/v0/sessions{'?' + query if query else ''}")

    def get_session(self, session_id: str, version: int | None = None) -> dict:
        suffix = f"?version={version}" if version else ""
        return self._call("GET", f"/v0/sessions/{session_id}{suffix}")

    def list_versions(self, session_id: str) -> dict:
        return self._call("GET", f"/v0/sessions/{session_id}/versions")

    def artifact_meta(self, artifact_id: str) -> dict:
        return self._call("GET", f"/v0/artifacts/{artifact_id}/meta")

    def artifact_body(self, artifact_id: str) -> bytes:
        req = urllib.request.Request(
            f"{self.url}/v0/artifacts/{artifact_id}",
            headers={"Authorization": f"Bearer {self.key}"} if self.key else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.reason) from e

    def projects(self) -> list:
        return self._call("GET", "/v0/projects")

    def tags(self) -> list:
        return self._call("GET", "/v0/tags")

    # writes
    def create_session(self, payload: dict, idem: str | None = None) -> dict:
        return self._call("POST", "/v0/sessions", payload, idem=idem)

    def new_version(self, session_id: str, payload: dict) -> dict:
        return self._call("POST", f"/v0/sessions/{session_id}/versions", payload)

    def append_artifacts(self, session_id: str, artifacts: list[dict]) -> dict:
        return self._call("POST", f"/v0/sessions/{session_id}/artifacts",
                          {"artifacts": artifacts})

    def share_session(self, session_id: str, rotate: bool = False) -> dict:
        suffix = "?rotate=true" if rotate else ""
        return self._call("POST", f"/v0/sessions/{session_id}/share{suffix}", {})

    def share_artifact(self, artifact_id: str, rotate: bool = False) -> dict:
        suffix = "?rotate=true" if rotate else ""
        return self._call("POST", f"/v0/artifacts/{artifact_id}/share{suffix}", {})


# ── push ─────────────────────────────────────────────────────────────────────
def build_payload(cfg: dict, name: str | None, artifacts: list[dict]) -> dict:
    g = git_context()
    repo = g["repository"] or ""
    return {
        "name": name or git("log", "-1", "--pretty=%s") or Path.cwd().name,
        "agent": cfg["agent"],
        "model": cfg["model"],
        "project": cfg["project"] or (Path(repo).stem or None if repo else None),
        "git": g,
        "tags": cfg["tags"],
        "artifacts": artifacts,
    }


def send(cfg: dict, payload: dict, idem: str, session_id: str | None = None) -> dict:
    """POST a payload, versioning an existing session when we know one.

    The session id is remembered per project in `.artifactbay/session_id`, so a
    re-push becomes v2 rather than a duplicate. A cached id that the server has
    never heard of (different instance, reset database) yields a 404, and we fall
    back to creating a fresh session instead of failing the push.
    """
    client = Client(cfg)
    state_dir: Path = cfg["state_dir"]
    sid_file = state_dir / "session_id"
    sid = session_id or (sid_file.read_text().strip() if sid_file.is_file() else None)

    if sid:
        try:
            return client.new_version(sid, payload)
        except ApiError as e:
            if e.status != 404:
                raise

    out = client.create_session(payload, idem=idem)
    state_dir.mkdir(parents=True, exist_ok=True)
    sid_file.write_text(out["id"])
    return out


def queue(cfg: dict, payload: dict, idem: str) -> Path:
    """Park a failed push on disk so the agent is never blocked by a down server."""
    pending = cfg["state_dir"] / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    path = pending / f"{idem}.json"
    path.write_text(json.dumps({"idem": idem, "payload": payload}))
    return path


def push(cfg: dict, name: str | None, artifacts: list[dict],
         session_id: str | None = None) -> dict:
    """Push artifacts, queueing on failure. Returns a result dict (never raises)."""
    if not artifacts:
        return {"ok": False, "reason": "no_artifacts"}
    if not cfg["key"]:
        return {"ok": False, "reason": "no_key"}

    payload = build_payload(cfg, name, artifacts)
    idem = uuid.uuid4().hex
    try:
        out = send(cfg, payload, idem, session_id)
        return {"ok": True, "id": out.get("id"), "version": out.get("version"),
                "url": out.get("url"), "artifacts": out.get("artifacts", [])}
    except Exception as e:  # noqa: BLE001 — fail-open: queue, never crash the agent
        path = queue(cfg, payload, idem)
        return {"ok": False, "reason": "queued", "queued_at": str(path), "error": str(e)}
