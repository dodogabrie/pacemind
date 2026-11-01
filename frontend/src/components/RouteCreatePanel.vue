<template>
  <div class="create-panel">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-slate-200">
      <h2 class="text-sm font-bold text-slate-900 uppercase tracking-wide">{{ $t('routes.create.title') }}</h2>
      <button @click="$emit('close')" :aria-label="$t('common.buttons.close')" class="w-11 h-11 -my-2 -mr-3 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
      </button>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 px-4 py-2 border-b border-slate-100">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="switchTab(tab.key)"
        class="px-3 py-2.5 sm:py-1.5 text-xs rounded-md transition-colors"
        :class="activeTab === tab.key ? 'bg-emerald-100 text-emerald-800 font-medium' : 'text-slate-500 hover:text-slate-700'"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Scrollable content -->
    <div class="create-content">
      <!-- Draw mode -->
      <template v-if="activeTab === 'draw'">
        <div class="px-4 py-3 space-y-3">
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.name') }}</label>
            <input v-model="routeName" :placeholder="$t('routes.create.name_placeholder_draw')" class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none" />
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.waypoints', { n: waypoints.length }) }}</label>
            <div v-if="waypoints.length === 0" class="text-xs text-slate-400">{{ $t('routes.create.waypoints_hint') }}</div>
            <div v-else class="space-y-1 max-h-32 overflow-y-auto">
              <div v-for="(wp, i) in waypoints" :key="i" class="flex items-center gap-1 text-xs text-slate-600 bg-slate-50 rounded px-2 py-1">
                <span class="w-4 h-4 rounded-full bg-emerald-600 text-white text-[10px] flex items-center justify-center font-bold flex-shrink-0">{{ i + 1 }}</span>
                <span class="flex-1 truncate">{{ wp.lat.toFixed(4) }}, {{ wp.lon.toFixed(4) }}</span>
                <button @click="removeWaypoint(i)" :aria-label="$t('common.buttons.delete')" class="text-slate-400 hover:text-rose-500 flex-shrink-0">&times;</button>
              </div>
            </div>
          </div>

          <label class="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
            <input type="checkbox" v-model="closeLoop" class="rounded border-slate-300 text-emerald-600" />
            {{ $t('routes.create.close_loop') }}
          </label>

          <button v-if="waypoints.length > 0" @click="clearWaypoints" class="text-xs text-slate-400 hover:text-rose-500">
            {{ $t('routes.create.clear_waypoints') }}
          </button>
        </div>
      </template>

      <!-- Loop mode -->
      <template v-if="activeTab === 'loop'">
        <div class="px-4 py-3 space-y-3">
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.name') }}</label>
            <input v-model="routeName" :placeholder="$t('routes.create.name_placeholder_loop')" class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none" />
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.start_point') }}</label>
            <div v-if="!loopCenter" class="text-xs text-slate-400">{{ $t('routes.create.start_hint') }}</div>
            <div v-else class="text-xs text-slate-600 bg-slate-50 rounded px-2 py-1 flex items-center">
              {{ loopCenter.lat.toFixed(4) }}, {{ loopCenter.lon.toFixed(4) }}
              <button @click="clearLoopCenter" class="ml-auto text-slate-400 hover:text-rose-500">&times;</button>
            </div>
          </div>

          <!-- Route type -->
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1.5">{{ $t('routes.create.route_type') }}</label>
            <div class="grid grid-cols-2 gap-1.5">
              <button
                v-for="rt in routeTypes"
                :key="rt.key"
                @click="loopRouteType = rt.key"
                class="flex flex-col items-center gap-0.5 p-2 rounded-lg border text-xs transition-all"
                :class="loopRouteType === rt.key
                  ? 'border-emerald-400 bg-emerald-50 text-emerald-800'
                  : 'border-slate-200 text-slate-500 hover:border-slate-300'"
              >
                <Icon :name="rt.icon" class="!w-4 !h-4" />
                <span class="font-medium">{{ rt.label }}</span>
              </button>
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.target_distance') }}</label>
            <input v-model.number="loopDistance" type="number" step="1" min="1" max="100" class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.target_gain') }}</label>
            <input v-model.number="loopElevation" type="number" step="50" class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none" />
          </div>

          <!-- Direction picker -->
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1.5">{{ $t('routes.create.direction') }}</label>
            <div class="flex items-center gap-3">
              <div class="direction-picker relative w-14 h-14 rounded-full border-2 border-slate-200 bg-slate-50 flex-shrink-0" @click="pickDirection">
                <div class="absolute inset-0 flex items-center justify-center text-[9px] text-slate-400 pointer-events-none">
                  <span class="absolute top-0.5">{{ $t('routes.compass.N') }}</span>
                  <span class="absolute bottom-0.5">{{ $t('routes.compass.S') }}</span>
                  <span class="absolute left-1">{{ $t('routes.compass.W') }}</span>
                  <span class="absolute right-1">{{ $t('routes.compass.E') }}</span>
                </div>
                <div
                  v-if="loopDirection !== null"
                  class="absolute top-1/2 left-1/2 w-0.5 h-5 bg-emerald-600 origin-bottom rounded-full"
                  :style="{ transform: `translate(-50%, -100%) rotate(${loopDirection}deg)` }"
                ></div>
                <div class="absolute top-1/2 left-1/2 w-2 h-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-600"></div>
              </div>
              <div class="text-xs text-slate-500">
                <span v-if="loopDirection === null">{{ $t('routes.create.direction_hint') }}</span>
                <span v-else>
                  {{ directionLabel(loopDirection) }}
                  <button @click="loopDirection = null" class="ml-1 text-slate-400 hover:text-rose-500">{{ $t('routes.create.clear') }}</button>
                </span>
              </div>
            </div>
          </div>

          <button
            @click="generateLoop"
            class="w-full text-sm py-2 px-3 rounded-lg bg-slate-700 text-white hover:bg-slate-800 font-medium transition-colors"
            :disabled="!loopCenter || routing"
          >
            {{ routing ? $t('routes.create.generating') : $t('routes.create.generate') }}
          </button>

          <!-- Loop progress -->
          <div v-if="loopProgress && (loopProgress.iteration > 0 || loopProgress.lastResult)" class="bg-slate-50 rounded-lg p-3 space-y-1.5 border border-slate-200">
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-slate-700">
                {{ $t('routes.create.attempt', { n: loopProgress.iteration, max: loopProgress.max || '?' }) }}
              </span>
              <span v-if="loopProgress.cacheHits > 0" class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">
                cache {{ loopProgress.cacheHits }}×
              </span>
            </div>
            <div class="flex gap-1 h-1.5">
              <div
                v-for="i in (loopProgress.max || 3)"
                :key="i"
                class="flex-1 rounded-full transition-colors"
                :class="i <= loopProgress.iteration ? 'bg-emerald-500' : 'bg-slate-200'"
              ></div>
            </div>
            <div v-if="loopProgress.lastResult" class="text-[11px] text-slate-500 leading-tight pt-1">
              <div>
                <span class="font-medium text-slate-700">{{ loopProgress.lastResult.distance_km }} km</span>
                <span class="ml-1">{{ $t('routes.create.error_pct', { pct: formatPct(loopProgress.lastResult.distance_error_pct) }) }}</span>
              </div>
              <div v-if="loopProgress.lastResult.elev_error_pct != null">
                {{ loopProgress.lastResult.elevation_gain_m }}m D+
                <span class="ml-1">{{ $t('routes.create.error_pct', { pct: formatPct(loopProgress.lastResult.elev_error_pct) }) }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Frequent mode -->
      <template v-if="activeTab === 'frequent'">
        <div class="px-4 py-3 space-y-3">
          <p class="text-xs text-slate-500">{{ $t('routes.create.frequent_intro') }}</p>

          <div v-if="frequentLoading" class="flex items-center gap-2 text-xs text-slate-500">
            <span class="inline-block w-3 h-3 border-2 border-slate-300 border-t-emerald-600 rounded-full animate-spin"></span>
            {{ $t('routes.create.frequent_loading') }}
          </div>

          <div v-else-if="frequentError" class="p-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
            {{ frequentError }}
          </div>

          <div v-else-if="frequentRoutes.length === 0" class="text-xs text-slate-400">
            {{ $t('routes.create.frequent_empty') }}
          </div>

          <div v-else class="space-y-2">
            <div
              v-for="suggestion in frequentRoutes"
              :key="suggestion.cluster_id"
              class="border border-slate-200 rounded-lg p-2.5 hover:border-emerald-400 transition-colors cursor-pointer"
              @mouseenter="previewFrequent(suggestion)"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-1.5 mb-0.5">
                    <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800">
                      {{ suggestion.frequency }}×
                    </span>
                    <span class="text-xs font-medium text-slate-800 truncate">{{ suggestion.name }}</span>
                  </div>
                  <div class="flex gap-2 text-[11px] text-slate-500">
                    <span>{{ suggestion.avg_distance_km }} km</span>
                    <span>{{ suggestion.avg_elevation_gain_m }}m D+</span>
                    <span class="text-slate-400">{{ $t('routes.create.last_run', { date: formatDate(suggestion.last_run_at) }) }}</span>
                  </div>
                </div>
                <button
                  @click.stop="saveFrequent(suggestion)"
                  class="text-[11px] px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700 font-medium flex-shrink-0 disabled:opacity-50"
                  :disabled="frequentSavingId === suggestion.cluster_id"
                >
                  {{ frequentSavingId === suggestion.cluster_id ? '...' : $t('common.buttons.save') }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Import mode -->
      <template v-if="activeTab === 'import'">
        <div class="px-4 py-3 space-y-3">
          <p class="text-xs text-slate-500">{{ $t('routes.create.import_intro') }}</p>
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.strava_id') }}</label>
            <input v-model.number="importActivityId" type="number" :placeholder="$t('routes.create.strava_id_placeholder')" class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">{{ $t('routes.create.name_optional') }}</label>
            <input v-model="importName" :placeholder="$t('routes.create.name_from_activity')" class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none" />
          </div>
          <button
            @click="doImport"
            class="w-full text-sm py-2 px-3 rounded-lg bg-[#FC4C02] text-white hover:bg-[#E34402] font-medium transition-colors"
            :disabled="importing || !importActivityId"
          >
            {{ importing ? $t('routes.create.importing') : $t('routes.create.import') }}
          </button>
        </div>
      </template>

      <!-- Route preview stats -->
      <div v-if="previewStats" class="mx-4 mt-2 bg-slate-50 rounded-lg p-3 space-y-2">
        <div class="text-xs font-medium text-slate-700">{{ $t('routes.create.preview') }}</div>
        <div class="text-lg font-bold text-emerald-700">{{ previewStats.distance_km }} km</div>
        <div class="flex gap-3 text-xs text-slate-500">
          <span>{{ previewStats.elevation_gain_m }}m D+</span>
          <span>{{ previewStats.elevation_loss_m }}m D-</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all" :style="{ width: difficultyPct + '%', background: difficultyColor }"></div>
          </div>
          <span class="text-[10px] font-medium" :style="{ color: difficultyColor }">{{ difficultyLabel }}</span>
        </div>
      </div>

      <!-- Routing indicator -->
      <div v-if="routing" class="mx-4 mt-2 flex items-center gap-2 text-sm text-emerald-700">
        <span class="inline-block w-3 h-3 border-2 border-emerald-300 border-t-emerald-700 rounded-full animate-spin"></span>
        {{ $t('routes.create.routing') }}
      </div>

      <!-- Error -->
      <div v-if="error" class="mx-4 mt-2 p-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
        {{ error }}
      </div>

      <!-- Success -->
      <div v-if="routeSaved" class="mx-4 mt-2 p-2 bg-emerald-50 border border-emerald-200 rounded text-xs text-emerald-700 font-medium text-center">
        {{ $t('routes.create.saved') }}
      </div>
    </div>

    <!-- Save button -->
    <div class="px-4 py-3 border-t border-slate-200">
      <button
        v-if="routeSaved"
        @click="$emit('done')"
        class="w-full text-sm py-2.5 px-3 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 font-semibold transition-colors"
      >
        {{ $t('routes.create.done') }}
      </button>
      <button
        v-else-if="activeTab === 'draw'"
        @click="saveRoute"
        class="w-full text-sm py-2.5 px-3 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!previewStats || saving"
      >
        {{ saving ? $t('routes.create.saving') : $t('routes.create.save') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import Icon from './Icon.vue'
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoutesStore } from '../stores/routes'

const emit = defineEmits(['close', 'done', 'update:createMode', 'update:waypoints', 'update:previewRoute', 'update:loopCenter'])

const props = defineProps({
  mapClick: { type: Object, default: null },
})

const routesStore = useRoutesStore()
const { t, locale } = useI18n()

const tabs = computed(() => [
  { key: 'draw', label: t('routes.create.tabs.draw') },
  { key: 'loop', label: t('routes.create.tabs.loop') },
  { key: 'frequent', label: t('routes.create.tabs.frequent') },
  { key: 'import', label: t('routes.create.tabs.import') },
])

const routeTypes = computed(() => [
  { key: 'loop', label: t('routes.create.types.loop'), icon: 'repeat' },
  { key: 'out_and_back', label: t('routes.create.types.out_and_back'), icon: 'arrow-left-right' },
])

const activeTab = ref('draw')
const routeName = ref('')
const error = ref(null)
const routing = ref(false)
const saving = ref(false)
const routeSaved = ref(false)

// Draw mode
const waypoints = ref([])
const closeLoop = ref(false)
const undoStack = ref([])
const redoStack = ref([])

// Loop mode
const loopCenter = ref(null)
const loopDistance = ref(10)
const loopElevation = ref(null)
const loopRouteType = ref('loop')
const loopDirection = ref(null)
const loopProgress = ref(null)

// Import mode
const importActivityId = ref(null)
const importName = ref('')
const importing = ref(false)

// Frequent mode
const frequentRoutes = ref([])
const frequentLoading = ref(false)
const frequentError = ref(null)
const frequentSavingId = ref(null)

// Preview data
const previewStats = ref(null)
const lastPreviewData = ref(null)
let previewTimer = null

// Difficulty
const difficultyPct = computed(() => {
  if (!previewStats.value) return 0
  const effort = previewStats.value.distance_km + (previewStats.value.elevation_gain_m / 100)
  return Math.min(100, (effort / 60) * 100)
})
const difficultyColor = computed(() => {
  const pct = difficultyPct.value
  if (pct < 25) return '#22c55e'
  if (pct < 50) return '#eab308'
  if (pct < 75) return '#f97316'
  return '#ef4444'
})
const difficultyLabel = computed(() => {
  const pct = difficultyPct.value
  if (pct < 25) return t('routes.difficulty.easy')
  if (pct < 50) return t('routes.difficulty.moderate')
  if (pct < 75) return t('routes.difficulty.hard')
  return t('routes.difficulty.extreme')
})

// Emit mode to parent
const switchTab = (tab) => {
  activeTab.value = tab
  clearState()
  // 'draw' / 'loop' need map clicks; 'import' / 'frequent' don't.
  emit('update:createMode', (tab === 'draw' || tab === 'loop') ? tab : null)
  if (tab === 'frequent' && frequentRoutes.value.length === 0) {
    loadFrequentRoutes()
  }
}

onMounted(() => {
  emit('update:createMode', 'draw')
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer)
  window.removeEventListener('keydown', onKeyDown)
})

const onKeyDown = (e) => {
  if (activeTab.value !== 'draw') return
  if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undoWaypoint() }
  else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); redoWaypoint() }
}

