import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({
  breaks: true,
  gfm: true,
})

const ALLOWED_TAGS = [
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'br', 'hr',
  'ul', 'ol', 'li',
  'strong', 'em', 'del', 's',
  'a', 'code', 'pre',
  'blockquote',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'div', 'span', 'abbr',
]

const ALLOWED_ATTR = ['href', 'target', 'rel', 'title', 'class', 'tabindex', 'data-term']

// Training/fitness term glossary
const GLOSSARY = {
  'CTL': 'Chronic Training Load — your long-term fitness, based on a 42-day weighted average of training stress. Higher = fitter.',
  'ATL': 'Acute Training Load — your short-term fatigue, based on a 7-day weighted average. Higher = more recent training stress.',
  'TSB': 'Training Stress Balance (CTL minus ATL). Positive = fresh and rested. Negative = carrying fatigue.',
  'D+': 'Cumulative positive elevation gain (meters climbed) over the route.',
  'D-': 'Cumulative negative elevation loss (meters descended) over the route.',
  'TRIMP': 'Training Impulse — a single number summarizing the training load of a session based on duration and intensity.',
  'VO2max': 'Maximum oxygen uptake — the peak rate your body can use oxygen during exercise. A key indicator of aerobic fitness.',
  'FTP': 'Functional Threshold Power — the highest power you can sustain for roughly one hour.',
  'RPE': 'Rate of Perceived Exertion — a subjective 1-10 scale of how hard an effort feels.',
  'GAP': 'Grade Adjusted Pace — your pace normalized to flat ground, accounting for uphill/downhill effort.',
}

function addGlossaryHints(html) {
  // Build a single regex for all terms, longest first to avoid partial matches
  const terms = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length)
  const pattern = new RegExp(
    `(?<![\\w/])\\b(${terms.map(t => t.replace(/[+]/g, '\\$&')).join('|')})\\b(?![\\w"<])`,
    'g'
  )
  const seen = new Set()
  return html.replace(pattern, (match, term) => {
    // Only annotate first occurrence of each term
    if (seen.has(term)) return match
    seen.add(term)
    const tip = GLOSSARY[term]
    if (!tip) return match
    return `<abbr class="agent-term" title="${tip.replace(/"/g, '&quot;')}" tabindex="0" data-term="${term}">${match}</abbr>`
  })
}

export function renderMarkdown(text) {
  if (!text) return ''
  const html = marked.parse(text)
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ADD_ATTR: ['target'],
  })
  return addGlossaryHints(clean)
}
