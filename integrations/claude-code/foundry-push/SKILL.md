---
name: foundry-push
description: Push the current AI session's artifacts to Foundry (the session artifact repository) and return a shareable URL. Use when the user says "save to foundry", "push this session", "/foundry-push", or wants to archive generated HTML/markdown artifacts. Captures files from .foundry/artifacts/ plus git context.
---

# Foundry Push

Save the current session's artifacts to Foundry and give the user a URL.

## When to use
- User asks to "save", "push", or "archive" the session to Foundry.
- You've produced HTML/markdown/SVG artifacts worth keeping.

This is **explicit** by default — push when asked, not on every turn.

## How it works
The engine is a stdlib-only Python CLI (`foundry_cli.py`) bundled **in this skill's
directory** (next to this SKILL.md) — no install needed. It collects artifacts from
`.foundry/artifacts/`, reads git context, and POSTs to Foundry. Re-pushing the same
checkout creates a new **version** automatically (it remembers the session id in
`.foundry/session_id`).

First, set `CLI` to the bundled script's absolute path (it sits beside this SKILL.md):
```bash
CLI="$CLAUDE_PLUGIN_ROOT/foundry_cli.py"   # or the absolute path to foundry_cli.py in this skill dir
```

## Steps

1. **Make sure artifacts exist.** Put anything worth saving in `.foundry/artifacts/`:
   ```bash
   mkdir -p .foundry/artifacts
   # e.g. write your generated report there
   # cp report.html .foundry/artifacts/
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

4. **If it failed** (Foundry unreachable), the push is queued and the command still
   exits 0 (it must never block your work). Retry later with:
   ```bash
   python3 "$CLI" push --resume
   ```

## Config (env)
- `FOUNDRY_URL` — Foundry base URL (default `http://localhost:8080`)
- `FOUNDRY_KEY` — write API key (**required**; never hardcode/commit it)
- `FOUNDRY_PROJECT`, `FOUNDRY_TAGS` (comma-sep), `FOUNDRY_MODEL` — optional metadata

## Rules
- Never put `FOUNDRY_KEY` in a committed file — use the environment.
- Don't push secrets. Only files under `.foundry/artifacts/` are sent (plus git repo/branch/commit strings).
- Don't auto-push unless the user opted into the Stop hook (see `../stop-hook.md`).
