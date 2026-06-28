#!/usr/bin/env python3
"""Foundry push CLI — the agent integration engine (FAIP v0, see docs/02).

Stdlib only: no pip install, drops into any agent's shell. Subcommands:

  doctor                 check connectivity + auth + what would be pushed
  push   [--name NAME]    package .foundry/artifacts + git context, POST to Foundry
         [--resume]       retry any queued pushes in .foundry/pending/
         [--dry-run]      print the payload, don't send

Config (env):
  FOUNDRY_URL            default http://localhost:8080
  FOUNDRY_KEY            write API key (required to push)
  FOUNDRY_ARTIFACTS_DIR  default .foundry/artifacts
  FOUNDRY_PROJECT        optional project name

Design: idempotent (Idempotency-Key), fail-open (never crash the agent),
versions automatically (remembers .foundry/session_id).
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

EXT_TYPE = {
    ".html": "html", ".htm": "html", ".md": "markdown", ".markdown": "markdown",
    ".json": "json", ".svg": "svg", ".png": "png", ".pdf": "pdf",
    ".zip": "zip", ".txt": "text", ".log": "text",
}
BINARY = {"png", "pdf", "zip"}

C_OK, C_ERR, C_DIM, C_RST = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def cfg() -> dict:
    return {
        "url": os.environ.get("FOUNDRY_URL", "http://localhost:8080").rstrip("/"),
        "key": os.environ.get("FOUNDRY_KEY", ""),
        "artifacts_dir": Path(os.environ.get("FOUNDRY_ARTIFACTS_DIR", ".foundry/artifacts")),
        "project": os.environ.get("FOUNDRY_PROJECT") or None,
        "state_dir": Path(".foundry"),
    }


def _req(method: str, url: str, key: str = "", body: bytes | None = None,
         idem: str | None = None, timeout: int = 15):
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    if idem:
        headers["Idempotency-Key"] = idem
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def git_context() -> dict:
    return {
        "repository": git("config", "--get", "remote.origin.url"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "HEAD"),
    }


def collect_artifacts(d: Path) -> list[dict]:
    arts: list[dict] = []
    if not d.is_dir():
        return arts
    # Opt-in: HTML files matching any glob in FOUNDRY_ALLOW_SCRIPTS get allow_scripts=true
    # (needed for interactive artifacts like slide decks). Default: scripts disabled.
    allow_globs = [g.strip() for g in os.environ.get("FOUNDRY_ALLOW_SCRIPTS", "").split(",") if g.strip()]
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        t = EXT_TYPE.get(p.suffix.lower())
        if t is None:
            continue  # skip unknown types — don't guess
        # Convention: conversation.json / *.conversation.json → transcript artifact.
        if p.name == "conversation.json" or p.name.endswith(".conversation.json"):
            t = "conversation"
        raw = p.read_bytes()
        if t in BINARY:
            content, enc = base64.b64encode(raw).decode(), "base64"
        else:
            content, enc = raw.decode("utf-8", errors="replace"), "utf8"
        art = {"name": p.name, "type": t, "encoding": enc, "content": content}
        if t == "html" and any(fnmatch.fnmatch(p.name, g) for g in allow_globs):
            art["allow_scripts"] = True
        arts.append(art)
    return arts


def build_payload(c: dict, name: str | None) -> dict:
    arts = collect_artifacts(c["artifacts_dir"])
    g = git_context()
    repo = g["repository"] or ""
    default_name = name or git("log", "-1", "--pretty=%s") or Path.cwd().name
    return {
        "name": default_name,
        "agent": os.environ.get("FOUNDRY_AGENT", "claude-code"),
        "model": os.environ.get("FOUNDRY_MODEL"),
        "project": c["project"] or (Path(repo).stem or None if repo else None),
        "git": g,
        "tags": [t for t in os.environ.get("FOUNDRY_TAGS", "").split(",") if t],
        "artifacts": arts,
    }


# ── commands ────────────────────────────────────────────────────────────────
def cmd_doctor(c: dict) -> int:
    print(f"Foundry: {c['url']}")
    try:
        _, meta = _req("GET", f"{c['url']}/v0/meta")
        print(f"  {C_OK}✓{C_RST} reachable (api v{meta.get('version')})")
    except Exception as e:  # noqa: BLE001
        print(f"  {C_ERR}✗ unreachable{C_RST} — {e}")
        return 1
    if not c["key"]:
        print(f"  {C_ERR}✗ FOUNDRY_KEY not set{C_RST}")
        return 1
    try:
        _req("GET", f"{c['url']}/v0/auth/check", key=c["key"])
        print(f"  {C_OK}✓{C_RST} key valid (write)")
    except urllib.error.HTTPError as e:
        print(f"  {C_ERR}✗ key rejected{C_RST} ({e.code})")
        return 1
    arts = collect_artifacts(c["artifacts_dir"])
    print(f"  {C_OK}✓{C_RST} {len(arts)} artifact(s) in {c['artifacts_dir']}/")
    for a in arts:
        print(f"      {C_DIM}{a['type']:<8} {a['name']}{C_RST}")
    pend = list((c["state_dir"] / "pending").glob("*.json")) if (c["state_dir"] / "pending").is_dir() else []
    if pend:
        print(f"  {C_DIM}{len(pend)} queued push(es) pending — run `push --resume`{C_RST}")
    return 0


def _send(c: dict, payload: dict, idem: str) -> dict:
    sid_file = c["state_dir"] / "session_id"
    body = json.dumps(payload).encode()
    if sid_file.is_file():  # known session → new version
        sid = sid_file.read_text().strip()
        _, out = _req("POST", f"{c['url']}/v0/sessions/{sid}/versions", key=c["key"], body=body)
    else:  # first push → create
        _, out = _req("POST", f"{c['url']}/v0/sessions", key=c["key"], body=body, idem=idem)
        c["state_dir"].mkdir(exist_ok=True)
        sid_file.write_text(out["id"])
    return out


def _queue(c: dict, payload: dict, idem: str) -> Path:
    pend = c["state_dir"] / "pending"
    pend.mkdir(parents=True, exist_ok=True)
    f = pend / f"{idem}.json"
    f.write_text(json.dumps({"idem": idem, "payload": payload}))
    return f


def cmd_push(c: dict, name: str | None, dry: bool, resume: bool) -> int:
    if resume:
        pend = c["state_dir"] / "pending"
        files = sorted(pend.glob("*.json")) if pend.is_dir() else []
        if not files:
            print("nothing pending")
            return 0
        ok = 0
        for f in files:
            d = json.loads(f.read_text())
            try:
                out = _send(c, d["payload"], d["idem"])
                f.unlink()
                ok += 1
                print(f"{C_OK}✓{C_RST} resumed → {out.get('url')}")
            except Exception as e:  # noqa: BLE001
                print(f"{C_ERR}✗ still failing{C_RST} {f.name} — {e}")
        return 0 if ok == len(files) else 1

    payload = build_payload(c, name)
    if not payload["artifacts"]:
        print(f"{C_DIM}no artifacts in {c['artifacts_dir']}/ — nothing to push{C_RST}")
        return 0
    if dry:
        preview = {**payload, "artifacts": [{**a, "content": f"<{len(a['content'])} chars>"}
                                            for a in payload["artifacts"]]}
        print(json.dumps(preview, indent=2))
        return 0
    if not c["key"]:
        print(f"{C_ERR}FOUNDRY_KEY not set{C_RST} — run `doctor`")
        return 1

    idem = uuid.uuid4().hex
    try:
        out = _send(c, payload, idem)
        print(f"{C_OK}✓ pushed{C_RST} → {out.get('url')}")
        return 0
    except Exception as e:  # noqa: BLE001  — fail-open: queue, never crash the agent
        f = _queue(c, payload, idem)
        print(f"{C_ERR}✗ push failed{C_RST} — queued {f} (retry: push --resume)\n  {e}")
        return 0  # exit 0 on purpose: must not break the agent's run


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="foundry")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    pp = sub.add_parser("push")
    pp.add_argument("--name")
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--resume", action="store_true")
    a = p.parse_args(argv)
    c = cfg()
    if a.cmd == "doctor":
        return cmd_doctor(c)
    return cmd_push(c, a.name, a.dry_run, a.resume)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
