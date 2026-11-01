<template>
  <section class="card stack" aria-labelledby="connections-title">
    <div>
      <h2 id="connections-title" class="text-2xl font-bold">{{ $t('auth.connections.title') }}</h2>
      <p class="section-subtitle mt-1">{{ $t('auth.connections.text') }}</p>
    </div>

    <p v-if="loadError" class="alert alert-error">{{ loadError }}</p>

    <ul class="divide-y divide-slate-200 border-t border-slate-200">
      <li
        v-for="p in providers"
        :key="p.id"
        class="flex flex-wrap items-center justify-between gap-3 py-4"
      >
        <div>
          <p class="font-semibold text-slate-900">{{ p.label }}</p>
          <p class="text-sm" :class="p.connected ? 'text-emerald-700' : 'text-slate-500'">
            {{ p.connected ? $t('auth.connections.connected') : $t('auth.connections.not_connected') }}
            <span v-if="p.connected && p.external_user_id" class="text-slate-400 font-mono text-xs">
              · {{ p.external_user_id }}
            </span>
          </p>
          <p v-if="p.id === 'strava' && syncStore.provider === 'strava' && syncStore.status && syncStore.status !== 'idle'"
             class="text-xs text-slate-500 mt-1">
            {{ syncStore.errorMessage || syncStore.message }}
          </p>
        </div>

        <div v-if="p.connected" class="flex gap-2">
          <button
            v-if="p.id === 'strava'"
            type="button"
            class="btn btn-outline text-xs py-2"
            :disabled="syncStore.isSyncing"
            @click="resync"
          >
            {{ syncStore.isSyncing ? $t('auth.connections.resyncing') : $t('auth.connections.resync') }}
          </button>
          <button
            type="button"
            class="btn btn-outline text-xs py-2"
            :disabled="busy === p.id"
            @click="disconnect(p)"
          >
            {{ busy === p.id ? $t('auth.connections.disconnecting') : $t('auth.connections.disconnect') }}
          </button>
        </div>
        <button
          v-else
          type="button"
          class="btn btn-primary text-xs py-2"
          :disabled="busy === p.id"
          @click="connect(p)"
        >
          {{ busy === p.id ? $t('auth.connections.connecting') : $t('auth.connections.connect') }}
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useToastStore } from '../stores/toast'
import { useSyncStore } from '../stores/sync'
import api from '../services/api'

// ponytail: Strava is the only provider with an OAuth flow today. Phase 3 adds
// rows here; the backend already returns one entry per provider, so extend this
// map (label + connect URL) rather than the rendering.
const KNOWN = { strava: 'Strava' }
const label = (id) => KNOWN[id] || id.charAt(0).toUpperCase() + id.slice(1)

const { t } = useI18n()
const authStore = useAuthStore()
const toastStore = useToastStore()
const syncStore = useSyncStore()

const providers = ref(Object.keys(KNOWN).map(id => ({ id, label: label(id), connected: false })))
const busy = ref(null)
const loadError = ref('')

const load = async () => {
  loadError.value = ''
  try {
    const connections = await authStore.fetchConnections()
    const byProvider = new Map(connections.map(c => [c.provider, c]))
    const ids = [...new Set([...Object.keys(KNOWN), ...byProvider.keys()])]
    providers.value = ids.map(id => {
      const c = byProvider.get(id)
      return {
        id,
        label: label(id),
        connected: c ? c.connected !== false && c.status !== 'revoked' : false,
        external_user_id: c?.external_user_id || null
      }
    })
  } catch (err) {
    loadError.value = t('auth.connections.load_error')
  }
}

onMounted(load)

const connect = async (p) => {
  if (p.id !== 'strava') return
  busy.value = p.id
  try {
    // Backend links the athlete to the current session when one exists.
    window.location.href = await authStore.getStravaAuthUrl()
  } catch (err) {
    busy.value = null
    toastStore.push({ type: 'error', message: t('auth.connections.error') })
  }
}

// Re-reads the last year from Strava (not just runs newer than the last one stored).
const resync = async () => {
  try {
    await api.post('/strava/sync')
  } catch (err) {
    // 409 = already running: just show its progress.
    if (err.response?.status !== 409) {
      toastStore.push({ type: 'error', message: t('auth.connections.error') })
      return
    }
  }
  syncStore.startPolling('strava')
}

const disconnect = async (p) => {
  // ponytail: native confirm(); swap for the app modal if this ever needs copy
  // richer than one sentence.
  if (!window.confirm(t('auth.connections.disconnect_confirm', { provider: p.label }))) return
  busy.value = p.id
  try {
    await authStore.disconnectProvider(p.id)
    toastStore.push({ message: t('auth.connections.disconnected', { provider: p.label }) })
    await load()
  } catch (err) {
    toastStore.push({ type: 'error', message: t('auth.connections.error') })
  } finally {
    busy.value = null
  }
}
</script>
