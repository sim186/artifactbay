"""Standalone export: one self-contained HTML file, no ArtifactBay required.

Capability links still point at a running instance — fine for a colleague, useless
for presenting on a laptop with no network, sending an attachment, or handing
something to someone who should never touch your server at all.

This builds a single HTML file with every artifact inlined (HTML into sandboxed
`srcdoc`, images and PDFs as `data:` URIs) plus a small viewer shell. It opens over
`file://`, makes no network requests, and can be dropped on any static host.

Untrusted artifact HTML is still isolated: it goes into an `<iframe sandbox>` with
no `allow-same-origin`, and `allow-scripts` only for artifacts explicitly marked
`allow_scripts`. That mirrors how the server renders them — the file is meant to be
opened by a human, so it shouldn't become the soft path around the sandbox.

A mirror of this builder lives in `integrations/artifactbay_core.py` so the CLI can
pack local files with no server involved. Keep the two visually in step.
"""
from __future__ import annotations

import base64
from html import escape

# Types shown as an image; everything else falls back to text or an embed.
_IMAGE = {"png": "image/png", "svg": "image/svg+xml"}
_TEXTUAL = {"markdown", "json", "text", "conversation"}

_CSS = """
:root{color-scheme:dark light}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  background:#0f1116;color:#e6e9ef;height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:.75rem;padding:.6rem 1rem;
  border-bottom:1px solid #232936;flex:none}
h1{font-size:.95rem;margin:0;font-weight:600}
.meta{font:11px ui-monospace,monospace;color:#7d8698}
.spacer{margin-left:auto}
nav{display:flex;gap:.25rem;overflow-x:auto;padding:.5rem 1rem;border-bottom:1px solid #232936;flex:none}
nav button{background:none;border:1px solid transparent;color:#9aa3b2;cursor:pointer;
  padding:.3rem .7rem;border-radius:6px;font-size:.8rem;white-space:nowrap}
nav button:hover{background:#1a1f2b;color:#e6e9ef}
nav button[aria-selected=true]{background:#2b3350;border-color:#4c5680;color:#fff}
main{flex:1;min-height:0;position:relative;background:#fff}
section{position:absolute;inset:0;display:none}
section[data-active=true]{display:block}
iframe{width:100%;height:100%;border:0;background:#fff}
.img{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  padding:1.5rem;background:#fff}
.img img{max-width:100%;max-height:100%}
pre{margin:0;width:100%;height:100%;overflow:auto;padding:1.5rem;background:#12151c;
  color:#e6e9ef;font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word}
.doc{height:100%;overflow:auto;padding:2rem 2.5rem;background:#12151c;color:#e6e9ef;
  font-size:15px;line-height:1.65;max-width:none}
.doc h1,.doc h2,.doc h3,.doc h4{line-height:1.25;margin:1.4em 0 .5em}
.doc h1{font-size:1.7rem;border-bottom:1px solid #232936;padding-bottom:.3em}
.doc h2{font-size:1.3rem}.doc h3{font-size:1.1rem}
.doc p{margin:.7em 0}.doc ul,.doc ol{margin:.7em 0;padding-left:1.6em}
.doc li{margin:.25em 0}
.doc code{background:#1d2230;padding:.15em .4em;border-radius:4px;
  font:13px ui-monospace,monospace}
.doc pre.code{background:#1d2230;padding:1rem;border-radius:8px;overflow:auto;
  margin:.9em 0;height:auto;width:auto}
.doc pre.code code{background:none;padding:0}
.doc blockquote{border-left:3px solid #384153;margin:.8em 0;padding-left:1rem;color:#9aa3b2}
.doc hr{border:0;border-top:1px solid #232936;margin:1.5em 0}
.doc a{color:#8b95ff}
.chat{height:100%;overflow:auto;padding:1.25rem;background:#12151c}
.msg{max-width:75%;margin:.5rem 0;padding:.5rem .9rem;border-radius:14px;font-size:.85rem;
  line-height:1.5;white-space:pre-wrap}
.msg.user{margin-left:auto;background:#4c5680;color:#fff}
.msg.assistant{background:#1d2230;color:#e6e9ef}
.role{font-size:9px;text-transform:uppercase;letter-spacing:.06em;opacity:.6;margin-bottom:.15rem}
footer{flex:none;padding:.4rem 1rem;border-top:1px solid #232936;
  font:11px ui-monospace,monospace;color:#5c6474}
@media print{nav,header,footer{display:none}section{position:static;display:none}
  section[data-active=true]{display:block;height:100vh}}
"""

# Arrow keys to move between artifacts — this file is often opened to present from.
_JS = """
(function(){
  var tabs=[].slice.call(document.querySelectorAll('nav button'));
  var panes=[].slice.call(document.querySelectorAll('section'));
  function show(i){
    tabs.forEach(function(t,j){t.setAttribute('aria-selected',String(j===i))});
    panes.forEach(function(p,j){p.setAttribute('data-active',String(j===i))});
  }
  tabs.forEach(function(t,i){t.addEventListener('click',function(){show(i)})});
  document.addEventListener('keydown',function(e){
    var cur=tabs.findIndex(function(t){return t.getAttribute('aria-selected')==='true'});
    if(e.key==='ArrowRight'&&cur<tabs.length-1)show(cur+1);
    if(e.key==='ArrowLeft'&&cur>0)show(cur-1);
  });
})();
"""