// Handle map clicks from parent
watch(() => props.mapClick, (click) => {
  if (!click) return
  if (activeTab.value === 'draw') {
    pushUndo()
    waypoints.value.push(click)
    redoStack.value = []
    emitWaypoints()
    debouncedPreview()
  } else if (activeTab.value === 'loop') {
    loopCenter.value = click
    emit('update:loopCenter', click)
  }
})

// --- Draw mode ---

const pushUndo = () => {
  undoStack.value.push(JSON.parse(JSON.stringify(waypoints.value)))
  if (undoStack.value.length > 50) undoStack.value.shift()
}

const undoWaypoint = () => {
  if (!undoStack.value.length) return
  redoStack.value.push(JSON.parse(JSON.stringify(waypoints.value)))
  waypoints.value = undoStack.value.pop()
  emitWaypoints()
  if (waypoints.value.length >= 2) debouncedPreview()
  else clearPreview()
}

const redoWaypoint = () => {
  if (!redoStack.value.length) return
  undoStack.value.push(JSON.parse(JSON.stringify(waypoints.value)))
  waypoints.value = redoStack.value.pop()
  emitWaypoints()
  if (waypoints.value.length >= 2) debouncedPreview()
  else clearPreview()
}

const removeWaypoint = (index) => {
  pushUndo()
  waypoints.value.splice(index, 1)
  redoStack.value = []
  emitWaypoints()
  if (waypoints.value.length >= 2) debouncedPreview()
  else clearPreview()
}

