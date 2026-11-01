import { defineStore } from 'pinia'
import api from '../services/api'

// Module-scoped so the in-flight promise isn't wrapped in Pinia reactivity.
// Views mount *before* App.vue's onMounted runs, so every view that fetches
// auth-gated data must await ensureAuthReady() first — otherwise it would see
// isAuthenticated === false and render its logged-out gate for a logged-in user.
let authProbe = null

export const useAuthStore = defineStore('auth', {
  state: () => ({
    isAuthenticated: false,
    user: null,
    // false until the first /auth/status round-trip settles
    authChecked: false,
    // Global sign-in modal (nav button + the session-expired toast open it)
    signInModalOpen: false
  }),

  getters: {
    /**
     * Label for "who is logged in". The user object no longer guarantees any
     * Strava field, so fall back through whatever identity we do have.
     */
    displayName: (state) => {
      const u = state.user
      if (!u) return ''
      return u.name || u.strava_username || u.email || ''
    }
  },

  actions: {
    async checkAuthStatus() {
      try {
        const response = await api.get('/auth/status')
        this.isAuthenticated = !!response.data.authenticated
        this.user = response.data.user || null
      } catch (error) {
        this.isAuthenticated = false
        this.user = null
      } finally {
        this.authChecked = true
      }
    },

    /**
     * Resolve once the auth state is known. Memoized: concurrent callers
     * (App.vue plus each view) share a single /auth/status request.
     */
    ensureAuthReady() {
      if (this.authChecked) return Promise.resolve()
      if (!authProbe) {
        authProbe = this.checkAuthStatus().finally(() => { authProbe = null })
      }
      return authProbe
    },

    /** Called by the API interceptor when the server rejects our session. */
    markSessionExpired() {
      this.isAuthenticated = false
      this.user = null
      this.authChecked = true
    },

    openSignIn() { this.signInModalOpen = true },
    closeSignIn() { this.signInModalOpen = false },

    /**
     * Ask the backend to email a magic sign-in link. Always resolves 202 —
     * the server never confirms whether the address has an account.
     */
    async requestMagicLink(email) {
      await api.post('/auth/magic-link', { email })
    },

    /** @returns {Array<{provider: string, connected: boolean, ...}>} */
    async fetchConnections() {
      const response = await api.get('/auth/connections')
      return response.data.connections || []
    },

    async disconnectProvider(provider) {
      await api.delete(`/auth/connections/${provider}`)
    },

    async getStravaAuthUrl() {
      const response = await api.get('/auth/strava')
      return response.data.auth_url
    },

    async logout() {
      try {
        await api.post('/auth/logout')
      } catch (error) {
        // Clear local state even if server call fails
      }
      this.isAuthenticated = false
      this.user = null
      this.authChecked = true
    },

    async refreshStravaToken() {
      await api.post('/auth/refresh')
    }
  }
})
