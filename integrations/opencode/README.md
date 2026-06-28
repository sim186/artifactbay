# OpenCode shim

OpenCode reads `AGENTS.md` and supports custom commands. Two ways to wire it:

## A. Explicit (recommended) — AGENTS.md
Paste into your project `AGENTS.md`:

```markdown
## Saving sessions to Foundry
When asked to save/push/archive this session:
1. Put artifacts in `.foundry/artifacts/` (.html .md .json .svg .png .pdf .zip .txt).
2. Run: `FOUNDRY_AGENT=opencode foundry push --name "Short title"`
3. Show the returned URL to the user. (Preflight: `foundry doctor`.)
```

## B. Custom command — opencode.json
Define a one-word command so the user can run `/foundry` in OpenCode:

```json
{
  "commands": {
    "foundry": {
      "description": "Push this session's artifacts to Foundry",
      "command": "FOUNDRY_AGENT=opencode foundry push --name \"$ARGUMENTS\""
    }
  }
}
```

## Setup (once)
```bash
export FOUNDRY_URL=http://localhost:8080
export FOUNDRY_KEY=fdy_...
ln -s /path/to/foundry/integrations/foundry /usr/local/bin/foundry
```

Trigger model: explicit. Re-pushes version the same session. Never commit `FOUNDRY_KEY`.
