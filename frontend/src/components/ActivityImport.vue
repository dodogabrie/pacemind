<template>
  <section class="card stack" :aria-labelledby="titleId">
    <div>
      <h2 :id="titleId" tabindex="-1" ref="titleEl" class="text-2xl font-bold">
        {{ t('activity_import.title') }}
      </h2>
      <p class="section-subtitle mt-1">{{ t('activity_import.text') }}</p>
    </div>

    <!-- Expectation setting: the vendor export is not instant. -->
    <p class="alert alert-info">{{ t('activity_import.delay_note') }}</p>

    <!-- Dropzone. The <input> is sr-only (not hidden) so it stays in the tab
         order; the <label> is its visible, clickable surface. -->
    <div
      class="border-2 border-dashed rounded-xl p-5 sm:p-8 text-center transition-colors"
      :class="dragover ? 'border-emerald-500 bg-emerald-50/50' : 'border-slate-300'"
      @dragover.prevent="dragover = true"
      @dragleave.prevent="dragover = false"
      @drop.prevent="onDrop"
    >
      <input
        :id="inputId"
        ref="fileInput"
        type="file"
        multiple
        :accept="ACCEPT"
        class="sr-only peer"
        :disabled="busy"
        :aria-describedby="hintId"
        @change="onPick"
      />
      <label
        :for="inputId"
        class="btn btn-primary cursor-pointer peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-600 peer-focus-visible:ring-offset-2 peer-disabled:opacity-50"
      >
        {{ t('activity_import.choose_files') }}
      </label>
      <p class="mt-3 text-sm text-slate-600">{{ t('activity_import.drop_text') }}</p>
      <p :id="hintId" class="mt-1 text-xs text-slate-500">
        {{ t('activity_import.accepts', { formats: ACCEPT, size: maxSizeLabel }) }}
      </p>
    </div>

    <!-- Chosen files, pre-upload -->
    <div v-if="files.length && !busy" class="space-y-3">
      <p class="text-sm text-slate-700">
        {{ t('activity_import.selected', { count: files.length, size: formatSize(totalBytes) }) }}
      </p>
      <ul class="text-xs text-slate-500 font-mono max-h-32 overflow-y-auto space-y-0.5 break-all">
        <li v-for="f in files.slice(0, 20)" :key="f.name">{{ f.name }}</li>
        <li v-if="files.length > 20">{{ t('activity_import.and_more', { count: files.length - 20 }) }}</li>
      </ul>
      <div class="flex gap-3">
        <button type="button" class="btn btn-primary" @click="upload">
          {{ t('activity_import.start') }}
        </button>
        <button type="button" class="btn btn-outline" @click="clearFiles">
          {{ t('activity_import.clear') }}
        </button>
      </div>
    </div>

    <p v-if="error" class="alert alert-error" role="alert">{{ error }}</p>

    <!-- Live progress. Survives reload: the status endpoint is the source of
         truth, this component just re-reads it on mount. -->
    <div v-if="busy" role="status" aria-live="polite" class="space-y-2">
      <p class="text-sm font-semibold text-slate-800">{{ phaseLabel }}</p>
      <progress class="w-full h-2" max="100" :value="percent" :aria-label="phaseLabel">
        {{ percent }}%
      </progress>
      <p class="text-xs text-slate-500">{{ percent }}%</p>
      <button type="button" class="btn btn-outline text-xs py-2" @click="cancel">
        {{ t('activity_import.cancel_import') }}
      </button>
    </div>

    <!-- Partial failure is a success screen, not an error banner. -->
    <div
      v-else-if="summary"
      role="status"
      class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 space-y-2"
    >
      <p class="font-semibold text-emerald-900">
        {{ t('activity_import.done', { imported: summary.imported ?? 0, skipped: skippedFiles.length || summary.skipped || 0 }) }}
      </p>
      <details v-if="skippedFiles.length" class="text-sm">
        <summary class="cursor-pointer text-emerald-800 font-medium">
          {{ t('activity_import.skipped_title', { count: skippedFiles.length }) }}
        </summary>
        <ul class="mt-2 space-y-1">
          <li v-for="s in skippedFiles" :key="s.name" class="flex flex-wrap gap-2">
            <span class="font-mono text-xs text-slate-700 break-all">{{ s.name }}</span>
            <span class="text-xs text-slate-500">— {{ s.reason }}</span>
          </li>
        </ul>
      </details>
      <p class="text-xs text-emerald-800">{{ t('activity_import.done_next') }}</p>
    </div>

    <!-- Per-vendor instructions: native <details>, no accordion library. -->
    <div>
      <h3 class="text-sm font-bold uppercase tracking-wide text-slate-500 mb-2">
        {{ t('activity_import.how_title') }}
      </h3>
      <div class="divide-y divide-slate-200 border-t border-slate-200">
        <details v-for="v in VENDORS" :key="v.id" class="py-3">
          <summary class="cursor-pointer font-semibold text-slate-800 py-1">
            {{ t(`activity_import.vendors.${v.id}.name`) }}
          </summary>
          <div class="mt-2 space-y-1 text-sm text-slate-600">
            <p>{{ t(`activity_import.vendors.${v.id}.route`) }}</p>
            <p class="text-xs text-slate-500">
              {{ t('activity_import.contents', { formats: t(`activity_import.vendors.${v.id}.contents`) }) }}
            </p>
            <a :href="v.url" target="_blank" rel="noopener noreferrer" class="link text-sm">
              {{ t('activity_import.open_export_page') }}
            </a>
          </div>
        </details>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../services/api'
