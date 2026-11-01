// Lightweight analytics scaffold. Activates only when env vars are set.
//
// Enable Plausible (self-host or cloud):
//   VITE_PLAUSIBLE_DOMAIN=pacemind.app
//   VITE_PLAUSIBLE_SRC=https://plausible.io/js/script.js   (optional override)
//
// Enable PostHog cloud:
//   VITE_POSTHOG_KEY=phc_xxx
//   VITE_POSTHOG_HOST=https://eu.i.posthog.com             (optional override)

let plausibleReady = false
let posthogInstance = null

export function initAnalytics() {
  initPlausible()
  initPostHog()
}

function initPlausible() {
  const domain = import.meta.env.VITE_PLAUSIBLE_DOMAIN
  if (!domain || typeof document === 'undefined') return
  const src = import.meta.env.VITE_PLAUSIBLE_SRC || 'https://plausible.io/js/script.js'
  const s = document.createElement('script')
  s.defer = true
  s.setAttribute('data-domain', domain)
  s.src = src
  document.head.appendChild(s)
  plausibleReady = true
}

function initPostHog() {
  const key = import.meta.env.VITE_POSTHOG_KEY
  if (!key || typeof window === 'undefined' || typeof document === 'undefined') return
  // Loaded from CDN to avoid adding posthog-js as a hard dependency.
  // If you want local bundling, `npm install posthog-js` and replace with a static import.
  const host = import.meta.env.VITE_POSTHOG_HOST || 'https://us.i.posthog.com'
  const snippet = document.createElement('script')
  snippet.type = 'text/javascript'
  snippet.async = true
  snippet.src = `${host}/static/array.js`
  snippet.onload = () => {
    if (window.posthog) {
      window.posthog.init(key, { api_host: host, capture_pageview: false, persistence: 'localStorage' })
      posthogInstance = window.posthog
    }
  }
  document.head.appendChild(snippet)
}

export function trackPageview(path) {
  if (plausibleReady && typeof window !== 'undefined' && typeof window.plausible === 'function') {
    window.plausible('pageview', { u: window.location.origin + path })
  }
  if (posthogInstance) {
    posthogInstance.capture('$pageview', { $current_url: window.location.origin + path })
  }
}

export function trackEvent(name, properties = {}) {
  if (plausibleReady && typeof window !== 'undefined' && typeof window.plausible === 'function') {
    window.plausible(name, { props: properties })
  }
  if (posthogInstance) {
    posthogInstance.capture(name, properties)
  }
}

export function identify(userId, traits = {}) {
  if (posthogInstance) {
    posthogInstance.identify(String(userId), traits)
  }
}
