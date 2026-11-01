import axios from 'axios'

const fallbackBaseUrl = () => {
  if (typeof window === 'undefined') return 'http://localhost:5000/api'
  return `${window.location.origin}/api`
}

const resolveBaseUrl = () => {
  const envBase = import.meta.env.VITE_API_URL
  if (!envBase) return fallbackBaseUrl()
  if (typeof window === 'undefined') return envBase
  try {
    const url = new URL(envBase)
    const isLocalEnv =
      url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    const isRemotePage =
      window.location.hostname !== 'localhost' &&
      window.location.hostname !== '127.0.0.1'
    if (isLocalEnv && isRemotePage) {
      url.hostname = window.location.hostname
      return url.toString().replace(/\/$/, '')
    }
  } catch (error) {
    // Fall back to envBase if it's not a valid URL.
  }
  return envBase
}

const api = axios.create({
  baseURL: resolveBaseUrl(),
  withCredentials: true
})

// Handle expired/absent sessions and trigger the contextual upgrade modal on
// premium-gated 403s.
//
// A 401 is NOT a navigation event. Plenty of screens are legitimately usable
// while logged out (the race calendar is public; other views render a
// sign-in gate), and several stores already catch their own 401s to
// degrade gracefully. Hard-redirecting to "/" here defeated all of that and
// bounced anonymous visitors off Calendar/Routes/Races with no explanation.
//
// Instead: clear the auth state so the gates render, surface a toast only when
// a *live* session dropped out from under the user, and always reject so the
// caller can still handle it.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const url = error.config?.url || ''
    const status = error.response?.status
    const data = error.response?.data

    if (status === 401 && !url.includes('/auth/status')) {
      try {
        const [{ useAuthStore }, { useToastStore }, { default: i18n }] = await Promise.all([
          import('../stores/auth'),
          import('../stores/toast'),
          import('../i18n')
        ])
        const authStore = useAuthStore()
        // Only a user who *was* authenticated has a session to lose. For an
        // anonymous visitor this 401 is expected and needs no announcement.
        const hadSession = authStore.isAuthenticated
        authStore.markSessionExpired()
        if (hadSession) {
          const t = i18n.global.t
          useToastStore().push({
            key: 'session-expired',
            type: 'warning',
            timeout: 0,
            title: t('auth.session_expired.title'),
            message: t('auth.session_expired.text'),
            action: {
              label: t('common.buttons.sign_in'),
              handler: () => authStore.openSignIn()
            }
          })
        }
      } catch (_) {
        // Pinia/i18n not ready yet — the rejection below is still delivered.
      }
      return Promise.reject(error)
    }

    if (status === 403 && data && typeof data === 'object' && data.error === 'Premium subscription required') {
      try {
        const { useSubscriptionStore } = await import('../stores/subscription')
        useSubscriptionStore().openUpgradeModal(data.feature || null)
      } catch (_) {
        // store not available yet — swallow
      }
    }

    return Promise.reject(error)
  }
)

export default api
