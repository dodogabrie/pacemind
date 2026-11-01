import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../services/api'
import i18n from '../i18n'

// The backend writes sync/import status lines in English (sync_status.message).
// ponytail: regex map over those fixed strings; move to message_key + params
// on the backend if the list grows or the wording changes often.
const MESSAGE_KEYS = [
  [/^Fetching and scoring/, 'fetching'],
  [/^Found 0 activities/, 'none_found'],
  [/^No new activities found/, 'up_to_date'],
  [/^Training advanced ML model/, 'training_ml'],
  [/^Learning your running parameters/, 'learning_params'],
  [/^Training your personal model/, 'training_model'],
  [/^Model trained with (\d+) activities/, 'trained'],
  [/^Downloading (\d+) most relevant/, 'downloading'],
  [/^Downloaded (\d+)\/(\d+) activities/, 'downloaded'],
  [/^Reading your export/, 'reading_export'],
  [/^Imported (\d+) activities\.\.\./, 'importing'],
  [/^Import cancelled after (\d+) activities/, 'import_cancelled'],
  [/^(\d+) imported, (\d+) skipped$/, 'imported_skipped'],
  [/^(\d+) imported$/, 'imported'],
]

export const translateSyncMessage = (msg) => {
  if (!msg) return msg
  for (const [re, key] of MESSAGE_KEYS) {
    const m = msg.match(re)
    if (m) return i18n.global.t(`sync.${key}`, { a: m[1], b: m[2] })
  }
  return msg
}

// Both endpoints are backed by the same `sync_status` row, now keyed by
// (user_id, provider), so one store renders both.
const STATUS_URLS = {
  strava: '/strava/sync-status',
  import: '/activities/import/status',
}

export const useSyncStore = defineStore('sync', () => {
  const provider = ref('strava')
  const status = ref(null)
  const message = ref(null)
  const progressPercent = ref(0)
  const totalActivities = ref(null)
  const downloadedActivities = ref(null)
  const errorMessage = ref(null)
  // Import result summary: { imported, skipped, skipped_files: [{name, reason}] }
  const result = ref(null)
  let pollTimer = null

  const isSyncing = computed(() => status.value === 'syncing')

  const fetchStatus = async (p = provider.value) => {
    provider.value = p
    try {
      const response = await api.get(STATUS_URLS[p] || STATUS_URLS.strava)
      const data = response.data
      status.value = data.status
      message.value = translateSyncMessage(data.message) || null
      progressPercent.value = data.progress_percent ?? 0
      totalActivities.value = data.total_activities || null
      downloadedActivities.value = data.downloaded_activities || null
      result.value = data.result || data.summary || null
      errorMessage.value = null

      if (data.status === 'completed' || data.status === 'error') {
        if (data.status === 'error') {
          errorMessage.value = translateSyncMessage(data.message) || i18n.global.t('sync.failed')
        }
        stopPolling()
      }
    } catch (error) {
      errorMessage.value = error.response?.data?.error || i18n.global.t('sync.status_failed')
      stopPolling()
    }
  }

  // ponytail: one timer, one provider at a time — a user does not run a Strava
  // sync and a file import concurrently in practice. Give the store a
  // per-provider map if that ever stops being true.
  const startPolling = (p = 'strava') => {
    if (pollTimer && provider.value === p) return
    stopPolling()
    fetchStatus(p)
    pollTimer = setInterval(() => fetchStatus(p), 2000)
  }

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const reset = () => {
    stopPolling()
    status.value = null
    message.value = null
    progressPercent.value = 0
    totalActivities.value = null
    downloadedActivities.value = null
    errorMessage.value = null
    result.value = null
  }

  return {
    provider,
    status,
    message,
    progressPercent,
    totalActivities,
    downloadedActivities,
    errorMessage,
    result,
    isSyncing,
    fetchStatus,
    startPolling,
    stopPolling,
    reset,
  }
})
