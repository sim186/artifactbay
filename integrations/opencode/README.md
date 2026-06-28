# OpenCode shim

OpenCode reads `AGENTS.md` and supports custom commands. Two ways to wire it:

## A. Explicit (recommended) — AGENTS.md
Paste into your project `AGENTS.md`:

```markdown
## Saving sessions to ArtifactBay
When asked to save/push/archive this session:
1. Put artifacts in `.artifactbay/artifacts/` (.html .md .json .svg .png .pdf .zip .txt).
2. Run: `ARTIFACTBAY_AGENT=opencode artifactbay push --name "Short title"`
3. Show the returned URL to the user. (Preflight: `artifactbay doctor`.)
```

## B. Custom command — opencode.json
Define a one-word command so the user can run `/artifactbay` in OpenCode:

```json
{
  "commands": {
    "artifactbay": {
      "description": "Push this session's artifacts to ArtifactBay",
      "command": "ARTIFACTBAY_AGENT=opencode artifactbay push --name \"$ARGUMENTS\""
    }
  }
}
```

## Setup (once)
```bash
export ARTIFACTBAY_URL=http://localhost:8080
export ARTIFACTBAY_KEY=ab_...
ln -s /path/to/artifactbay/integrations/artifactbay /usr/local/bin/artifactbay
```

Trigger model: explicit. Re-pushes version the same session. Never commit `ARTIFACTBAY_KEY`.
