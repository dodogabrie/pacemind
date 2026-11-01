<template>
  <div class="min-h-screen bg-slate-50">
    <section class="py-10 bg-gradient-to-b from-white to-slate-50 border-b border-slate-200">
      <div class="layout">
        <h1 class="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">
          {{ t('races.title') }}
        </h1>
        <p class="mt-2 text-slate-600 max-w-2xl">
          {{ t('races.subtitle') }}
        </p>
      </div>
    </section>

    <section class="py-8">
      <div class="layout grid lg:grid-cols-[18rem_1fr] gap-6">
        <!-- Filter sidebar -->
        <aside class="min-w-0 bg-white rounded-xl border border-slate-200 p-4 lg:sticky lg:top-4 lg:self-start [&_input]:min-w-0 [&_input]:min-h-[44px] [&_select]:min-h-[44px] lg:[&_input]:min-h-0 lg:[&_select]:min-h-0">
          <div class="flex items-center justify-between" :class="{ 'mb-4': filtersOpen }">
            <!-- Mobile: the filter block collapses behind its own title so results are visible first. -->
            <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wide">
              <button
                type="button"
                class="flex items-center gap-2 min-h-[44px] -my-2 uppercase tracking-wide lg:pointer-events-none lg:min-h-0 lg:my-0"
                :aria-expanded="filtersOpen"
                @click="filtersOpen = !filtersOpen"
              >
                {{ t('races.filters.title') }}
                <svg class="w-4 h-4 transition-transform lg:hidden" :class="{ 'rotate-180': filtersOpen }" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
              </button>
            </h2>
            <button
              v-show="filtersOpen"
              type="button"
              class="text-xs text-slate-500 hover:text-slate-800 min-h-[44px] px-2 -mr-2 -my-2 lg:min-h-0"
              @click="reset"
            >
              {{ t('races.filters.reset') }}
            </button>
          </div>

          <div v-show="filtersOpen">
          <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.search') }}</label>
          <input
            v-model="local.q"
            type="text"
            class="w-full mb-4 px-3 py-2 text-sm rounded border border-slate-300"
            :placeholder="t('races.filters.searchPlaceholder')"
            @input="onFilterChanged"
          />

          <div class="grid grid-cols-2 gap-2 mb-4">
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.from') }}</label>
              <input v-model="local.start_date" type="date" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @change="onFilterChanged" />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.to') }}</label>
              <input v-model="local.end_date" type="date" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @change="onFilterChanged" />
            </div>
          </div>

          <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.country') }}</label>
          <select v-model="local.country" class="w-full mb-4 px-3 py-2 text-sm rounded border border-slate-300" @change="onFilterChanged">
            <option value="">{{ t('races.filters.any') }}</option>
            <option v-for="code in COUNTRY_CODES" :key="code" :value="code">{{ countryName(code) }}</option>
          </select>

          <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.distance') }}</label>
          <div class="grid grid-cols-2 gap-2 mb-4">
            <input v-model="local.min_distance_km" type="number" min="0" :placeholder="t('races.filters.min')" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @input="onFilterChanged" />
            <input v-model="local.max_distance_km" type="number" min="0" :placeholder="t('races.filters.max')" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @input="onFilterChanged" />
          </div>

          <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.elevation') }}</label>
          <div class="grid grid-cols-2 gap-2 mb-4">
            <input v-model="local.min_elev_m" type="number" min="0" :placeholder="t('races.filters.min')" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @input="onFilterChanged" />
            <input v-model="local.max_elev_m" type="number" min="0" :placeholder="t('races.filters.max')" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @input="onFilterChanged" />
          </div>

          <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.surface') }}</label>
          <select v-model="local.surface" class="w-full mb-4 px-3 py-2 text-sm rounded border border-slate-300" @change="onFilterChanged">
            <option value="">{{ t('races.filters.any') }}</option>
            <option value="asphalt">{{ t('races.surface.asphalt') }}</option>
            <option value="trail">{{ t('races.surface.trail') }}</option>
            <option value="mixed">{{ t('races.surface.mixed') }}</option>
          </select>

          <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.type') }}</label>
          <select v-model="local.race_type" class="w-full mb-4 px-3 py-2 text-sm rounded border border-slate-300" @change="onFilterChanged">
            <option value="">{{ t('races.filters.any') }}</option>
            <option value="road">{{ t('races.type.road') }}</option>
            <option value="trail">{{ t('races.type.trail') }}</option>
            <option value="ultra">{{ t('races.type.ultra') }}</option>
            <option value="vertical">{{ t('races.type.vertical') }}</option>
          </select>

          <div v-if="store.hasNearMe" class="mt-2 pt-4 border-t border-slate-200">
            <label class="flex items-center text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" v-model="local.near_me" class="mr-2" @change="onFilterChanged" />
              {{ t('races.filters.nearMe') }}
              <span v-if="store.preferences?.training_base_name" class="ml-1 text-slate-500 text-xs">
                ({{ store.preferences.training_base_name }})
              </span>
            </label>
            <div v-if="local.near_me" class="mt-3">
              <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.maxTravelKm') }}</label>
              <input v-model="local.max_travel_km" type="number" min="10" max="2000" class="w-full px-2 py-2 text-sm rounded border border-slate-300" @input="onFilterChanged" />
            </div>
          </div>

          <div class="mt-4 pt-4 border-t border-slate-200">
            <label class="block text-xs font-medium text-slate-600 mb-1">{{ t('races.filters.sort') }}</label>
            <select v-model="local.sort" class="w-full px-3 py-2 text-sm rounded border border-slate-300" @change="onFilterChanged">
              <option value="date">{{ t('races.sort.date') }}</option>
              <option value="distance">{{ t('races.sort.distance') }}</option>
              <option value="fit_score" :disabled="!local.near_me">{{ t('races.sort.fitScore') }}</option>
            </select>
          </div>
          </div>
        </aside>

        <!-- Result list / map -->
        <div class="min-w-0">
          <div class="flex items-center justify-between mb-4">
            <p class="text-sm text-slate-600">
              {{ store.loading ? t('races.loading') : t('races.found', { n: store.races.length }) }}
            </p>
            <div class="inline-flex rounded-lg border border-slate-300 bg-white overflow-hidden text-sm">
              <button
                type="button"
                class="px-3 py-1.5 min-h-[44px] lg:min-h-0"
                :class="view === 'list' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-50'"
                @click="view = 'list'"
              >
                {{ t('races.viewList') }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 min-h-[44px] lg:min-h-0 border-l border-slate-300"
                :class="view === 'map' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-50'"
                @click="view = 'map'"
              >
                {{ t('races.viewMap') }}
              </button>
            </div>
          </div>

          <div v-if="store.error" class="bg-red-50 text-red-700 px-4 py-3 rounded mb-4 text-sm">
            {{ store.error }}
          </div>

          <div v-if="view === 'map'" class="bg-white rounded-xl border border-slate-200 isolate overflow-hidden h-[60vh] min-h-[320px]">
            <RacesMap
              :races="store.races"
              :selected-race-id="selectedId"
              :training-location="trainingLocation"
              @race-click="open"
            />
          </div>

          <ul v-else class="space-y-3">
            <li
              v-for="race in store.races"
              :key="race.id"
              class="bg-white rounded-xl border border-slate-200 hover:border-slate-300 hover:shadow-sm transition p-4 cursor-pointer"
              :class="{ 'ring-2 ring-blue-400': race.id === selectedId }"
              @click="open(race)"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0">
                  <h3 class="font-semibold text-slate-900 truncate">{{ race.name }}</h3>
                  <p class="text-sm text-slate-500 mt-0.5 truncate">
                    {{ formatDate(race.date) }}
                    <span v-if="race.location"> · {{ race.location }}</span>
                    <span v-if="race.country"> · {{ race.country }}</span>
                  </p>
                  <div class="mt-2 flex flex-wrap gap-2 text-xs">
                    <span class="px-2 py-1 rounded bg-slate-100 text-slate-700">
                      {{ formatDistance(race.distance_km) }}
                    </span>
                    <span v-if="race.elev_gain_m" class="px-2 py-1 rounded bg-slate-100 text-slate-700">
                      D+ {{ Math.round(race.elev_gain_m) }} m
                    </span>
                    <span v-if="race.surface" class="px-2 py-1 rounded bg-slate-100 text-slate-700">
                      {{ raceLabel('surface', race.surface) }}
                    </span>
                    <span v-if="race.race_type" class="px-2 py-1 rounded bg-slate-100 text-slate-700">
                      {{ raceLabel('type', race.race_type) }}
                    </span>
                    <span
                      v-if="race.distance_from_base_km != null"
                      class="px-2 py-1 rounded bg-blue-50 text-blue-700"
                    >
                      ~{{ Math.round(race.distance_from_base_km) }} km {{ t('races.filters.fromBase') }}
                    </span>
                  </div>
                </div>
                <div v-if="race.fit_score != null" class="text-right shrink-0">
                  <div class="text-2xl font-bold text-emerald-700">
                    {{ Math.round(race.fit_score * 100) }}
                  </div>
                  <div class="text-xs text-slate-500">{{ t('races.fitScore') }}</div>
                </div>
              </div>
            </li>
          </ul>

          <div v-if="!store.loading && store.races.length === 0" class="text-center text-slate-500 py-12">
            <p v-if="store.discoverEmpty">{{ t('races.discoverNone', { q: local.q }) }}</p>
            <p v-else>{{ t('races.empty') }}</p>
            <template v-if="local.q && local.q.trim().length >= 3">
              <p v-if="store.discovering" class="mt-4 text-sm">{{ t('races.discovering') }}</p>
              <button
                v-else-if="authStore.isAuthenticated"
                type="button"
                class="mt-4 px-4 py-2 min-h-[44px] rounded-lg bg-slate-900 text-white text-sm hover:bg-slate-700"
                @click="store.discover(local.q.trim())"
              >
                {{ t('races.discover') }}
              </button>
              <p v-else class="mt-4 text-sm">{{ t('races.discoverLogin') }}</p>
            </template>
          </div>
        </div>
      </div>
    </section>

    <!-- Detail panel slide-in -->
    <transition name="slide">
      <div
        v-if="store.currentRace"
        class="fixed inset-y-0 right-0 w-full max-w-md bg-white border-l border-slate-200 shadow-2xl z-[55] overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom)]"
      >
        <RaceDetailPanel :race="store.currentRace" @close="closeDetail" />
      </div>
    </transition>
    <div
      v-if="store.currentRace"
      class="fixed inset-0 bg-black/30 z-[54]"
      @click="closeDetail"
    ></div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRacesStore } from '../stores/races'
