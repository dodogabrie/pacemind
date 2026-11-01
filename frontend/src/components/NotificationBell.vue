<template>
  <div class="notif-bell" ref="bellRef">
    <button class="notif-bell-btn" @click="toggle" :title="$t('notifications.unread', store.unreadCount)" :aria-label="$t('notifications.unread', store.unreadCount)">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
      <span v-if="store.unreadCount > 0" class="notif-badge">{{ store.unreadCount > 9 ? '9+' : store.unreadCount }}</span>
    </button>

    <div v-if="open" class="notif-dropdown">
      <div class="notif-header">
        <span class="notif-title">{{ $t('notifications.title') }}</span>
        <button v-if="store.unreadCount > 0" @click="store.markAllRead()" class="notif-mark-all">{{ $t('notifications.mark_all') }}</button>
      </div>
      <div class="notif-list" v-if="store.notifications.length > 0">
        <div
          v-for="n in store.notifications"
          :key="n.id"
          class="notif-item"
          :class="{ 'notif-item--unread': !n.read }"
          @click="store.markRead(n.id)"
        >
          <div class="notif-item-icon">
            <span v-if="n.type === 'weekly_summary'">W</span>
            <span v-else-if="n.type === 'coach_suggestion'">C</span>
            <span v-else-if="n.type === 'race_countdown'">R</span>
            <span v-else>N</span>
          </div>
          <div class="notif-item-body">
            <div class="notif-item-title">{{ n.title }}</div>
            <div class="notif-item-msg">{{ n.message }}</div>
            <div class="notif-item-time">{{ timeAgo(n.created_at) }}</div>
          </div>
        </div>
      </div>
      <div v-else class="notif-empty">{{ $t('notifications.empty') }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useNotificationStore } from '../stores/notifications'

const store = useNotificationStore()
const { t } = useI18n()
const open = ref(false)
const bellRef = ref(null)

const toggle = () => {
  open.value = !open.value
  if (open.value) {
    store.fetchNotifications()
  }
}

const handleClickOutside = (e) => {
  if (bellRef.value && !bellRef.value.contains(e.target)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  store.fetchUnreadCount()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside)
})

const timeAgo = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return t('notifications.just_now')
  if (diff < 3600) return t('notifications.minutes_ago', { n: Math.floor(diff / 60) })
  if (diff < 86400) return t('notifications.hours_ago', { n: Math.floor(diff / 3600) })
  return t('notifications.days_ago', { n: Math.floor(diff / 86400) })
}
</script>

<style scoped>
.notif-bell {
  position: relative;
}
.notif-bell-btn {
  position: relative;
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.625rem;
  margin: -0.25rem;
  border-radius: 0.375rem;
  transition: color 0.15s;
}
.notif-bell-btn:hover {
  color: #047857;
}
.notif-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
  color: white;
  background: #ef4444;
  border-radius: 9999px;
  padding: 0 4px;
}
.notif-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 320px;
  max-height: 400px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  box-shadow: 0 10px 25px rgba(0,0,0,0.1);
  z-index: 100;
  overflow: hidden;
}
@media (max-width: 639px) {
  /* Anchor to the viewport: the bell sits mid-header, so right:0 would push a 320px panel off-screen. */
  .notif-dropdown {
    position: fixed;
    top: calc(4rem + env(safe-area-inset-top) + 4px);
    left: .75rem;
    right: .75rem;
    width: auto;
    max-height: min(400px, calc(100dvh - 6rem));
  }
  .notif-bell .notif-list { max-height: min(340px, calc(100dvh - 9.5rem)); }
}
.notif-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #f1f5f9;
}
.notif-title {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #1e293b;
}
.notif-mark-all {
  font-size: 0.6875rem;
  padding: 0.5rem 0;
  color: #047857;
  background: none;
  border: none;
  cursor: pointer;
  font-weight: 600;
}
.notif-mark-all:hover {
  text-decoration: underline;
}
.notif-list {
  overflow-y: auto;
  max-height: 340px;
}
.notif-item {
  display: flex;
  gap: 0.625rem;
  padding: 0.625rem 1rem;
  cursor: pointer;
  border-bottom: 1px solid #f8fafc;
  transition: background 0.1s;
}
.notif-item:hover {
  background: #f8fafc;
}
.notif-item--unread {
  background: #f0fdf4;
}
.notif-item--unread:hover {
  background: #dcfce7;
}
.notif-item-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: #475569;
}
.notif-item--unread .notif-item-icon {
  background: #047857;
  color: white;
}
.notif-item-body {
  flex: 1;
  min-width: 0;
}
.notif-item-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 2px;
}
.notif-item-msg {
  font-size: 0.6875rem;
  color: #64748b;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.notif-item-time {
  font-size: 0.625rem;
  color: #94a3b8;
  margin-top: 2px;
}
.notif-empty {
  padding: 2rem 1rem;
  text-align: center;
  font-size: 0.8125rem;
  color: #94a3b8;
}
</style>
