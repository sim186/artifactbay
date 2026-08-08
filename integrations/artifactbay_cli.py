#!/usr/bin/env python3
"""ArtifactBay push CLI (FAIP v0, see docs/02).

Stdlib only: no pip install, drops into any agent's shell. The engine lives in
`artifactbay_core.py` beside this file and is shared with the MCP server.

  init                    write machine-wide config (~/.config/artifactbay/config.json)
  doctor                  check connectivity + auth + what would be pushed
  push  [PATH ...]        push files/dirs directly, or the staged artifacts dir
        [--name NAME]     session title
        [--resume]        retry any queued pushes in .artifactbay/pending/
        [--dry-run]       print the payload, don't send
        [--no-redact]     skip client-side secret stripping (not recommended)
  pack  [SESSION_ID|FILES] build ONE self-contained HTML file — opens offline,
        [--local]          needs no ArtifactBay to view. For presenting.
  share SESSION_ID        mint a capability link for a session
  ls    [-q QUERY]        list recent sessions
  mcp                     run the MCP server on stdio (see artifactbay_mcp.py)

Config resolution: env vars → ./.artifactbay/config.json → ~/.config/artifactbay/config.json.
Run `artifactbay init` once per machine and projects need no setup of their own.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifactbay_core import (  # noqa: E402
    USER_CONFIG,
    ApiError,
    Client,
    build_standalone,
    collect_artifacts,
    collect_paths,
    load_config,
    push,
    send,
    write_user_config,
)

C_OK, C_ERR, C_DIM, C_RST = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def cmd_init(args: argparse.Namespace) -> int:
    """Write the machine-wide config once, so no project needs its own."""
    url = args.url or input(f"ArtifactBay URL [{'http://localhost:8080'}]: ").strip() \
        or "http://localhost:8080"
    key = args.key or input("Write API key (ab_...): ").strip()
    if not key:
        print(f"{C_ERR}a write key is required{C_RST} — create one in Settings → API keys")
        return 1

    cfg = load_config({"url": url, "key": key})
    try:
        Client(cfg).check()
    except ApiError as e:
        print(f"{C_ERR}✗ key rejected by {url}{C_RST} ({e.status})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"{C_ERR}✗ cannot reach {url}{C_RST} — {e}")
        return 1

    path = write_user_config(url, key, agent=args.agent)
    print(f"{C_OK}✓{C_RST} wrote {path}")
    print(f"{C_DIM}  every project on this machine can now push — no per-project setup{C_RST}")
    return 0


def cmd_doctor(cfg: dict) -> int:
    client = Client(cfg)
    print(f"ArtifactBay: {cfg['url']}")
    print(f"{C_DIM}  config: {USER_CONFIG if USER_CONFIG.is_file() else 'env only'}{C_RST}")
    try:
        meta = client.meta()
        print(f"  {C_OK}✓{C_RST} reachable (api v{meta.get('version')})")
        caps = meta.get("capabilities") or []
        if caps:
            print(f"{C_DIM}      capabilities: {', '.join(caps)}{C_RST}")
        else:
            print(f"{C_DIM}      older instance — incremental push/export unavailable{C_RST}")
    except Exception as e:  # noqa: BLE001
        print(f"  {C_ERR}✗ unreachable{C_RST} — {e}")
        return 1

    if not cfg["key"]:
        print(f"  {C_ERR}✗ no API key{C_RST} — run `artifactbay init`")
        return 1
    try:
        client.check()
        print(f"  {C_OK}✓{C_RST} key valid (write)")
    except ApiError as e:
        print(f"  {C_ERR}✗ key rejected{C_RST} ({e.status})")
        return 1

    arts = collect_artifacts(cfg["artifacts_dir"], cfg["allow_scripts"], cfg["redact"])
    print(f"  {C_OK}✓{C_RST} {len(arts)} artifact(s) staged in {cfg['artifacts_dir']}/")
    for a in arts:
        print(f"      {C_DIM}{a['type']:<12} {a['name']}{C_RST}")
    pending_dir = cfg["state_dir"] / "pending"
    pending = list(pending_dir.glob("*.json")) if pending_dir.is_dir() else []
    if pending:
        print(f"  {C_DIM}{len(pending)} queued push(es) — run `artifactbay push --resume`{C_RST}")
    return 0


def cmd_push(cfg: dict, args: argparse.Namespace) -> int:
    if args.resume:
        pending_dir = cfg["state_dir"] / "pending"
        files = sorted(pending_dir.glob("*.json")) if pending_dir.is_dir() else []
        if not files:
            print("nothing pending")
            return 0
        ok = 0
        for f in files:
            d = json.loads(f.read_text())
            try:
                out = send(cfg, d["payload"], d["idem"])
                f.unlink()
                ok += 1
                print(f"{C_OK}✓{C_RST} resumed → {out.get('url')}")
            except Exception as e:  # noqa: BLE001
                print(f"{C_ERR}✗ still failing{C_RST} {f.name} — {e}")
        return 0 if ok == len(files) else 1

    # Explicit paths win; otherwise fall back to the staged directory.
    if args.paths:
        artifacts, skipped = collect_paths(args.paths, cfg["allow_scripts"], cfg["redact"])
        for s in skipped:
            print(f"{C_DIM}skipped {s}{C_RST}")
    else:
        artifacts = collect_artifacts(cfg["artifacts_dir"], cfg["allow_scripts"], cfg["redact"])

    if not artifacts:
        where = " ".join(args.paths) if args.paths else f"{cfg['artifacts_dir']}/"
        print(f"{C_DIM}nothing to push from {where}{C_RST}")
        return 0

    if args.dry_run:
        preview = {
            "name": args.name, "agent": cfg["agent"], "tags": cfg["tags"],
            "artifacts": [{**a, "content": f"<{len(a['content'])} chars>"} for a in artifacts],
        }
        print(json.dumps(preview, indent=2))
        return 0

    result = push(cfg, args.name, artifacts)
    if result["ok"]:
        print(f"{C_OK}✓ pushed{C_RST} v{result['version']} → {result['url']}")
        return 0
    if result["reason"] == "no_key":
        print(f"{C_ERR}no API key{C_RST} — run `artifactbay init`")
        return 1
    # Queued: exit 0 on purpose so a failed push never breaks the agent's run.
    print(f"{C_ERR}✗ push failed{C_RST} — queued {result['queued_at']} "
          f"(retry: artifactbay push --resume)\n  {result.get('error')}")
    return 0


def cmd_pack(cfg: dict, args: argparse.Namespace) -> int:
    """Build one self-contained HTML file — for presenting, with no server needed.

    Two modes, because "share without ArtifactBay" means two different things:
      pack <session-id>        pull a stored session down into a single file
      pack --local a.html b.svg   package local files with no instance involved
    """
    if args.local or not args.target:
        paths = ([args.target] if args.target else []) + args.paths
        if not paths:
            print(f"{C_ERR}nothing to pack{C_RST} — pass files, or a session id without --local")
            return 1
        artifacts, skipped = collect_paths(paths, cfg["allow_scripts"], cfg["redact"])
        for s in skipped:
            print(f"{C_DIM}skipped {s}{C_RST}")
        if not artifacts:
            print(f"{C_ERR}no packable files{C_RST}")
            return 1
        title = args.title or (Path(paths[0]).stem if len(artifacts) == 1 else Path.cwd().name)
        html = build_standalone(title, artifacts,
                                subtitle=f"{len(artifacts)} artifact(s)").encode()
        out = Path(args.output or f"{title}.html")
    else:
        try:
            html = Client(cfg).standalone(args.target, args.version)
        except ApiError as e:
            print(f"{C_ERR}✗ {e}{C_RST}")
            return 1
        out = Path(args.output or f"{args.target[:8]}.html")

    out.write_bytes(html)
    size = len(html) / 1024
    print(f"{C_OK}✓ packed{C_RST} {out} ({size:.0f} KB)")
    print(f"{C_DIM}  self-contained — open it directly, email it, or drop it on any static host{C_RST}")
    return 0


def cmd_share(cfg: dict, args: argparse.Namespace) -> int:
    try:
        if args.artifact:
            out = Client(cfg).share_artifact(args.id, rotate=args.rotate)
        else:
            out = Client(cfg).share_session(args.id, rotate=args.rotate)
    except ApiError as e:
        print(f"{C_ERR}✗ {e}{C_RST}")
        return 1
    print(out["url"])
    return 0


def cmd_ls(cfg: dict, args: argparse.Namespace) -> int:
    try:
        out = Client(cfg).list_sessions(q=args.q, limit=args.limit)
    except ApiError as e:
        print(f"{C_ERR}✗ {e}{C_RST}")
        return 1
    for s in out.get("sessions", []):
        tags = f" {C_DIM}[{','.join(s['tags'])}]{C_RST}" if s.get("tags") else ""
        print(f"{s['id'][:8]}  v{s['version']:<3} {s['name'][:52]:<52} "
              f"{C_DIM}{s['artifact_count']} artifact(s){C_RST}{tags}")
    print(f"{C_DIM}{out.get('total', 0)} total{C_RST}")
    return 0


def cmd_mcp() -> int:
    import artifactbay_mcp

    return artifactbay_mcp.serve()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="artifactbay")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="write machine-wide config")
    p_init.add_argument("--url")
    p_init.add_argument("--key")
    p_init.add_argument("--agent")

    sub.add_parser("doctor", help="check connectivity, auth and staged artifacts")

    p_push = sub.add_parser("push", help="push artifacts")
    p_push.add_argument("paths", nargs="*", help="files or directories (default: staged dir)")
    p_push.add_argument("--name")
    p_push.add_argument("--dry-run", action="store_true")
    p_push.add_argument("--resume", action="store_true")
    p_push.add_argument("--no-redact", action="store_true",
                        help="skip client-side secret stripping")

    p_pack = sub.add_parser(
        "pack", help="build a self-contained HTML file (no server needed to view it)")
    p_pack.add_argument("target", nargs="?",
                        help="session id to pack, or a file path when --local")
    p_pack.add_argument("paths", nargs="*", help="extra files (implies --local)")
    p_pack.add_argument("--local", action="store_true",
                        help="pack local files without contacting ArtifactBay at all")
    p_pack.add_argument("-o", "--output", help="output file (default: <title>.html)")
    p_pack.add_argument("--title")
    p_pack.add_argument("--version", type=int, help="session version to pack")

    p_share = sub.add_parser("share", help="mint a capability link")
    p_share.add_argument("id")
    p_share.add_argument("--artifact", action="store_true", help="share one artifact, not a session")
    p_share.add_argument("--rotate", action="store_true")

    p_ls = sub.add_parser("ls", help="list sessions")
    p_ls.add_argument("-q", help="search query")
    p_ls.add_argument("--limit", type=int, default=20)

    sub.add_parser("mcp", help="run the MCP server on stdio")

    a = p.parse_args(argv)
    if a.cmd == "init":
        return cmd_init(a)
    if a.cmd == "mcp":
        return cmd_mcp()

    cfg = load_config()
    if getattr(a, "no_redact", False):
        cfg["redact"] = False

    if a.cmd == "doctor":
        return cmd_doctor(cfg)
    if a.cmd == "push":
        return cmd_push(cfg, a)
    if a.cmd == "pack":
        return cmd_pack(cfg, a)
    if a.cmd == "share":
        return cmd_share(cfg, a)
    if a.cmd == "ls":
        return cmd_ls(cfg, a)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
