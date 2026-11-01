<template>
  <aside class="bg-white border-l border-slate-200 w-full lg:w-[24rem] flex-shrink-0 overflow-y-auto">
    <div v-if="!race" class="p-6 text-slate-500 text-sm">
      {{ t('races.empty') }}
    </div>
    <div v-else class="p-4 pt-[max(1rem,env(safe-area-inset-top))] sm:p-6">
      <button
        type="button"
        class="text-sm text-slate-500 hover:text-slate-800 mb-2 -ml-2 px-2 min-h-[44px]"
        @click="$emit('close')"
      >
        ← {{ t('races.detail.back') }}
      </button>

      <h2 class="text-xl font-bold text-slate-900">{{ race.name }}</h2>
      <p class="mt-1 text-sm text-slate-500">
        {{ formatDate(race.date) }}
        <span v-if="race.location"> · {{ race.location }}</span>
        <span v-if="race.country"> · {{ countryName(race.country) }}</span>
        <span v-if="race.date_estimated" class="block text-xs text-amber-700">{{ t('races.detail.dateEstimated') }}</span>
      </p>

      <img
        v-if="race.has_poster"
        :src="`${apiBase}/races/${race.id}/poster`"
        :alt="t('races.detail.poster')"
        class="mt-4 w-full rounded-lg border border-slate-200"
        loading="lazy"
      />

      <div class="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div class="bg-slate-50 rounded-lg p-3">
          <p class="text-xs uppercase tracking-wide text-slate-500">{{ t('races.filters.distance') }}</p>
          <p class="font-semibold text-slate-900 mt-0.5">{{ formatDistance(race.distance_km) }}</p>
        </div>
        <div v-if="race.elev_gain_m != null" class="bg-slate-50 rounded-lg p-3">
          <p class="text-xs uppercase tracking-wide text-slate-500">{{ t('races.filters.elevation') }}</p>
          <p class="font-semibold text-slate-900 mt-0.5">{{ Math.round(race.elev_gain_m) }} m</p>
        </div>
        <div v-if="race.surface" class="bg-slate-50 rounded-lg p-3">
          <p class="text-xs uppercase tracking-wide text-slate-500">{{ t('races.filters.surface') }}</p>
          <p class="font-semibold text-slate-900 mt-0.5">{{ raceLabel('surface', race.surface) }}</p>
        </div>
        <div v-if="race.race_type" class="bg-slate-50 rounded-lg p-3">
          <p class="text-xs uppercase tracking-wide text-slate-500">{{ t('races.filters.type') }}</p>
          <p class="font-semibold text-slate-900 mt-0.5">{{ raceLabel('type', race.race_type) }}</p>
        </div>
        <div v-if="race.itra_points" class="bg-slate-50 rounded-lg p-3 col-span-2">
          <p class="text-xs uppercase tracking-wide text-slate-500">ITRA</p>
          <p class="font-semibold text-slate-900 mt-0.5">{{ t('races.detail.itra_points', { n: race.itra_points }) }}</p>
        </div>
      </div>

      <p v-if="race.description" class="mt-4 text-sm text-slate-700 leading-relaxed">
        {{ race.description }}
      </p>

      <a
        v-if="race.url"
        :href="race.url"
        target="_blank"
        rel="noopener"
        class="mt-3 inline-flex items-center min-h-[44px] text-sm text-blue-700 hover:text-blue-900"
      >
        {{ t('races.detail.officialUrl') }} →
      </a>

      <a
        v-if="race.has_gpx"
        :href="`${apiBase}/races/${race.id}/gpx`"
        class="mt-1 flex items-center min-h-[44px] text-sm text-blue-700 hover:text-blue-900"
      >
        {{ t('races.detail.downloadGpx') }} →
      </a>

      <div class="mt-6 pt-4 border-t border-slate-200">
        <p class="text-sm font-semibold text-slate-900 mb-3">{{ t('races.detail.addAs') }}</p>

        <div v-if="!authStore.isAuthenticated" class="text-sm text-slate-600 bg-amber-50 border border-amber-200 rounded p-3">
          {{ t('auth.signin.required') }}
        </div>

        <template v-else>
          <button
            v-for="p in priorities"
            :key="p.code"
            type="button"
            :disabled="busy"
            class="w-full mb-2 text-left p-3 rounded-lg border transition disabled:opacity-50"
            :class="addedPriority === p.code
              ? 'bg-emerald-50 border-emerald-400 ring-1 ring-emerald-400'
              : 'bg-white border-slate-300 hover:border-slate-400'"
            @click="add(p.code)"
          >
            <div class="flex items-center justify-between">
              <span class="font-bold text-slate-900">{{ p.code }}</span>
              <span v-if="busy && pending === p.code" class="text-xs text-slate-500">
                {{ t('races.detail.addingAs', { priority: p.code }) }}
              </span>
            </div>
            <p class="text-xs text-slate-600 mt-1">{{ p.explain }}</p>
          </button>

          <p v-if="addedPriority" class="text-sm text-emerald-700 mt-3 flex items-center gap-1.5">
            <svg class="w-4 h-4 shrink-0" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> {{ t('races.detail.addedSuccess') }}
          </p>
          <button
            v-if="createdPlan"
            type="button"
            class="mt-3 w-full px-4 py-2 min-h-[44px] rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium"
            @click="goToPlan"
          >
            {{ t('races.detail.openPlan') }} →
          </button>
        </template>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useRacesStore } from '../stores/races'
import { makeRaceLabel } from '../utils/raceLabels'
import api from '../services/api'

const apiBase = api.defaults.baseURL

const props = defineProps({
  race: { type: Object, default: null },
})
defineEmits(['close'])

const { t, te, locale } = useI18n()
const raceLabel = makeRaceLabel(t, te)
const racesStore = useRacesStore()
const authStore = useAuthStore()
const router = useRouter()

const busy = ref(false)
const pending = ref(null)
const addedPriority = ref(null)
const createdPlan = ref(null)

const priorities = computed(() => [
  { code: 'A', explain: t('races.detail.addAsAExplain') },
  { code: 'B', explain: t('races.detail.addAsBExplain') },
  { code: 'C', explain: t('races.detail.addAsCExplain') },
])

async function add(priority) {
  if (!props.race) return
  busy.value = true
  pending.value = priority
  try {
    const res = await racesStore.addToPlan(props.race.id, priority)
    addedPriority.value = priority
    createdPlan.value = res?.plan || null
  } finally {
    busy.value = false
    pending.value = null
  }
}

function goToPlan() {
  if (!createdPlan.value?.id) return
  router.push({ name: 'RaceDashboard', params: { planId: createdPlan.value.id, lang: locale.value } })
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(locale.value, { day: '2-digit', month: 'long', year: 'numeric' })
}

function countryName(code) {
  try { return new Intl.DisplayNames([locale.value], { type: 'region' }).of(code) } catch { return code }
}

function formatDistance(km) {
  if (km == null) return ''
  return km >= 10 ? `${Math.round(km)} km` : `${km.toFixed(1)} km`
}
</script>
