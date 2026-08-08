#!/usr/bin/env python3
"""ArtifactBay MCP server — stdio, stdlib only.

Why this exists: configuration used to be per-project. Every repo needed its own
env exports, its own `.artifactbay/` staging directory, and its own committed
shim telling the agent where and how to push. An MCP server is registered once
per machine at user scope, carries the URL and key in its own environment, and is
then available to every project without any of that.

It also opens the read path. The CLI could only ever write, so ArtifactBay was a
place artifacts went and never came back from. `search_artifacts` and
`get_artifact` let an agent ask what it already built — which is the difference
between an archive and usable memory.

Register once (Claude Code):

    claude mcp add artifactbay --scope user \\
      -e ARTIFACTBAY_URL=https://artifacts.example.com \\
      -e ARTIFACTBAY_KEY=ab_... \\
      -- python3 /path/to/integrations/artifactbay_mcp.py

Or omit the -e flags entirely once `artifactbay init` has written
~/.config/artifactbay/config.json — the server reads the same config the CLI does.

Protocol: JSON-RPC 2.0 over newline-delimited stdio (MCP). Nothing but protocol
messages may go to stdout; diagnostics go to stderr.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifactbay_core import (  # noqa: E402
    ApiError,
    Client,
    collect_paths,
    load_config,
    make_conversation_artifact,
    push,
    redact,
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "artifactbay", "version": "0.2.0"}

ARTIFACT_TYPES = ["html", "markdown", "json", "svg", "png", "pdf", "zip", "text", "conversation"]

TOOLS = [
    {
        "name": "push_artifact",
        "description": (
            "Save an artifact (HTML, markdown, SVG, JSON, text) to ArtifactBay and get a "
            "durable URL back. Pass the content inline — no need to write a file or stage a "
            "directory first. Optionally attach `conversation`: the slice of this chat that "
            "produced the artifact, stored as owner-only provenance so a share link never "
            "exposes it. Re-pushing in the same project creates a new version."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filename, e.g. 'architecture.html'"},
                "type": {"type": "string", "enum": ARTIFACT_TYPES,
                         "description": "Artifact type; infer from the extension if unsure"},
                "content": {"type": "string", "description": "The artifact body, inline"},
                "session_name": {"type": "string",
                                 "description": "Short title for the session, e.g. 'Database redesign'"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "allow_scripts": {
                    "type": "boolean",
                    "description": "Let this HTML run JS in the sandboxed iframe (interactive decks/dashboards). Default false.",
                },
                "conversation": {
                    "type": "array",
                    "description": "Transcript slice that produced this artifact — the last few relevant turns, not the whole session.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
                "session_id": {"type": "string",
                               "description": "Append to a known session instead of the project's cached one"},
            },
            "required": ["name", "type", "content"],
        },
    },
    {
        "name": "push_files",
        "description": (
            "Push existing files or directories from disk to ArtifactBay by path. "
            "Use when the artifact is already written out; use push_artifact for inline content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"},
                          "description": "File or directory paths"},
                "session_name": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["paths"],
        },
    },
    {
        "name": "search_artifacts",
        "description": (
            "Full-text search across everything previously pushed — titles, tags, and the text "
            "extracted from artifact bodies. Use this before building something from scratch to "
            "check whether a past session already produced it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "agent": {"type": "string", "description": "Filter by agent, e.g. 'claude-code'"},
                "tag": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_sessions",
        "description": "List recent sessions, newest first. Use search_artifacts when you have search terms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "tag": {"type": "string"},
                "favorite": {"type": "boolean"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_session",
        "description": "Full detail for one session: metadata, git context, and the artifacts in a version.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "version": {"type": "integer", "description": "Defaults to the current version"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "get_artifact",
        "description": (
            "Fetch one artifact's content by id, so you can read, reuse or build on what a "
            "previous session produced. Binary types return metadata and a URL instead of bytes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"artifact_id": {"type": "string"}},
            "required": ["artifact_id"],
        },
    },
    {
        "name": "share",
        "description": (
            "Mint a capability link so someone without an account can view a session or a single "
            "artifact. Prefer sharing one artifact when that's all the recipient needs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Session id, or artifact id with artifact=true"},
                "artifact": {"type": "boolean", "default": False},
                "rotate": {"type": "boolean", "default": False,
                           "description": "Invalidate the previous link and mint a new one"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "doctor",
        "description": "Check ArtifactBay connectivity, authentication and server capabilities.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

BINARY_TYPES = {"png", "pdf", "zip"}


# ── tool implementations ─────────────────────────────────────────────────────
def _cfg(args: dict) -> dict:
    overrides = {}
    if args.get("tags"):
        overrides["tags"] = args["tags"]
    return load_config(overrides)


def _push_result(result: dict, cfg: dict) -> str:
    if result["ok"]:
        lines = [f"Pushed v{result['version']} → {result['url']}"]
        for a in result.get("artifacts", []):
            lines.append(f"  {a['name']} → {a['url']}")
        return "\n".join(lines)
    if result["reason"] == "no_key":
        return ("No API key configured. Run `artifactbay init`, or set ARTIFACTBAY_KEY "
                "in this MCP server's environment.")
    if result["reason"] == "no_artifacts":
        return "Nothing to push."
    return (f"ArtifactBay unreachable — push queued at {result['queued_at']} and will be sent by "
            f"`artifactbay push --resume`. ({result.get('error')})")


def tool_push_artifact(args: dict) -> str:
    cfg = _cfg(args)
    content, found = (redact(args["content"]) if cfg["redact"] else (args["content"], []))
    artifact = {
        "name": args["name"], "type": args["type"], "encoding": "utf8", "content": content,
    }
    if args.get("allow_scripts") and args["type"] == "html":
        artifact["allow_scripts"] = True

    artifacts = [artifact]
    # The provenance slice. The host already has these messages in memory, so
    # there is nothing to parse out of a vendor's transcript files.
    if args.get("conversation"):
        artifacts.append(make_conversation_artifact(args["conversation"],
                                                    do_redact=cfg["redact"]))

    result = push(cfg, args.get("session_name") or args["name"], artifacts,
                  session_id=args.get("session_id"))
    out = _push_result(result, cfg)
    if found:
        out += f"\n(redacted before upload: {', '.join(sorted(set(found)))})"
    return out


def tool_push_files(args: dict) -> str:
    cfg = _cfg(args)
    artifacts, skipped = collect_paths(args["paths"], cfg["allow_scripts"], cfg["redact"])
    result = push(cfg, args.get("session_name"), artifacts)
    out = _push_result(result, cfg)
    if skipped:
        out += "\nSkipped: " + ", ".join(skipped)
    return out


def _format_sessions(data: dict) -> str:
    sessions = data.get("sessions", [])
    if not sessions:
        return "No matching sessions."
    lines = []
    for s in sessions:
        head = f"{s['id']}  v{s['version']}  {s['name']}"
        meta = f"    {s['agent']} · {s['artifact_count']} artifact(s) · updated {s['updated_at'][:10]}"
        if s.get("tags"):
            meta += f" · tags: {', '.join(s['tags'])}"
        lines.append(head)
        lines.append(meta)
        if s.get("snippet"):
            # Server marks matches with sentinel delimiters, not HTML.
            snippet = s["snippet"].replace("@@HLS@@", "**").replace("@@HLE@@", "**")
            lines.append(f"    …{snippet}…")
    lines.append(f"\n{data.get('total', len(sessions))} total")
    return "\n".join(lines)


def tool_search_artifacts(args: dict) -> str:
    cfg = _cfg(args)
    data = Client(cfg).list_sessions(q=args["query"], agent=args.get("agent"),
                                     tag=args.get("tag"), limit=args.get("limit", 10))
    return _format_sessions(data)


def tool_list_sessions(args: dict) -> str:
    cfg = _cfg(args)
    data = Client(cfg).list_sessions(agent=args.get("agent"), tag=args.get("tag"),
                                     favorite=args.get("favorite"),
                                     limit=args.get("limit", 20))
    return _format_sessions(data)


def tool_get_session(args: dict) -> str:
    cfg = _cfg(args)
    s = Client(cfg).get_session(args["session_id"], args.get("version"))
    lines = [
        f"{s['name']}  (v{s['requested_version']} of {s['version']})",
        f"  agent: {s['agent']}" + (f" · model: {s['model']}" if s.get("model") else ""),
        f"  status: {s['status']} · visibility: {s['visibility']}",
    ]
    if s.get("description"):
        lines.append(f"  {s['description']}")
    git = s.get("git") or {}
    if git.get("repository"):
        lines.append(f"  git: {git['repository']} @ {git.get('branch')} ({(git.get('commit') or '')[:7]})")
    if s.get("tags"):
        lines.append(f"  tags: {', '.join(s['tags'])}")
    lines.append("  artifacts:")
    for a in s.get("artifacts", []):
        flag = " [owner-only]" if a.get("owner_only") else ""
        lines.append(f"    {a['id']}  {a['name']}  ({a['type']}, {a['size_bytes']} bytes){flag}")
    if s.get("share_url"):
        lines.append(f"  share link: {s['share_url']}")
    return "\n".join(lines)


def tool_get_artifact(args: dict) -> str:
    cfg = _cfg(args)
    client = Client(cfg)
    meta = client.artifact_meta(args["artifact_id"])
    header = (f"{meta['name']} ({meta['type']}, {meta['size_bytes']} bytes) "
              f"from session “{meta['session_name']}” v{meta['version']}\n{meta['url']}")
    if meta["type"] in BINARY_TYPES:
        return f"{header}\n\n[binary artifact — fetch the URL above to view it]"
    body = client.artifact_body(args["artifact_id"]).decode("utf-8", errors="replace")
    return f"{header}\n\n{body}"


def tool_share(args: dict) -> str:
    cfg = _cfg(args)
    client = Client(cfg)
    rotate = bool(args.get("rotate"))
    out = (client.share_artifact(args["id"], rotate) if args.get("artifact")
           else client.share_session(args["id"], rotate))
    kind = "artifact" if args.get("artifact") else "session"
    return (f"Capability link for this {kind} (anyone with it can view; no account needed):\n"
            f"{out['url']}")


def tool_doctor(args: dict) -> str:
    cfg = _cfg(args)
    client = Client(cfg)
    lines = [f"ArtifactBay: {cfg['url']}"]
    try:
        meta = client.meta()
        lines.append(f"  reachable — api v{meta.get('version')}")
        caps = meta.get("capabilities")
        lines.append(f"  capabilities: {', '.join(caps)}" if caps
                     else "  older instance: incremental push/export unavailable")
    except Exception as e:  # noqa: BLE001
        return f"{lines[0]}\n  UNREACHABLE — {e}"
    if not cfg["key"]:
        lines.append("  no API key — run `artifactbay init` or set ARTIFACTBAY_KEY")
        return "\n".join(lines)
    try:
        client.check()
        lines.append("  key valid (write scope)")
    except ApiError as e:
        lines.append(f"  key rejected ({e.status})")
    return "\n".join(lines)


HANDLERS = {
    "push_artifact": tool_push_artifact,
    "push_files": tool_push_files,
    "search_artifacts": tool_search_artifacts,
    "list_sessions": tool_list_sessions,
    "get_session": tool_get_session,
    "get_artifact": tool_get_artifact,
    "share": tool_share,
    "doctor": tool_doctor,
}


# ── JSON-RPC plumbing ────────────────────────────────────────────────────────
def _result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(body: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": body}], "isError": is_error}


def handle(message: dict) -> dict | None:
    """Route one JSON-RPC message. None = notification, nothing to send back."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })

    # Notifications carry no id and expect no response.
    if request_id is None:
        return None

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _result(request_id, _text(f"Unknown tool: {name}", is_error=True))
        try:
            return _result(request_id, _text(handler(params.get("arguments") or {})))
        except ApiError as e:
            return _result(request_id, _text(f"ArtifactBay error: {e}", is_error=True))
        except Exception as e:  # noqa: BLE001 — a tool failure must not kill the server
            traceback.print_exc(file=sys.stderr)
            return _result(request_id, _text(f"{type(e).__name__}: {e}", is_error=True))

    if method == "ping":
        return _result(request_id, {})

    return _error(request_id, -32601, f"Method not found: {method}")


def serve() -> int:
    """Read newline-delimited JSON-RPC from stdin until EOF."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps(_error(None, -32700, "Parse error")), flush=True)
            continue
        response = handle(message)
        if response is not None:
            print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(serve())
