import { defineStore } from 'pinia'
import api from '../services/api'

export const useSubscriptionStore = defineStore('subscription', {
  state: () => ({
    plan: 'free',
    status: 'active',
    isPremium: false,
    agentMessagesRemaining: 3,
    expiresAt: null,
    loading: false,
    showUpgradeModal: false,
    upgradeFeature: null,
  }),

  actions: {
    async fetchStatus() {
      try {
        const response = await api.get('/billing/status')
        const data = response.data
        this.plan = data.plan
        this.status = data.status
        this.isPremium = data.is_premium
        this.agentMessagesRemaining = data.agent_messages_remaining
        this.expiresAt = data.expires_at
      } catch (error) {
        // Not authenticated or billing not set up — default to free
        this.plan = 'free'
        this.isPremium = false
      }
    },

    async createCheckout(plan = 'premium_monthly') {
      this.loading = true
      try {
        const response = await api.post('/billing/checkout', { plan })
        const { checkout_url } = response.data
        if (checkout_url) {
          window.location.href = checkout_url
        }
        return response.data
      } catch (error) {
        throw error
      } finally {
        this.loading = false
      }
    },

    async cancelSubscription() {
      this.loading = true
      try {
        await api.post('/billing/cancel')
        await this.fetchStatus()
      } catch (error) {
        throw error
      } finally {
        this.loading = false
      }
    },

    openUpgradeModal(feature = null) {
      this.upgradeFeature = feature
      this.showUpgradeModal = true
    },

    closeUpgradeModal() {
      this.showUpgradeModal = false
      this.upgradeFeature = null
    },

    updateMessagesRemaining(count) {
      this.agentMessagesRemaining = count
    },
  },
})
