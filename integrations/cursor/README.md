# Cursor shim

Cursor has no reliable session-end hook, so ArtifactBay push is **explicit** here:
a Cursor Rule tells the agent how, and a VS Code task gives a one-click button.

## A. Cursor Rule
Save as `.cursor/rules/artifactbay-push.mdc` in your project:

```markdown
---
description: Push the current session's artifacts to ArtifactBay
globs:
alwaysApply: false
---
When the user asks to save/push/archive this session to ArtifactBay:
1. Put artifacts in `.artifactbay/artifacts/` (.html .md .json .svg .png .pdf .zip .txt).
2. Run in the terminal: `ARTIFACTBAY_AGENT=cursor artifactbay push --name "Short title"`
3. Show the returned `✓ pushed → <url>` to the user.
Preflight with `artifactbay doctor`. Never put ARTIFACTBAY_KEY in a committed file.
```

## B. One-click task — .vscode/tasks.json
```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "ArtifactBay: push session",
      "type": "shell",
      "command": "ARTIFACTBAY_AGENT=cursor artifactbay push --name \"${input:title}\"",
      "problemMatcher": []
    }
  ],
  "inputs": [
    { "id": "title", "type": "promptString", "description": "Session title" }
  ]
}
```
Run via **Terminal → Run Task → ArtifactBay: push session**.

## Setup (once)
```bash
export ARTIFACTBAY_URL=http://localhost:8080
export ARTIFACTBAY_KEY=ab_...
ln -s /path/to/artifactbay/integrations/artifactbay /usr/local/bin/artifactbay
```
