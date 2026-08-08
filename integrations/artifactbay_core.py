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
from html import escape
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


# ── standalone packing (no server involved) ──────────────────────────────────
# Mirrors backend/app/standalone.py. Duplicated on purpose: this half has to run
# with nothing but the stdlib on a machine that may never reach an ArtifactBay,
# which is the entire point of `artifactbay pack --local`.
_PACK_CSS = """
:root{color-scheme:dark light}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  background:#0f1116;color:#e6e9ef;height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:.75rem;padding:.6rem 1rem;
  border-bottom:1px solid #232936;flex:none}
h1{font-size:.95rem;margin:0;font-weight:600}
.meta{font:11px ui-monospace,monospace;color:#7d8698}
nav{display:flex;gap:.25rem;overflow-x:auto;padding:.5rem 1rem;border-bottom:1px solid #232936;flex:none}
nav button{background:none;border:1px solid transparent;color:#9aa3b2;cursor:pointer;
  padding:.3rem .7rem;border-radius:6px;font-size:.8rem;white-space:nowrap}
nav button:hover{background:#1a1f2b;color:#e6e9ef}
nav button[aria-selected=true]{background:#2b3350;border-color:#4c5680;color:#fff}
main{flex:1;min-height:0;position:relative;background:#fff}
section{position:absolute;inset:0;display:none}
section[data-active=true]{display:block}
iframe{width:100%;height:100%;border:0;background:#fff}
.img{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  padding:1.5rem;background:#fff}
.img img{max-width:100%;max-height:100%}
pre{margin:0;width:100%;height:100%;overflow:auto;padding:1.5rem;background:#12151c;
  color:#e6e9ef;font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word}
.doc{height:100%;overflow:auto;padding:2rem 2.5rem;background:#12151c;color:#e6e9ef;
  font-size:15px;line-height:1.65;max-width:none}
.doc h1,.doc h2,.doc h3,.doc h4{line-height:1.25;margin:1.4em 0 .5em}
.doc h1{font-size:1.7rem;border-bottom:1px solid #232936;padding-bottom:.3em}
.doc h2{font-size:1.3rem}.doc h3{font-size:1.1rem}
.doc p{margin:.7em 0}.doc ul,.doc ol{margin:.7em 0;padding-left:1.6em}
.doc li{margin:.25em 0}
.doc code{background:#1d2230;padding:.15em .4em;border-radius:4px;
  font:13px ui-monospace,monospace}
.doc pre.code{background:#1d2230;padding:1rem;border-radius:8px;overflow:auto;
  margin:.9em 0;height:auto;width:auto}
.doc pre.code code{background:none;padding:0}
.doc blockquote{border-left:3px solid #384153;margin:.8em 0;padding-left:1rem;color:#9aa3b2}
.doc hr{border:0;border-top:1px solid #232936;margin:1.5em 0}
.doc a{color:#8b95ff}
footer{flex:none;padding:.4rem 1rem;border-top:1px solid #232936;
  font:11px ui-monospace,monospace;color:#5c6474}
@media print{nav,header,footer{display:none}section{position:static;display:none}
  section[data-active=true]{display:block;height:100vh}}
"""

_PACK_JS = """
(function(){
  var tabs=[].slice.call(document.querySelectorAll('nav button'));
  var panes=[].slice.call(document.querySelectorAll('section'));
  function show(i){
    tabs.forEach(function(t,j){t.setAttribute('aria-selected',String(j===i))});
    panes.forEach(function(p,j){p.setAttribute('data-active',String(j===i))});
  }
  tabs.forEach(function(t,i){t.addEventListener('click',function(){show(i)})});
  document.addEventListener('keydown',function(e){
    var cur=tabs.findIndex(function(t){return t.getAttribute('aria-selected')==='true'});
    if(e.key==='ArrowRight'&&cur<tabs.length-1)show(cur+1);
    if(e.key==='ArrowLeft'&&cur>0)show(cur-1);
  });
})();
"""

_PACK_IMAGE = {"png": "image/png", "svg": "image/svg+xml"}


