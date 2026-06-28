"""Seed demo sessions for local UI dev. Run: uv run python seed.py [BASE_URL]"""
from __future__ import annotations

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8009"
KEY = "fdy_dev_changeme"
H = {"Authorization": f"Bearer {KEY}"}

ARCH_HTML = """<!doctype html><html><head><meta charset=utf-8>
<style>body{font-family:system-ui;margin:2rem;color:#1a1a1a}
h1{color:#6366f1}code{background:#f0f0f0;padding:2px 6px;border-radius:4px}
details{margin:1rem 0;border:1px solid #ddd;border-radius:8px;padding:.5rem 1rem}
summary{cursor:pointer;font-weight:600}</style></head>
<body><h1>Database Architecture</h1>
<p>Proposed schema for the redesign. Normalized to 3NF with content-addressed blobs.</p>
<details open><summary>Tables</summary>
<ul><li><code>session</code> — core entity</li>
<li><code>artifact</code> — per-version outputs</li>
<li><code>blob</code> — content-addressed by sha256</li></ul></details>
<details><summary>Why content-addressing?</summary>
<p>Store-once, ref-many. Re-uploading identical bytes dedupes automatically.</p></details>
<svg width=300 height=80><rect width=300 height=80 rx=8 fill=#6366f1/>
<text x=150 y=46 text-anchor=middle fill=white font-family=monospace font-size=14>session &#8594; artifact &#8594; blob</text></svg>
</body></html>"""

API_HTML = """<!doctype html><html><head><meta charset=utf-8>
<style>body{font-family:system-ui;margin:2rem}h1{color:#10a37f}
table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px 12px;text-align:left}</style>
</head><body><h1>API Endpoints</h1>
<table><tr><th>Method</th><th>Path</th></tr>
<tr><td>POST</td><td>/v0/sessions</td></tr>
<tr><td>GET</td><td>/v0/sessions/{id}</td></tr>
<tr><td>GET</td><td>/v0/artifacts/{id}</td></tr></table></body></html>"""

SESSIONS = [
    {
        "name": "Database redesign", "agent": "claude-code", "model": "claude-opus-4-8",
        "project": "Inspector", "tags": ["database", "architecture"], "favorite": True,
        "git": {"repository": "git@github.com:acme/inspector.git", "branch": "main", "commit": "abc1234"},
        "artifacts": [
            {"name": "architecture.html", "type": "html", "content": ARCH_HTML},
            {"name": "notes.md", "type": "markdown", "content": "# Notes\n\n- 3NF\n- dedupe blobs\n"},
        ],
    },
    {
        "name": "API reference", "agent": "claude-code", "model": "claude-opus-4-8",
        "project": "Inspector", "tags": ["api", "docs"],
        "git": {"repository": "git@github.com:acme/inspector.git", "branch": "main", "commit": "def5678"},
        "artifacts": [{"name": "endpoints.html", "type": "html", "content": API_HTML}],
    },
    {
        "name": "Lambda cold-start optimization", "agent": "codex", "model": "gpt-5",
        "project": "Backend Platform", "tags": ["perf", "aws"],
        "git": {"repository": "git@github.com:acme/platform.git", "branch": "perf", "commit": "9911aac"},
        "artifacts": [
            {"name": "report.html", "type": "html",
             "content": "<h1 style='font-family:system-ui;color:#10a37f'>Cold start: 840ms → 120ms</h1>"},
        ],
    },
    {
        "name": "Qt rendering fix", "agent": "opencode", "model": "qwen-3",
        "project": "SwissKnife", "tags": ["bug", "qt"],
        "artifacts": [{"name": "diff.txt", "type": "text", "content": "- repaint()\n+ update()\n"}],
    },
]


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        for i, s in enumerate(SESSIONS):
            r = c.post("/v0/sessions", json=s, headers={**H, "Idempotency-Key": f"seed-{i}"})
            r.raise_for_status()
            print(f"  {s['name']:<32} → {r.json()['url']}")
    print("seeded ✅")


if __name__ == "__main__":
    main()
