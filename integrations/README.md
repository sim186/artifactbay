# ArtifactBay Agent Integrations

How AI agents talk to ArtifactBay. Protocol spec: `../docs/02-agent-integration-protocol.md`.

There are two front ends over one engine (`artifactbay_core.py`):

| | Use it when | Configured |
|---|---|---|
| **MCP server** (`artifactbay_mcp.py`) | the agent speaks MCP (Claude Code, Codex, Cursor, …) | **once per machine** |
| **CLI** (`artifactbay_cli.py`) | hooks, CI, shell, agents without MCP | once per machine |

**Prefer MCP.** It is registered at user scope, carries the URL and key in its own
environment, and is then available to every project — which is the whole answer to
"I have to tell every project where and how to push". It also exposes the *read* path
(`search_artifacts`, `get_artifact`), so an agent can find what a past session already
built instead of rebuilding it.

## One-time setup

The installer does all three steps below — copies the engine to
`~/.local/share/artifactbay`, links `artifactbay` onto PATH, writes the config, and
registers the MCP server with Claude Code:

```bash
curl -fsSL https://raw.githubusercontent.com/sim186/artifactbay/main/install.sh | \
  sh -s -- --client-only --url https://artifacts.example.com --key ab_...
```

By hand, from a checkout:

```bash
# 1. Machine-wide config — every project inherits it, none needs its own.
python3 artifactbay_cli.py init --url https://artifacts.example.com --key ab_...
#    → writes ~/.config/artifactbay/config.json (chmod 600)

# 2. Put `artifactbay` on PATH (optional but handy)
ln -s "$PWD/artifactbay" /usr/local/bin/artifactbay

# 3. Register the MCP server with your agent (see table below)
```

Configuration resolves environment → `./.artifactbay/config.json` →
`~/.config/artifactbay/config.json`, so a single project can still override the defaults
without touching anything else.

## MCP server

Stdlib-only stdio server — no `pip install`, no virtualenv.

```bash
# Claude Code (user scope: available in every project)
claude mcp add artifactbay --scope user -- python3 /path/to/integrations/artifactbay_mcp.py

# Codex CLI — ~/.codex/config.toml
[mcp_servers.artifactbay]
command = "python3"
args = ["/path/to/integrations/artifactbay_mcp.py"]

# Cursor / Windsurf / generic — ~/.cursor/mcp.json
{ "mcpServers": { "artifactbay": {
    "command": "python3", "args": ["/path/to/integrations/artifactbay_mcp.py"] } } }
```

Credentials come from the config file written by `init`. To override per server, add an
`env` block (`ARTIFACTBAY_URL`, `ARTIFACTBAY_KEY`).

### Tools

| Tool | What it does |
|---|---|
| `push_artifact` | Save inline content; optionally attach a `conversation` slice |
| `push_files` | Save existing files/directories by path |
| `search_artifacts` | Full-text search over titles, tags and extracted artifact text |
| `list_sessions` / `get_session` | Browse history |
| `get_artifact` | Read a past artifact's content back |
| `share` | Mint a capability link for a session or a single artifact |
| `pack_standalone` | Build one self-contained HTML file — opens offline, no ArtifactBay needed |
| `doctor` | Connectivity, auth and server capabilities |

## CLI

```bash
artifactbay init                              # machine-wide config (once)
artifactbay doctor                            # connectivity + auth + staged artifacts
artifactbay push report.html diagram.svg      # push files BY PATH — no staging dir
artifactbay push --name "Ledger redesign"     # or push whatever is staged
artifactbay ls -q ledger                      # search past sessions
artifactbay share <session-id>                # capability link (--artifact for one file)
artifactbay pack <session-id> -o out.html     # self-contained file — no server to view it
artifactbay pack --local a.html b.svg -o deck.html   # …packed with no instance involved
artifactbay push --resume                     # flush queued (offline) pushes
artifactbay mcp                               # run the MCP server on stdio
```