def render_markdown(text: str) -> str:
    """Minimal, XSS-safe markdown → HTML.

    Everything is escaped FIRST, then a small set of block/inline patterns is
    re-introduced as tags. That ordering is the safety property: no markup can
    survive from the source, so hostile markdown can't inject anything. Links are
    additionally restricted to http/https/mailto.

    Deliberately small — the standalone file has no bundler and no network, so a
    real markdown library isn't an option. Unsupported syntax degrades to text.
    """
    import re

    out: list[str] = []
    in_code = False
    in_list: str | None = None

    def inline(s: str) -> str:
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        # Only safe schemes; anything else stays as plain text.
        s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+|mailto:[^\s)]+)\)",
                   r'<a href="\2" rel="noreferrer noopener">\1</a>', s)
        return s

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    for raw in escape(text).split("\n"):
        line = raw.rstrip()
        if line.startswith("```"):
            close_list()
            out.append("</code></pre>" if in_code else '<pre class="code"><code>')
            in_code = not in_code
            continue
        if in_code:
            out.append(raw)
            continue
        if not line.strip():
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue
        if re.match(r"^\s*(---+|\*\*\*+)\s*$", line):
            close_list()
            out.append("<hr>")
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        numbered = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if bullet or numbered:
            want = "ul" if bullet else "ol"
            if in_list != want:
                close_list()
                out.append(f"<{want}>")
                in_list = want
            out.append(f"<li>{inline((bullet or numbered).group(1))}</li>")
            continue
        quote = re.match(r"^&gt;\s?(.*)$", line)
        if quote:
            close_list()
            out.append(f"<blockquote>{inline(quote.group(1))}</blockquote>")
            continue
        close_list()
        out.append(f"<p>{inline(line)}</p>")

    if in_code:
        out.append("</code></pre>")
    close_list()
    return "\n".join(out)


def _pack_pane(art: dict) -> str:
    """One artifact payload → a self-contained pane."""
    name, kind = art["name"], art["type"]
    raw = (base64.b64decode(art["content"]) if art.get("encoding") == "base64"
           else art["content"].encode())

    if kind == "html":
        # No allow-same-origin: artifact script (when allowed at all) gets an
        # opaque origin and can't touch the wrapper document.
        sandbox = "allow-scripts" if art.get("allow_scripts") else ""
        return (f'<iframe title="{escape(name, quote=True)}" sandbox="{sandbox}" '
                f'srcdoc="{escape(raw.decode("utf-8", errors="replace"), quote=True)}"></iframe>')
    if kind in _PACK_IMAGE:
        b64 = base64.b64encode(raw).decode()
        return (f'<div class="img"><img alt="{escape(name, quote=True)}" '
                f'src="data:{_PACK_IMAGE[kind]};base64,{b64}"></div>')
    if kind == "pdf":
        b64 = base64.b64encode(raw).decode()
        return (f'<iframe title="{escape(name, quote=True)}" '
                f'src="data:application/pdf;base64,{b64}"></iframe>')
    if kind == "markdown":
        return f'<div class="doc">{render_markdown(raw.decode("utf-8", errors="replace"))}</div>'
    return f"<pre>{escape(raw.decode('utf-8', errors='replace'))}</pre>"


def build_standalone(title: str, artifacts: list[dict], subtitle: str = "") -> str:
    """Pack artifact payloads into one offline HTML file.

    Opens over file://, makes no network requests, and needs no ArtifactBay — for
    presenting, emailing, or handing work to someone who should never touch your
    instance.
    """
    if not artifacts:
        artifacts = [{"name": "empty", "type": "text", "encoding": "utf8",
                      "content": "Nothing to show."}]
    tabs, panes = [], []
    for i, a in enumerate(artifacts):
        sel = "true" if i == 0 else "false"
        tabs.append(f'<button type="button" aria-selected="{sel}">{escape(a["name"])}</button>')
        panes.append(f'<section data-active="{sel}">{_pack_pane(a)}</section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>{_PACK_CSS}</style>
</head>
<body>
<header><h1>{escape(title)}</h1><span class="meta">{escape(subtitle)}</span></header>
<nav>{"".join(tabs)}</nav>
<main>{"".join(panes)}</main>
<footer>Standalone export — no network required. &#8592; &#8594; to switch artifacts.</footer>
<script>{_PACK_JS}</script>
</body>
</html>
"""


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

    def standalone(self, session_id: str, version: int | None = None) -> bytes:
        """Fetch a stored session as one self-contained HTML file."""
        suffix = f"?download=false&version={version}" if version else "?download=false"
        req = urllib.request.Request(
            f"{self.url}/v0/sessions/{session_id}/standalone{suffix}",
            headers={"Authorization": f"Bearer {self.key}"} if self.key else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
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
