# Aider shim

Aider commits its own edits, so a **git `post-commit` hook** auto-pushes each change
to Foundry — the most reliable auto-trigger for aider.

## Install (per repo)
```bash
cp integrations/aider/post-commit .git/hooks/post-commit
chmod +x .git/hooks/post-commit
export FOUNDRY_URL=http://localhost:8080 FOUNDRY_KEY=fdy_...
```

Now every aider commit:
1. writes the commit diff/message to `.foundry/artifacts/commit-<sha>.md`,
2. runs `foundry push` (fail-open — never blocks the commit).

Re-pushes become **versions** of the same session (`.foundry/session_id`).

## Manual mode
Don't want auto? Skip the hook and just run `foundry push` when you want, after
dropping artifacts in `.foundry/artifacts/`.

## Notes
- This is **auto** — every commit pushes. Disable by removing `.git/hooks/post-commit`.
- Add `.foundry/` to `.gitignore` so state/artifacts aren't themselves committed.
