---
name: artifactbay-push
description: Push the current AI session's artifacts to ArtifactBay (the session artifact repository) and return a shareable URL. Use when the user says "save to artifactbay", "push this session", "/artifactbay-push", or wants to archive generated HTML/markdown artifacts. Captures files from .artifactbay/artifacts/ plus git context.
---

# ArtifactBay Push

Save the current session's artifacts to ArtifactBay and give the user a URL.

## When to use
- User asks to "save", "push", or "archive" the session to ArtifactBay.
- You've produced HTML/markdown/SVG artifacts worth keeping.

This is **explicit** by default — push when asked, not on every turn.

## How it works
The engine is a stdlib-only Python CLI (`artifactbay_cli.py`) bundled **in this skill's
directory** (next to this SKILL.md) — no install needed. It collects artifacts from
`.artifactbay/artifacts/`, reads git context, and POSTs to ArtifactBay. Re-pushing the same
checkout creates a new **version** automatically (it remembers the session id in
`.artifactbay/session_id`).

First, set `CLI` to the bundled script's absolute path (it sits beside this SKILL.md):
```bash
CLI="$CLAUDE_PLUGIN_ROOT/artifactbay_cli.py"   # or the absolute path to artifactbay_cli.py in this skill dir
```

## Steps

1. **Make sure artifacts exist.** Put anything worth saving in `.artifactbay/artifacts/`:
   ```bash
   mkdir -p .artifactbay/artifacts
   # e.g. write your generated report there
   # cp report.html .artifactbay/artifacts/
   ```
   Supported: `.html .md .json .svg .png .pdf .zip .txt`.

2. **Preflight (optional but recommended).** Confirms connectivity, auth, and what will be sent:
   ```bash
   python3 "$CLI" doctor
   ```

3. **Push.**
   ```bash
   python3 "$CLI" push --name "Short session title"
   ```
   On success it prints `✓ pushed → <url>`. **Show that URL to the user.**

4. **If it failed** (ArtifactBay unreachable), the push is queued and the command still
   exits 0 (it must never block your work). Retry later with:
   ```bash
   python3 "$CLI" push --resume
   ```

## Config (env)
- `ARTIFACTBAY_URL` — ArtifactBay base URL (default `http://localhost:8080`)
- `ARTIFACTBAY_KEY` — write API key (**required**; never hardcode/commit it)
- `ARTIFACTBAY_PROJECT`, `ARTIFACTBAY_TAGS` (comma-sep), `ARTIFACTBAY_MODEL` — optional metadata

## Rules
- Never put `ARTIFACTBAY_KEY` in a committed file — use the environment.
- Don't push secrets. Only files under `.artifactbay/artifacts/` are sent (plus git repo/branch/commit strings).
- Don't auto-push unless the user opted into the Stop hook (see `../stop-hook.md`).