const clearWaypoints = () => {
  pushUndo()
  waypoints.value = []
  redoStack.value = []
  emitWaypoints()
  clearPreview()
}

const emitWaypoints = () => {
  emit('update:waypoints', [...waypoints.value])
}

const debouncedPreview = () => {
  if (previewTimer) clearTimeout(previewTimer)
  if (waypoints.value.length < 2) return
  previewTimer = setTimeout(fetchPreview, 400)
}

const fetchPreview = async () => {
  if (waypoints.value.length < 2) return
  routing.value = true
  error.value = null

  let wps = [...waypoints.value]
  if (closeLoop.value && wps.length >= 2) wps.push(wps[0])

  try {
    const data = await routesStore.previewRoute(wps)
    if (data.route_data) {
      previewStats.value = {
        distance_km: data.distance_km,
        elevation_gain_m: data.elevation_gain_m,
        elevation_loss_m: data.elevation_loss_m,
      }
      lastPreviewData.value = data
      emit('update:previewRoute', data.route_data)
    }
  } catch (err) {
    error.value = err.response?.data?.error || err.message
  } finally {
    routing.value = false
  }
}

watch(closeLoop, () => {
  if (waypoints.value.length >= 2) fetchPreview()
})

// --- Loop mode ---

const clearLoopCenter = () => {
  loopCenter.value = null
  emit('update:loopCenter', null)
  clearPreview()
}

