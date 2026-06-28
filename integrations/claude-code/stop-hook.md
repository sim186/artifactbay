# Opt-in: auto-push on session end (Claude Code Stop hook)

Explicit `/foundry-push` is the default. If you want Foundry to capture **every**
session automatically when Claude Code finishes, add a `Stop` hook.

This is **opt-in** on purpose: auto-push sends artifacts to a server without asking
each time. Only enable it on repos/instances where that's fine.

## settings.json snippet
Add to `~/.claude/settings.json` (global) or `.claude/settings.json` (per-project):

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /ABSOLUTE/PATH/integrations/foundry_cli.py push >> .foundry/push.log 2>&1 || true"
          }
        ]
      }
    ]
  }
}
```

Set `FOUNDRY_URL` and `FOUNDRY_KEY` in your environment (e.g. shell profile) so the
hook can authenticate.

## Why this is safe to run on every Stop
- **Fail-open:** the CLI exits 0 even when Foundry is down (it queues to
  `.foundry/pending/`), so it never blocks Claude Code from finishing. The trailing
  `|| true` is belt-and-suspenders.
- **No artifacts → no-op:** if `.foundry/artifacts/` is empty it prints a notice and does nothing.
- **Idempotent + versioned:** repeated pushes of the same checkout become versions, not duplicates.
- **Quiet:** output goes to `.foundry/push.log`, not your session.

To disable: remove the hook block.
