import { defineStore } from 'pinia'
import api from '../services/api'

export const useNotificationStore = defineStore('notifications', {
  state: () => ({
    notifications: [],
    unreadCount: 0,
    loading: false,
  }),

  actions: {
    async fetchNotifications() {
      this.loading = true
      try {
        const { data } = await api.get('/notifications/')
        this.notifications = data.notifications || []
        this.unreadCount = data.unread_count || 0
      } catch {
        // silent
      } finally {
        this.loading = false
      }
    },

    async fetchUnreadCount() {
      try {
        const { data } = await api.get('/notifications/')
        this.unreadCount = data.unread_count || 0
      } catch {
        // silent
      }
    },

    async markRead(id) {
      try {
        await api.put(`/notifications/${id}/read`)
        const n = this.notifications.find(n => n.id === id)
        if (n) {
          n.read = true
          this.unreadCount = Math.max(0, this.unreadCount - 1)
        }
      } catch {
        // silent
      }
    },

    async markAllRead() {
      try {
        await api.put('/notifications/read-all')
        this.notifications.forEach(n => { n.read = true })
        this.unreadCount = 0
      } catch {
        // silent
      }
    },
  },
})