const pickDirection = (e) => {
  const rect = e.currentTarget.getBoundingClientRect()
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  const dx = e.clientX - cx
  const dy = e.clientY - cy
  let deg = Math.atan2(dx, -dy) * 180 / Math.PI
  if (deg < 0) deg += 360
  loopDirection.value = Math.round(deg)
}

const directionLabel = (deg) => {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return t(`routes.compass.${dirs[Math.round(deg / 45) % 8]}`) + ` (${deg}\u00B0)`
}

const generateLoop = async () => {
  if (!loopCenter.value) return
  routing.value = true
  error.value = null
  loopProgress.value = { iteration: 0, max: 0, lastResult: null, cacheHits: 0 }

  try {
    const data = await routesStore.generateRouteStreaming(
      {
        name: routeName.value || `${loopDistance.value}km ${t(`routes.create.types.${loopRouteType.value}`).toLowerCase()}`,
        center_lat: loopCenter.value.lat,
        center_lon: loopCenter.value.lon,
        target_distance_km: loopDistance.value,
        target_elevation_m: loopElevation.value,
        route_type: loopRouteType.value,
        preferred_direction: loopDirection.value,
      },
      onLoopProgress,
    )
    if (data?.route_data) {
      previewStats.value = {
        distance_km: data.distance_km,
        elevation_gain_m: data.elevation_gain_m,
        elevation_loss_m: data.elevation_loss_m,
      }
      emit('update:previewRoute', data.route_data)
    }
    routeSaved.value = true
  } catch (err) {
    error.value = err.message
  } finally {
    routing.value = false
  }
}

