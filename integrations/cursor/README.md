# Cursor shim

Cursor has no reliable session-end hook, so Foundry push is **explicit** here:
a Cursor Rule tells the agent how, and a VS Code task gives a one-click button.

## A. Cursor Rule
Save as `.cursor/rules/foundry-push.mdc` in your project:

```markdown
---
description: Push the current session's artifacts to Foundry
globs:
alwaysApply: false
---
When the user asks to save/push/archive this session to Foundry:
1. Put artifacts in `.foundry/artifacts/` (.html .md .json .svg .png .pdf .zip .txt).
2. Run in the terminal: `FOUNDRY_AGENT=cursor foundry push --name "Short title"`
3. Show the returned `✓ pushed → <url>` to the user.
Preflight with `foundry doctor`. Never put FOUNDRY_KEY in a committed file.
```

## B. One-click task — .vscode/tasks.json
```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Foundry: push session",
      "type": "shell",
      "command": "FOUNDRY_AGENT=cursor foundry push --name \"${input:title}\"",
      "problemMatcher": []
    }
  ],
  "inputs": [
    { "id": "title", "type": "promptString", "description": "Session title" }
  ]
}
```
Run via **Terminal → Run Task → Foundry: push session**.

## Setup (once)
```bash
export FOUNDRY_URL=http://localhost:8080
export FOUNDRY_KEY=fdy_...
ln -s /path/to/foundry/integrations/foundry /usr/local/bin/foundry
```
