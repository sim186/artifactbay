// Renders a search snippet safely. The backend marks matches with @@HLS@@/@@HLE@@
// sentinels (not HTML). We escape the raw text, THEN swap sentinels for <mark> —
// so any HTML inside artifact text is inert (no XSS).
const START = '@@HLS@@'
const END = '@@HLE@@'

function escapeHtml(s: string): string {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

export function Snippet({ text, className = '' }: { text: string; className?: string }) {
  const html = escapeHtml(text)
    .replaceAll(START, '<mark class="bg-accent-soft text-text rounded-sm px-0.5">')
    .replaceAll(END, '</mark>')
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />
}