const onLoopProgress = (event) => {
  if (!loopProgress.value) return
  if (event.type === 'attempt') {
    loopProgress.value.iteration = event.iteration
    loopProgress.value.max = event.max_iterations
  } else if (event.type === 'result') {
    loopProgress.value.lastResult = {
      distance_km: event.distance_km,
      elevation_gain_m: event.elevation_gain_m,
      distance_error_pct: event.distance_error_pct,
      elev_error_pct: event.elev_error_pct,
      cached: event.cached,
    }
    if (event.cached) loopProgress.value.cacheHits += 1
  }
}

const formatPct = (v) => v == null ? '–' : `${(v * 100).toFixed(0)}%`

// --- Frequent routes ---

const loadFrequentRoutes = async () => {
  frequentLoading.value = true
  frequentError.value = null
  try {
    frequentRoutes.value = await routesStore.fetchFrequentRoutes(10)
  } catch (err) {
    frequentError.value = err.message
  } finally {
    frequentLoading.value = false
  }
}

const saveFrequent = async (suggestion) => {
  frequentSavingId.value = suggestion.cluster_id
  error.value = null
  try {
    await routesStore.importFromStrava(
      suggestion.representative_strava_id,
      suggestion.name,
    )
    routeSaved.value = true
  } catch (err) {
    error.value = err.response?.data?.error || err.message
  } finally {
    frequentSavingId.value = null
  }
}