import { useAuthStore } from '../stores/auth'
import { useSyncStore } from '../stores/sync'
import { useToastStore } from '../stores/toast'

// Verified at implementation time; vendors move these, so they live in one list.
const VENDORS = [
  { id: 'garmin', url: 'https://www.garmin.com/en-US/account/datamanagement/exportdata/' },
  { id: 'suunto', url: 'https://www.suunto.com/Support/faq-articles/suunto-app/how-can-i-export-my-data-from-the-suunto-app/' },
  { id: 'polar', url: 'https://flow.polar.com/settings/account' },
  { id: 'coros', url: 'https://t.coros.com/' },
  { id: 'strava', url: 'https://www.strava.com/athlete/delete_your_account' },
]

const ACCEPT = '.zip,.fit,.tcx,.gpx,.gz'
const ALLOWED_RE = /\.(zip|fit|tcx|gpx|gz)$/i
// ponytail: mirrors the backend cap and Nginx client_max_body_size. If those
// move, move this constant — there is no endpoint that reports the limit.
const MAX_TOTAL_BYTES = 512 * 1024 * 1024

const { t } = useI18n()
const authStore = useAuthStore()
const syncStore = useSyncStore()
const toastStore = useToastStore()

const titleId = useId()
const inputId = useId()
const hintId = useId()

const titleEl = ref(null)
const fileInput = ref(null)
const dragover = ref(false)
const files = ref([])
const error = ref('')
const uploading = ref(false)
const uploadPercent = ref(0)

const totalBytes = computed(() => files.value.reduce((n, f) => n + f.size, 0))
const maxSizeLabel = computed(() => formatSize(MAX_TOTAL_BYTES))

const importing = computed(() => syncStore.provider === 'import' && syncStore.isSyncing)
const busy = computed(() => uploading.value || importing.value)
const percent = computed(() =>
  uploading.value ? uploadPercent.value : Math.round(syncStore.progressPercent || 0)
)
const phaseLabel = computed(() =>
  uploading.value
    ? t('activity_import.phase_upload')
    : syncStore.message || t('activity_import.phase_process')
)

const summary = computed(() =>
  syncStore.provider === 'import' && syncStore.status === 'completed' ? syncStore.result : null
)
const skippedFiles = computed(() => summary.value?.skipped_files || [])

const formatSize = (bytes) => {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

const validate = (picked) => {
  const bad = picked.filter((f) => !ALLOWED_RE.test(f.name))
  if (bad.length) {
    error.value = t('activity_import.error_type', { name: bad[0].name })
    return false
  }
  const total = picked.reduce((n, f) => n + f.size, 0)
  if (total > MAX_TOTAL_BYTES) {
    error.value = t('activity_import.error_size', { size: maxSizeLabel.value })
    return false
  }
  return true
}

const accept = (list) => {
  const picked = Array.from(list || [])
  if (!picked.length) return
  error.value = ''
  if (!validate(picked)) return
  files.value = picked
}

const onPick = (event) => accept(event.target.files)

const onDrop = (event) => {
  dragover.value = false
  accept(event.dataTransfer?.files)
}

const clearFiles = () => {
  files.value = []
  error.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

const upload = async () => {
  if (!files.value.length) return
  error.value = ''
  uploading.value = true
  uploadPercent.value = 0
  syncStore.reset()
  const form = new FormData()
  files.value.forEach((f) => form.append('files', f, f.name))
  try {
    await api.post('/activities/import', form, {
      onUploadProgress: (e) =>
        (uploadPercent.value = e.total ? Math.round((e.loaded / e.total) * 100) : 0),
    })
    clearFiles()
    syncStore.startPolling('import')
  } catch (err) {
    error.value = err.response?.data?.error || t('activity_import.error_upload')
  } finally {
    uploading.value = false
  }
}

const cancel = async () => {
  try {
    await api.delete('/activities/import')
    syncStore.stopPolling()
    await syncStore.fetchStatus('import')
    toastStore.push({ message: t('activity_import.cancelled') })
  } catch (err) {
    error.value = err.response?.data?.error || t('activity_import.error_cancel')
  }
}

// Move focus to the heading when the import finishes so screen-reader and
// keyboard users land on the result instead of wherever they were.
watch(summary, async (value, previous) => {
  if (value && !previous) {
    await nextTick()
    titleEl.value?.focus()
  }
})

onMounted(async () => {
  // A 401 must never redirect: we simply skip the status probe when logged out.
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  // ponytail: the status row is the last import, so a long-finished one still
  // renders its summary on mount. Harmless; add a dismiss/ack when it annoys.
  await syncStore.fetchStatus('import')
  if (syncStore.isSyncing) syncStore.startPolling('import')
})

onUnmounted(() => {
  if (syncStore.provider === 'import') syncStore.stopPolling()
})
</script>