- Explicit paths win; with none it reads `.artifactbay/artifacts/`
  (`ARTIFACTBAY_ARTIFACTS_DIR` to change).
- **Interactive HTML** (slide decks, dashboards): opt in to JS with
  `ARTIFACTBAY_ALLOW_SCRIPTS="deck.html,*.slides.html"` (comma globs). Matching HTML gets
  `allow_scripts=true` so it runs in the sandboxed iframe. Default: scripts off.
- Reads git repo/branch/commit automatically.
- Remembers the session in `.artifactbay/session_id` → re-push = new **version**.
  (Different server / reset DB? The cached id won't exist there — the client detects the
  404 and creates a fresh session.)
- **Idempotent** (Idempotency-Key) and **fail-open** (never crashes the agent; queues to
  `.artifactbay/pending/`).

## Presenting without ArtifactBay

A capability link points at a running instance. `pack` instead produces **one
self-contained HTML file**: artifacts inlined (HTML into sandboxed `srcdoc`, images and
PDFs as `data:` URIs), a tab bar and arrow-key navigation, and no network requests when
opened. Open it over `file://`, email it, or drop it on any static host.

Two modes, because "share without ArtifactBay" means two things:

- `pack <session-id>` — pull a stored session down into a single file.
- `pack --local FILES` — package files that were never pushed anywhere. No server is
  contacted, so this works with no instance at all.

Artifact HTML stays sandboxed inside the packed file (no `allow-same-origin`; scripts
only where `allow_scripts` was set). Owner-only transcripts are included when you pack
your own session, and excluded when the pack comes from a share link.

## Conversation slices

Both front ends can attach the transcript excerpt that produced an artifact. That slice is:

- **scoped** — the few relevant turns, not a full session archive;
- **owner-only** — withheld from every capability link and public view, so sharing the
  work never ships the conversation behind it;
- **trimmed server-side** — capped at `ARTIFACTBAY_MAX_CONVERSATION_BYTES` (512 KB) and
  200 messages, newest kept;
- **redacted client-side** — credential-shaped strings are stripped before upload.

Storing *every* conversation from every agent is a deliberate non-goal: it has different
scale, retention and privacy needs than artifacts, and the blob layer is content-addressed
on whole bodies, which suits documents and not append-only logs.

## Trigger model

- **Default = explicit.** Push when the user asks. Universal across agents.
- **Opt-in = automatic.** A Stop hook auto-pushes on session end (Claude Code) — see
  `claude-code/stop-hook.md`.

## Per-agent shims

| Agent | Folder | Preferred | Fallback |
|-------|--------|-----------|----------|
| Claude Code | `claude-code/` | MCP server | Skill `/artifactbay-push` + optional Stop hook |
| Codex | `codex/` | MCP server | `AGENTS.md` instruction → `artifactbay push` |
| Cursor | `cursor/` | MCP server | `.cursor/rules` + VS Code task |
| OpenCode | `opencode/` | MCP server | `/artifactbay` command |
| Aider | `aider/` | — | git `post-commit` hook (auto-push on commit) |

Each shim sets `ARTIFACTBAY_AGENT=<name>` so sessions show the right agent badge.

`claude-code/artifactbay-push/` bundles copies of the three engine files so the skill is
self-contained; keep them in sync with this directory when editing.

## Security

- The API key lives in `~/.config/artifactbay/config.json` (chmod 600) or the
  environment. Never commit it.
- Only the files you name (or those under `.artifactbay/artifacts/`) plus git metadata
  strings are sent — no repo-wide slurp.
- Credential-shaped strings (AWS/GitHub/Slack/OpenAI/Anthropic keys, JWTs, private keys,
  `*_SECRET=` assignments) are redacted client-side before upload. Defence in depth, not
  a licence to push secrets. `--no-redact` disables it.
- HTML is stored as-is; the **server** sandboxes it on render (iframe + CSP), not the agent.