import { useAuthStore } from '../stores/auth'
import { makeRaceLabel } from '../utils/raceLabels'
import RacesMap from '../components/RacesMap.vue'
import RaceDetailPanel from '../components/RaceDetailPanel.vue'

const { t, te, locale } = useI18n()
const raceLabel = makeRaceLabel(t, te)
const COUNTRY_CODES = ['IT', 'FR', 'CH', 'DE', 'ES', 'GB', 'PT', 'US', 'BG']
// ponytail: Intl.DisplayNames localises country names, no per-country keys needed.
const countryName = (code) => new Intl.DisplayNames([locale.value], { type: 'region' }).of(code)
const store = useRacesStore()
const authStore = useAuthStore()
const local = reactive({ ...store.filters })
const view = ref('list')
// Filters start collapsed on phones (< lg) so the list is the first thing seen.
const filtersOpen = ref(typeof window === 'undefined' || window.matchMedia('(min-width: 1024px)').matches)

const selectedId = computed(() => store.currentRace?.id ?? null)
const trainingLocation = computed(() => {
  const p = store.preferences
  if (!p?.training_base_lat || !p?.training_base_lon) return null
  return { lat: p.training_base_lat, lon: p.training_base_lon, name: p.training_base_name }
})

function closeDetail() {
  store.currentRace = null
}

let debounceTimer = null

function onFilterChanged() {
  for (const k of Object.keys(local)) {
    store.setFilter(k, local[k])
  }
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => store.fetchRaces(), 250)
}

function reset() {
  store.resetFilters()
  Object.assign(local, store.filters)
  store.fetchRaces()
}

function open(race) {
  store.fetchRace(race.id)
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(locale.value, { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatDistance(km) {
  if (km == null) return ''
  return km >= 10 ? `${Math.round(km)} km` : `${km.toFixed(1)} km`
}

watch(() => store.filters, (f) => {
  for (const k of Object.keys(f)) local[k] = f[k]
}, { deep: true })

onMounted(async () => {
  // /api/races is public, so anonymous browsing is fully supported here.
  // Only the "near me" defaults come from the user's saved preferences, so
  // skip that call entirely when logged out rather than firing a known 401.
  await authStore.ensureAuthReady()
  if (authStore.isAuthenticated) {
    await store.fetchPreferences()
  }
  Object.assign(local, store.filters)
  await store.fetchRaces()
})
</script>

<style scoped>
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
