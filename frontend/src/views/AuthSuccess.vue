<template>
  <div class="card text-center space-y-6">
    <div class="space-y-2">
      <h2 class="section-title text-emerald-600">{{ $t('auth_success.title') }}</h2>
      <p class="text-slate-600">{{ $t('auth_success.subtitle') }}</p>
      <p class="text-slate-500">{{ $t('auth_success.note') }}</p>
      <p class="text-sm text-emerald-600 font-medium">{{ $t('auth_success.safe_to_leave') }}</p>
    </div>

    <div class="space-y-3 text-left">
      <div class="flex items-center justify-between text-xs text-slate-500 uppercase tracking-widest">
        <span>{{ $t('auth_success.status_label') }}</span>
        <span v-if="syncStatus">{{ formatStatus(syncStatus.status) }}</span>
      </div>
      <div class="w-full bg-slate-200 rounded-full h-3 overflow-hidden">
        <div
          class="h-3 rounded-full transition-all duration-500"
          style="background: linear-gradient(120deg, #34d399 0%, #22d3ee 100%);"
          :style="{ width: `${progressPercent}%` }"
        ></div>
      </div>
      <div class="text-sm text-slate-600">
        <span v-if="syncStatus?.message">{{ syncStatus.message }}</span>
        <span v-else>{{ $t('auth_success.preparing') }}</span>
      </div>
      <div v-if="syncStatus?.total_activities" class="text-xs text-slate-500">
        {{ $t('auth_success.activities_downloaded', { downloaded: syncStatus.downloaded_activities, total: syncStatus.total_activities }) }}
      </div>
      <div v-if="syncStatus?.status === 'completed'" class="text-sm text-emerald-600 font-semibold">
        {{ $t('auth_success.completed') }}
      </div>
      <div v-if="syncStatus?.status === 'error'" class="text-sm text-rose-600 font-semibold">
        {{ $t('auth_success.failed') }}
      </div>
      <div v-if="syncError" class="text-xs text-rose-600">{{ syncError }}</div>
    </div>

    <div class="flex flex-col sm:flex-row gap-3 justify-center">
      <button @click="goHome" class="btn btn-primary px-6 py-3">
        {{ $t('auth_success.cta_home') }}
      </button>
      <button @click="checkNow" class="btn btn-outline px-6 py-3" :disabled="polling">
        {{ polling ? $t('auth_success.cta_refreshing') : $t('auth_success.cta_refresh') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useSyncStore } from '../stores/sync'

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const authStore = useAuthStore()
const syncStore = useSyncStore()

const syncStatus = computed(() => ({
  status: syncStore.status,
  message: syncStore.message,
  progress_percent: syncStore.progressPercent,
  total_activities: syncStore.totalActivities,
  downloaded_activities: syncStore.downloadedActivities,
}))

const progressPercent = computed(() => syncStore.progressPercent)
const syncError = computed(() => syncStore.errorMessage)
const polling = computed(() => syncStore.isSyncing)

const formatStatus = (status) => {
  if (!status) return t('auth_success.status_initializing')
  return status.replace('_', ' ')
}

const goHome = () => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  if (useLang) {
    router.push({ name: 'Home', params: { lang: langParam } })
    return
  }
  const storedLang = typeof localStorage === 'undefined' ? null : localStorage.getItem('preferred_lang')
  const fallbackLang = storedLang || locale.value
  if (fallbackLang) {
    router.push({ name: 'Home', params: { lang: fallbackLang } })
    return
  }
  router.push({ name: 'Home' })
}

const checkNow = async () => {
  await syncStore.fetchStatus()
}

// Auto-navigate home on completion
watch(() => syncStore.status, (newStatus) => {
  if (newStatus === 'completed') {
    setTimeout(() => goHome(), 1500)
  }
})

onMounted(async () => {
  // JWT is now delivered via httpOnly cookie (set by backend on redirect)
  await authStore.checkAuthStatus()
  syncStore.startPolling()
})
</script>
