# ArtifactBay push (Codex CLI)

Codex reads `AGENTS.md`. Paste this block into your project's `AGENTS.md` so Codex
saves sessions to ArtifactBay on request.

> **Trigger:** explicit. Mechanism: Codex runs the shell command itself.

---

## Saving sessions to ArtifactBay

When the user asks to "save" / "push" / "archive" this session:

1. Put artifacts worth keeping in `.artifactbay/artifacts/` (`.html .md .json .svg .png .pdf .zip .txt`):
   ```bash
   mkdir -p .artifactbay/artifacts && cp <generated-file> .artifactbay/artifacts/
   ```
2. Push (the `artifactbay` wrapper is on PATH; else use `python3 /path/to/artifactbay_cli.py`):
   ```bash
   ARTIFACTBAY_AGENT=codex artifactbay push --name "Short session title"
   ```
3. Show the returned `✓ pushed → <url>` to the user.

Preflight check: `artifactbay doctor`. Never commit `ARTIFACTBAY_KEY` — it lives in the env.

---

## Setup (once)
```bash
export ARTIFACTBAY_URL=http://localhost:8080
export ARTIFACTBAY_KEY=ab_...
ln -s /path/to/artifactbay/integrations/artifactbay /usr/local/bin/artifactbay
```