def render_markdown(text: str) -> str:
    """Minimal, XSS-safe markdown → HTML.

    Everything is escaped FIRST, then a small set of block/inline patterns is
    re-introduced as tags. That ordering is the safety property: no markup can
    survive from the source, so hostile markdown can't inject anything. Links are
    additionally restricted to http/https/mailto.

    Deliberately small — the standalone file has no bundler and no network, so a
    real markdown library isn't an option. Unsupported syntax degrades to text.
    """
    import re

    out: list[str] = []
    in_code = False
    in_list: str | None = None

    def inline(s: str) -> str:
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        # Only safe schemes; anything else stays as plain text.
        s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+|mailto:[^\s)]+)\)",
                   r'<a href="\2" rel="noreferrer noopener">\1</a>', s)
        return s

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    for raw in escape(text).split("\n"):
        line = raw.rstrip()
        if line.startswith("```"):
            close_list()
            out.append("</code></pre>" if in_code else '<pre class="code"><code>')
            in_code = not in_code
            continue
        if in_code:
            out.append(raw)
            continue
        if not line.strip():
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue
        if re.match(r"^\s*(---+|\*\*\*+)\s*$", line):
            close_list()
            out.append("<hr>")
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        numbered = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if bullet or numbered:
            want = "ul" if bullet else "ol"
            if in_list != want:
                close_list()
                out.append(f"<{want}>")
                in_list = want
            out.append(f"<li>{inline((bullet or numbered).group(1))}</li>")
            continue
        quote = re.match(r"^&gt;\s?(.*)$", line)
        if quote:
            close_list()
            out.append(f"<blockquote>{inline(quote.group(1))}</blockquote>")
            continue
        close_list()
        out.append(f"<p>{inline(line)}</p>")

    if in_code:
        out.append("</code></pre>")
    close_list()
    return "\n".join(out)


def _pane(name: str, artifact_type: str, data: bytes, allow_scripts: bool) -> str:
    """Render one artifact into a self-contained pane."""
    if artifact_type == "html":
        # No allow-same-origin: the frame gets a unique opaque origin, so artifact
        # script (when permitted at all) can't reach into the wrapper document.
        sandbox = "allow-scripts" if allow_scripts else ""
        return (f'<iframe title="{escape(name, quote=True)}" sandbox="{sandbox}" '
                f'srcdoc="{escape(data.decode("utf-8", errors="replace"), quote=True)}"></iframe>')

    if artifact_type in _IMAGE:
        b64 = base64.b64encode(data).decode()
        return (f'<div class="img"><img alt="{escape(name, quote=True)}" '
                f'src="data:{_IMAGE[artifact_type]};base64,{b64}"></div>')

    if artifact_type == "pdf":
        b64 = base64.b64encode(data).decode()
        return f'<iframe title="{escape(name, quote=True)}" src="data:application/pdf;base64,{b64}"></iframe>'

    if artifact_type == "conversation":
        return _transcript(data)

    if artifact_type == "markdown":
        body = render_markdown(data.decode("utf-8", errors="replace"))
        return f'<div class="doc">{body}</div>'

    if artifact_type in _TEXTUAL:
        return f"<pre>{escape(data.decode('utf-8', errors='replace'))}</pre>"

    return (f'<pre>{escape(name)} ({escape(artifact_type)}, {len(data)} bytes)\n\n'
            f'Not embeddable in a standalone file — export the session as a zip instead.</pre>')


def _transcript(data: bytes) -> str:
    """Render a conversation slice as chat bubbles (owner exports only)."""
    import json

    try:
        messages = json.loads(data.decode("utf-8", errors="replace"))
        if not isinstance(messages, list):
            raise ValueError
    except Exception:  # noqa: BLE001
        return f"<pre>{escape(data.decode('utf-8', errors='replace'))}</pre>"

    rows = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "assistant"))
        css = "user" if role.lower() == "user" else "assistant"
        rows.append(f'<div class="msg {css}"><div class="role">{escape(role)}</div>'
                    f'{escape(str(m.get("content", "")))}</div>')
    return f'<div class="chat">{"".join(rows)}</div>'


def build(title: str, subtitle: str, artifacts: list[dict], footer: str = "") -> str:
    """Assemble the standalone document.

    `artifacts` items: {name, type, data (bytes), allow_scripts (bool)}.
    """
    if not artifacts:
        artifacts = [{"name": "empty", "type": "text",
                      "data": b"This session has no artifacts.", "allow_scripts": False}]

    tabs, panes = [], []
    for i, a in enumerate(artifacts):
        selected = "true" if i == 0 else "false"
        tabs.append(f'<button type="button" aria-selected="{selected}">{escape(a["name"])}</button>')
        panes.append(f'<section data-active="{selected}">'
                     f'{_pane(a["name"], a["type"], a["data"], a.get("allow_scripts", False))}'
                     f"</section>")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>{escape(title)}</h1>
  <span class="meta">{escape(subtitle)}</span>
</header>
<nav>{"".join(tabs)}</nav>
<main>{"".join(panes)}</main>
<footer>{escape(footer or "Standalone export — no network required. ← → to switch artifacts.")}</footer>
<script>{_JS}</script>
</body>
</html>
"""
