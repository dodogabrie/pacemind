import { defineStore } from 'pinia'

let nextId = 1

export const useToastStore = defineStore('toast', {
  state: () => ({
    toasts: []
  }),

  actions: {
    /**
     * @param {object} toast
     * @param {string} toast.message   body text (already localized)
     * @param {string} [toast.title]
     * @param {'info'|'warning'|'error'} [toast.type]
     * @param {number} [toast.timeout] ms; 0 keeps it until dismissed
     * @param {string} [toast.key]     dedupe key — re-pushing replaces rather than stacks
     * @param {{label: string, handler: Function}} [toast.action]
     */
    push({ message, title = null, type = 'info', timeout = 6000, key = null, action = null }) {
      if (key) {
        const existing = this.toasts.find(t => t.key === key)
        if (existing) {
          clearTimeout(existing._timer)
          this.dismiss(existing.id)
        }
      }
      const id = nextId++
      const toast = { id, message, title, type, key, action, _timer: null }
      if (timeout > 0) {
        toast._timer = setTimeout(() => this.dismiss(id), timeout)
      }
      this.toasts.push(toast)
      return id
    },

    dismiss(id) {
      const idx = this.toasts.findIndex(t => t.id === id)
      if (idx === -1) return
      clearTimeout(this.toasts[idx]._timer)
      this.toasts.splice(idx, 1)
    },

    clear() {
      this.toasts.forEach(t => clearTimeout(t._timer))
      this.toasts = []
    }
  }
})
