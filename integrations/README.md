# Foundry Agent Integrations

How AI agents push sessions to Foundry. Protocol spec: `../docs/02-agent-integration-protocol.md`.

## Engine: `foundry_cli.py`
Stdlib-only Python (no `pip install`) so it drops into any agent's shell.

```bash
export FOUNDRY_URL=http://localhost:8080
export FOUNDRY_KEY=fdy_...          # write key — keep in env, never commit

python3 foundry_cli.py doctor       # check connectivity + auth + artifacts
python3 foundry_cli.py push --name "My session"
python3 foundry_cli.py push --resume # flush any queued (offline) pushes
python3 foundry_cli.py push --dry-run
```

- Collects artifacts from `.foundry/artifacts/` (`FOUNDRY_ARTIFACTS_DIR` to change).
- **Interactive HTML** (slide decks, dashboards): opt in to JS with
  `FOUNDRY_ALLOW_SCRIPTS="deck.html,*.slides.html"` (comma globs). Matching HTML gets
  `allow_scripts=true` so it runs in the sandboxed iframe. Default: scripts off.
- Reads git repo/branch/commit automatically.
- Remembers the session in `.foundry/session_id` → re-push = new **version**.
- **Idempotent** (Idempotency-Key) and **fail-open** (never crashes the agent; queues to `.foundry/pending/`).

## Trigger model
- **Default = explicit.** Push when the user asks. Universal across agents.
- **Opt-in = automatic.** A Stop hook auto-pushes on session end (Claude Code) — see `claude-code/stop-hook.md`.

## Per-agent shims
All shims call the **same** engine (`foundry_cli.py`, via the `foundry` wrapper).
Adding an agent = a thin trigger around `push`.

| Agent | Folder | Trigger | Mechanism |
|-------|--------|---------|-----------|
| Claude Code | `claude-code/foundry-push/` | explicit (+opt-in auto) | Skill `/foundry-push` + optional Stop hook |
| Codex | `codex/AGENTS.md` | explicit | `AGENTS.md` instruction → agent runs `foundry push` |
| Aider | `aider/` | **auto** | git `post-commit` hook (aider auto-commits) — captures diff + pushes |
| OpenCode | `opencode/` | explicit | `AGENTS.md` instruction or `opencode.json` command |
| Cursor | `cursor/` | explicit | `.cursor/rules` rule + VS Code task button |

The `foundry` wrapper (`integrations/foundry`) puts `foundry doctor` / `foundry push`
on PATH:
```bash
ln -s "$PWD/integrations/foundry" /usr/local/bin/foundry
```
Each shim sets `FOUNDRY_AGENT=<name>` so sessions show the right agent badge.

## Install the Claude Code skill
Copy the skill where Claude Code looks for skills:
```bash
cp -r claude-code/foundry-push ~/.claude/skills/      # global
# or  .claude/skills/  in a project
```
Then in Claude Code: `/foundry-push`. Set `FOUNDRY_URL` + `FOUNDRY_KEY` in your shell profile.

## Security
- `FOUNDRY_KEY` lives in the environment only. Never commit it.
- Only files under `.foundry/artifacts/` + git metadata strings are sent — no repo-wide slurp.
- HTML is stored as-is; the **server** sandboxes it on render (iframe + CSP), not the agent.
