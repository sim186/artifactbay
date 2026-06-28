# Aider shim

Aider commits its own edits, so a **git `post-commit` hook** auto-pushes each change
to ArtifactBay — the most reliable auto-trigger for aider.

## Install (per repo)
```bash
cp integrations/aider/post-commit .git/hooks/post-commit
chmod +x .git/hooks/post-commit
export ARTIFACTBAY_URL=http://localhost:8080 ARTIFACTBAY_KEY=ab_...
```

Now every aider commit:
1. writes the commit diff/message to `.artifactbay/artifacts/commit-<sha>.md`,
2. runs `artifactbay push` (fail-open — never blocks the commit).

Re-pushes become **versions** of the same session (`.artifactbay/session_id`).

## Manual mode
Don't want auto? Skip the hook and just run `artifactbay push` when you want, after
dropping artifacts in `.artifactbay/artifacts/`.

## Notes
- This is **auto** — every commit pushes. Disable by removing `.git/hooks/post-commit`.
- Add `.artifactbay/` to `.gitignore` so state/artifacts aren't themselves committed.
