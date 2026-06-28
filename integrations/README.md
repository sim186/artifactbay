# ArtifactBay Agent Integrations

How AI agents push sessions to ArtifactBay. Protocol spec: `../docs/02-agent-integration-protocol.md`.

## Engine: `artifactbay_cli.py`
Stdlib-only Python (no `pip install`) so it drops into any agent's shell.

```bash
export ARTIFACTBAY_URL=http://localhost:8080
export ARTIFACTBAY_KEY=ab_...          # write key — keep in env, never commit

python3 artifactbay_cli.py doctor       # check connectivity + auth + artifacts
python3 artifactbay_cli.py push --name "My session"
python3 artifactbay_cli.py push --resume # flush any queued (offline) pushes
python3 artifactbay_cli.py push --dry-run
```

- Collects artifacts from `.artifactbay/artifacts/` (`ARTIFACTBAY_ARTIFACTS_DIR` to change).
- **Interactive HTML** (slide decks, dashboards): opt in to JS with
  `ARTIFACTBAY_ALLOW_SCRIPTS="deck.html,*.slides.html"` (comma globs). Matching HTML gets
  `allow_scripts=true` so it runs in the sandboxed iframe. Default: scripts off.
- Reads git repo/branch/commit automatically.
- Remembers the session in `.artifactbay/session_id` → re-push = new **version**.
- **Idempotent** (Idempotency-Key) and **fail-open** (never crashes the agent; queues to `.artifactbay/pending/`).

## Trigger model
- **Default = explicit.** Push when the user asks. Universal across agents.
- **Opt-in = automatic.** A Stop hook auto-pushes on session end (Claude Code) — see `claude-code/stop-hook.md`.

## Per-agent shims
All shims call the **same** engine (`artifactbay_cli.py`, via the `artifactbay` wrapper).
Adding an agent = a thin trigger around `push`.

| Agent | Folder | Trigger | Mechanism |
|-------|--------|---------|-----------|
| Claude Code | `claude-code/artifactbay-push/` | explicit (+opt-in auto) | Skill `/artifactbay-push` + optional Stop hook |
| Codex | `codex/AGENTS.md` | explicit | `AGENTS.md` instruction → agent runs `artifactbay push` |
| Aider | `aider/` | **auto** | git `post-commit` hook (aider auto-commits) — captures diff + pushes |
| OpenCode | `opencode/` | explicit | `AGENTS.md` instruction or `opencode.json` command |
| Cursor | `cursor/` | explicit | `.cursor/rules` rule + VS Code task button |

The `artifactbay` wrapper (`integrations/artifactbay`) puts `artifactbay doctor` / `artifactbay push`
on PATH:
```bash
ln -s "$PWD/integrations/artifactbay" /usr/local/bin/artifactbay
```
Each shim sets `ARTIFACTBAY_AGENT=<name>` so sessions show the right agent badge.

## Install the Claude Code skill
Copy the skill where Claude Code looks for skills:
```bash
cp -r claude-code/artifactbay-push ~/.claude/skills/      # global
# or  .claude/skills/  in a project
```
Then in Claude Code: `/artifactbay-push`. Set `ARTIFACTBAY_URL` + `ARTIFACTBAY_KEY` in your shell profile.

## Security
- `ARTIFACTBAY_KEY` lives in the environment only. Never commit it.
- Only files under `.artifactbay/artifacts/` + git metadata strings are sent — no repo-wide slurp.
- HTML is stored as-is; the **server** sandboxes it on render (iframe + CSP), not the agent.
