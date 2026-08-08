---
name: artifactbay-push
description: Push the current AI session's artifacts to ArtifactBay (the session artifact repository) and return a shareable URL, or search what past sessions already produced. Use when the user says "save to artifactbay", "push this session", "/artifactbay-push", wants to archive generated HTML/markdown artifacts, or asks whether something was built before.
---

# ArtifactBay Push

Save this session's artifacts to ArtifactBay and give the user a URL — or look up what
earlier sessions already built.

## Prefer the MCP server

If the `artifactbay` MCP server is configured, **use its tools directly** and ignore the
CLI section below. It needs no staging directory, no environment variables in this
project, and no file writing:

| Tool | Use for |
|---|---|
| `push_artifact` | Save inline content (HTML, markdown, SVG…) and get a URL |
| `push_files` | Save files that already exist on disk, by path |
| `search_artifacts` | Full-text search over everything pushed before |
| `get_artifact` | Read back a past artifact's content |
| `get_session` / `list_sessions` | Browse history |
| `share` | Mint a view link for a session or a single artifact |
| `pack_standalone` | Build one self-contained HTML file that opens offline (for presenting) |

Set it up once per machine (not per project):

```bash
claude mcp add artifactbay --scope user -- python3 /path/to/integrations/artifactbay_mcp.py
```

With `artifactbay init` already run, the server picks up the URL and key from
`~/.config/artifactbay/config.json` — no `-e` flags needed.

### Attaching the conversation

`push_artifact` takes an optional `conversation` array: the slice of this chat that
produced the artifact. Include it when the reasoning matters — a few relevant turns,
not the whole session. It is stored as **owner-only** provenance, so it never travels
with a share link. Redaction runs before upload, but still don't deliberately include
secrets.

## Fallback: the CLI

Use this only when the MCP server isn't available.

```bash
CLI="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/artifactbay-push}/artifactbay_cli.py"
```

1. **One-time setup** (per machine, not per project):
   ```bash
   python3 "$CLI" init --url https://artifacts.example.com --key ab_...
   ```
   This writes `~/.config/artifactbay/config.json`, so every project on this machine
   can push with no local configuration.

2. **Push.** Pass paths directly — no staging directory needed:
   ```bash
   python3 "$CLI" push report.html diagram.svg --name "Short session title"
   ```
   With no paths it falls back to whatever is in `.artifactbay/artifacts/`.
   On success it prints `✓ pushed v<N> → <url>`. **Show that URL to the user.**

3. **Other commands:**
   ```bash
   python3 "$CLI" doctor            # connectivity, auth, server capabilities
   python3 "$CLI" ls -q "ledger"    # search past sessions
   python3 "$CLI" share <id>        # mint a view link (--artifact for one file)
   python3 "$CLI" push --resume     # flush pushes queued while the server was down
   python3 "$CLI" pack <id> -o out.html          # self-contained file, viewable offline
   python3 "$CLI" pack --local a.html b.svg -o deck.html   # …with no server at all
   ```

### Presenting

When the user wants to *show* something — a demo, a review, a deck — prefer
`pack_standalone` over a share link. It produces one HTML file that opens with no
network, no account and no ArtifactBay, so it survives conference-room wifi and email.

Supported types: `.html .md .json .svg .png .pdf .zip .txt`.

## Config

Resolution order: environment → `./.artifactbay/config.json` → `~/.config/artifactbay/config.json`.

- `ARTIFACTBAY_URL` — base URL (default `http://localhost:8080`). TLS must be valid;
  there is no insecure/skip-verify flag.
- `ARTIFACTBAY_KEY` — write API key (**never** hardcode or commit it)
- `ARTIFACTBAY_PROJECT`, `ARTIFACTBAY_TAGS`, `ARTIFACTBAY_MODEL` — optional metadata

## Rules

- Never put the API key in a committed file — use `init` or the environment.
- Only the files you name (or those under `.artifactbay/artifacts/`) are sent, plus git
  repo/branch/commit strings. Nothing scans the repo.
- Credential-shaped strings are stripped client-side before upload, but that's a safety
  net, not a licence to push secrets.
- Don't auto-push unless the user opted into the Stop hook (see `../stop-hook.md`).

## Notes

- Re-pushing in the same project creates a new **version** (the session id is cached in
  `.artifactbay/session_id`). Delete that file to start a fresh session.
- Pointing at a different server, or one whose DB was reset, makes the cached id 404;
  the client detects that and creates a new session rather than failing.
- If ArtifactBay is unreachable the push is queued to `.artifactbay/pending/` and the
  command still succeeds — it must never block your work.