const previewFrequent = (suggestion) => {
  if (!suggestion.thumbnail || suggestion.thumbnail.length < 2) return
  emit('update:previewRoute', suggestion.thumbnail.map(p => ({
    lat: p.lat, lon: p.lon, elevation: 0, distance: 0,
  })))
}

const formatDate = (iso) => {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(locale.value)
  } catch (e) { return '' }
}

// --- Import ---

const doImport = async () => {
  importing.value = true
  error.value = null
  try {
    await routesStore.importFromStrava(importActivityId.value, importName.value)
    routeSaved.value = true
  } catch (err) {
    error.value = err.response?.data?.error || err.message
  } finally {
    importing.value = false
  }
}

// --- Save drawn route ---

const saveRoute = async () => {
  if (!lastPreviewData.value) return
  saving.value = true
  error.value = null

  let wps = [...waypoints.value]
  if (closeLoop.value && wps.length >= 2) wps.push(wps[0])

  try {
    await routesStore.generateFromWaypoints(
      wps.map(w => [w.lat, w.lon]),
      routeName.value || t('routes.create.custom_route'),
    )
    routeSaved.value = true
  } catch (err) {
    error.value = err.response?.data?.error || err.message
  } finally {
    saving.value = false
  }
}

// --- Cleanup ---

const clearPreview = () => {
  previewStats.value = null
  lastPreviewData.value = null
  emit('update:previewRoute', null)
}

const clearState = () => {
  waypoints.value = []
  undoStack.value = []
  redoStack.value = []
  loopCenter.value = null
  error.value = null
  routeSaved.value = false
  loopProgress.value = null
  clearPreview()
  emit('update:waypoints', [])
  emit('update:loopCenter', null)
}

defineExpose({
  undoWaypoint,
  redoWaypoint,
  canUndo: computed(() => undoStack.value.length > 0),
  canRedo: computed(() => redoStack.value.length > 0),
  isDrawMode: computed(() => activeTab.value === 'draw'),
})
</script>

<style scoped>
.create-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 340px;
  background: white;
  z-index: 1050;
  display: flex;
  flex-direction: column;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.1);
}

.create-content {
  flex: 1;
  overflow-y: auto;
}

.direction-picker {
  cursor: crosshair;
}

@media (max-width: 640px) {
  /* Phones: bottom sheet over the lower part of the map so the map stays usable above it. */
  .create-panel {
    top: auto;
    left: 0;
    right: 0;
    width: 100%;
    height: 55%;
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.15);
    padding-bottom: env(safe-area-inset-bottom);
  }
}
</style>
