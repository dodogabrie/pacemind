const DEFAULT_TITLE = 'PaceMind — AI pacing coach for trail & ultra racing'
const DEFAULT_DESCRIPTION = 'Predict your race finish time and pacing strategy on any GPX course. PaceMind combines a physics-based model, your Strava history, and AI coaching to help you finish stronger.'
const SITE_URL = (import.meta.env.VITE_SITE_URL || 'https://pacemind.app').replace(/\/$/, '')

function upsertMeta(selector, attrs) {
  let el = document.head.querySelector(selector)
  if (!el) {
    el = document.createElement('meta')
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'content') continue
      el.setAttribute(k, v)
    }
    document.head.appendChild(el)
  }
  el.setAttribute('content', attrs.content)
}

function upsertLink(rel, href, hreflang) {
  const selector = hreflang
    ? `link[rel="${rel}"][hreflang="${hreflang}"]`
    : `link[rel="${rel}"]`
  let el = document.head.querySelector(selector)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    if (hreflang) el.setAttribute('hreflang', hreflang)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

export function applyRouteMeta(to, lang) {
  const meta = to.meta || {}
  const title = meta.title || DEFAULT_TITLE
  const description = meta.description || DEFAULT_DESCRIPTION
  const path = to.fullPath || '/'
  const canonical = `${SITE_URL}${path}`

  document.title = title
  if (document.documentElement && lang) {
    document.documentElement.setAttribute('lang', lang)
  }

  upsertMeta('meta[name="description"]', { name: 'description', content: description })
  upsertMeta('meta[property="og:title"]', { property: 'og:title', content: title })
  upsertMeta('meta[property="og:description"]', { property: 'og:description', content: description })
  upsertMeta('meta[property="og:url"]', { property: 'og:url', content: canonical })
  upsertMeta('meta[name="twitter:title"]', { name: 'twitter:title', content: title })
  upsertMeta('meta[name="twitter:description"]', { name: 'twitter:description', content: description })

  upsertLink('canonical', canonical)
}
