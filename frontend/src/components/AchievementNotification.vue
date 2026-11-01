<template>
  <!-- Compact notification badge -->
  <!-- Phones: bottom-left, clear of the sticky nav and the home indicator. -->
  <div v-if="unreadCount > 0" class="fixed z-50 left-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] sm:left-auto sm:bottom-auto sm:top-4 sm:right-4">
    <button
      @click="showPanel = !showPanel"
      class="btn btn-signal shadow-lg"
    >
      <svg class="w-5 h-5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></svg>
      <span>{{ $t('achievements.new_count', unreadCount) }}</span>
    </button>

    <!-- Expandable panel -->
    <Transition name="slide-down">
      <div
        v-if="showPanel"
        class="absolute bottom-14 left-0 w-[calc(100vw-2rem)] max-h-[60dvh] sm:bottom-auto sm:left-auto sm:top-14 sm:right-0 sm:w-96 sm:max-h-[500px] overflow-y-auto rounded-2xl border border-white/70 bg-white/90 shadow-xl"
      >
        <div class="sticky top-0 bg-gradient-to-r from-amber-300 to-orange-400 p-4 flex items-center justify-between">
          <h3 class="font-bold text-slate-900">{{ $t('achievements.title') }}</h3>
          <button
            @click="markAllAsRead"
            class="text-xs text-slate-900 hover:text-slate-700 underline min-h-[44px] px-2"
          >
            {{ $t('achievements.mark_all') }}
          </button>
        </div>

        <div class="p-2 space-y-2">
          <div
            v-for="achievement in visibleAchievements"
            :key="achievement.id"
            class="p-3 rounded-xl border border-amber-200 bg-amber-50 hover:bg-amber-100 transition-colors cursor-pointer"
            @click="markAsRead(achievement.id)"
          >
            <div class="flex items-start gap-3">
              <div class="shrink-0 text-amber-600"><svg class="w-6 h-6" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></svg></div>
              <div class="flex-1 min-w-0">
                <h4 class="font-bold text-slate-900 text-sm">{{ achievement.name }}</h4>
                <p class="text-xs text-slate-600 mt-1">{{ achievement.description }}</p>
                <p class="text-xs text-slate-400 mt-1">{{ formatDate(achievement.earned_at) }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import api from '../services/api'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const visibleAchievements = ref([])
const pollInterval = ref(null)
const showPanel = ref(false)

const unreadCount = computed(() => visibleAchievements.value.length)

const fetchNewAchievements = async () => {
  try {
    const response = await api.get('/performance/achievements', {
      params: { unread_only: true }
    })
    const data = response.data
    const newAchievements = data.achievements || []

    // Update achievements list
    visibleAchievements.value = newAchievements
  } catch (error) {
    // TODO(#91 — see GH issues): also runs for logged-out visitors → 401 noise.
    // Gate this (and weather/connections/sync-status fetches) on authStore.isAuthenticated.
    console.error('Failed to fetch achievements:', error)
  }
}

const markAsRead = async (achievementId) => {
  try {
    await api.post(`/performance/achievements/${achievementId}/mark-read`)
    const index = visibleAchievements.value.findIndex(a => a.id === achievementId)
    if (index !== -1) {
      visibleAchievements.value.splice(index, 1)
    }
  } catch (error) {
    console.error('Failed to mark achievement as read:', error)
  }
}

const markAllAsRead = async () => {
  for (const achievement of visibleAchievements.value) {
    try {
      await api.post(`/performance/achievements/${achievement.id}/mark-read`)
    } catch (error) {
      console.error('Failed to mark achievement as read:', error)
    }
  }
  visibleAchievements.value = []
  showPanel.value = false
}

const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return t('achievements.just_now')
  if (diffMins < 60) return t('achievements.min_ago', { n: diffMins })
  if (diffMins < 1440) return t('achievements.h_ago', { n: Math.floor(diffMins / 60) })
  return t('achievements.d_ago', { n: Math.floor(diffMins / 1440) })
}

onMounted(() => {
  fetchNewAchievements()
  // Poll every 60 seconds (less frequent)
  pollInterval.value = setInterval(fetchNewAchievements, 60000)
})

onUnmounted(() => {
  if (pollInterval.value) {
    clearInterval(pollInterval.value)
  }
})
</script>

<style scoped>
.slide-down-enter-active {
  animation: slide-down 0.3s ease-out;
}

.slide-down-leave-active {
  animation: slide-down 0.2s ease-in reverse;
}

@keyframes slide-down {
  from {
    transform: translateY(-10px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}
</style>
