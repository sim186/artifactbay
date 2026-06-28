# Foundry push (Codex CLI)

Codex reads `AGENTS.md`. Paste this block into your project's `AGENTS.md` so Codex
saves sessions to Foundry on request.

> **Trigger:** explicit. Mechanism: Codex runs the shell command itself.

---

## Saving sessions to Foundry

When the user asks to "save" / "push" / "archive" this session:

1. Put artifacts worth keeping in `.foundry/artifacts/` (`.html .md .json .svg .png .pdf .zip .txt`):
   ```bash
   mkdir -p .foundry/artifacts && cp <generated-file> .foundry/artifacts/
   ```
2. Push (the `foundry` wrapper is on PATH; else use `python3 /path/to/foundry_cli.py`):
   ```bash
   FOUNDRY_AGENT=codex foundry push --name "Short session title"
   ```
3. Show the returned `✓ pushed → <url>` to the user.

Preflight check: `foundry doctor`. Never commit `FOUNDRY_KEY` — it lives in the env.

---

## Setup (once)
```bash
export FOUNDRY_URL=http://localhost:8080
export FOUNDRY_KEY=fdy_...
ln -s /path/to/foundry/integrations/foundry /usr/local/bin/foundry
```
