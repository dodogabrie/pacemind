<template>
  <div class="routes-fullscreen">
    <AuthGate
      v-if="authStore.authChecked && !authStore.isAuthenticated"
      :title="$t('auth.routes.title')"
      :text="$t('auth.routes.text')"
      class="routes-gate"
    />

    <div v-else-if="!authStore.authChecked" class="routes-booting">
      {{ $t('common.loading') }}
    </div>

    <template v-else>
    <!-- Map (fills entire area) -->
    <RoutesMap
      :routes="sortedRoutes"
      :selected-route-id="selectedRoute?.id"
      :selected-route-full="selectedRoute"
      :hovered-point="hoveredPoint"
      :training-location="routesStore.trainingLocation"
      :create-mode="createMode"
      :create-waypoints="createWaypoints"
      :create-preview-route="createPreviewRoute"
      :create-loop-center="createLoopCenter"
      @route-click="onRouteClick"
      @map-click="onMapClick"
    />

    <!-- Floating toolbar -->
    <div class="toolbar" :class="{ 'toolbar--creating': creating }">
      <!-- Panel toggle (only when not creating) -->
      <button
        v-if="!panelOpen && !creating"
        @click="panelOpen = true"
        class="toolbar-btn"
        :title="$t('routes.show_list')" :aria-label="$t('routes.show_list')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h18"/><path d="M3 6h18"/><path d="M3 18h18"/></svg>
      </button>

      <div class="flex-1"></div>

      <button v-if="!creating" @click="showLocations = true" class="toolbar-btn" :title="$t('locations.title')" :aria-label="$t('locations.title')">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/><circle cx="12" cy="12" r="2"/></svg>
      </button>

      <!-- Training location -->
      <div v-if="!routesStore.hasTrainingLocation && !creating" class="relative">
        <button
          @click="showLocationSetup = !showLocationSetup"
          class="toolbar-btn"
          :title="$t('routes.location.set')" :aria-label="$t('routes.location.set')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
        </button>
        <div v-if="showLocationSetup" class="location-popover">
          <p class="text-xs text-slate-600 mb-2">{{ $t('routes.location.hint') }}</p>
          <div class="relative mb-2">
            <input
              v-model="locationSearch"
              @keydown.enter="searchTrainingLocation"
              :placeholder="$t('routes.location.search')"
              class="w-full text-sm px-3 py-1.5 rounded border border-slate-200 focus:border-emerald-400 outline-none"
            />
            <div v-if="locationResults.length > 0" class="absolute z-10 mt-1 w-full bg-white rounded-lg shadow-lg border border-slate-200 max-h-36 overflow-y-auto">
              <button
                v-for="(r, i) in locationResults"
                :key="i"
                @click="pickTrainingLocation(r)"
                class="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-emerald-50 border-b border-slate-100 last:border-0"
              >
                {{ r.display_name }}
              </button>
            </div>
          </div>
          <div v-if="locationName" class="text-xs text-slate-500 mb-2">{{ locationName }}</div>
          <button @click="saveLocation" class="w-full text-xs py-1.5 px-3 rounded bg-emerald-600 text-white hover:bg-emerald-700 transition-colors" :disabled="!locationLat || !locationLon">
            {{ $t('routes.location.save') }}
          </button>
        </div>
      </div>

      <!-- Create route button (hidden when already creating) -->
      <button v-if="!creating" @click="startCreating" class="create-route-btn">
        {{ $t('routes.new_route') }}
      </button>
    </div>

    <TrainingLocationsEditor v-if="showLocations" @close="showLocations = false" />

    <!-- Floating undo/redo on map (create draw mode) -->
    <div v-if="creating && createPanelRef?.isDrawMode && createWaypoints.length > 0" class="map-undo-redo">
      <button
        @click="createPanelRef?.undoWaypoint()"
        :disabled="!createPanelRef?.canUndo"
        class="map-action-btn"
        :class="createPanelRef?.canUndo ? '' : 'disabled'"
        :title="$t('routes.undo')" :aria-label="$t('routes.undo')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg>
      </button>
      <button
        @click="createPanelRef?.redoWaypoint()"
        :disabled="!createPanelRef?.canRedo"
        class="map-action-btn"
        :class="createPanelRef?.canRedo ? '' : 'disabled'"
        :title="$t('routes.redo')" :aria-label="$t('routes.redo')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 14 20 9 15 4"/><path d="M4 20v-7a4 4 0 0 1 4-4h12"/></svg>
      </button>
    </div>

    <!-- Map instruction overlay (create mode) -->
    <div v-if="creating && createWaypoints.length === 0 && createMode === 'draw'" class="map-hint">
      {{ $t('routes.hint_draw') }}
    </div>
    <div v-if="creating && !createLoopCenter && createMode === 'loop'" class="map-hint">
      {{ $t('routes.hint_loop') }}
    </div>

    <!-- Left panel: route list (hidden when creating) -->
    <Transition name="slide-left">
      <RoutesPanel
        v-if="panelOpen && !creating"
        :routes="sortedRoutes"
        :selected-route-id="selectedRoute?.id"
        v-model:searchText="searchText"
        v-model:sortBy="sortBy"
        :active-tag-filters="activeTagFilters"
        :available-tags="availableTags"
        @route-click="onRouteClick"
        @toggle-tag="toggleTagFilter"
        @close="panelOpen = false"
      />
    </Transition>

    <!-- Right panel: route detail (browse mode) -->
    <Transition name="slide-right">
      <RouteDetailPanel
        v-if="selectedRoute && !creating"
        :route="selectedRoute"
        @close="selectedRoute = null"
        @delete="deleteRoute"
        @toggle-favorite="toggleSelectedFavorite"
        @hover-point="onHoverPoint"
      />
    </Transition>

    <!-- Right panel: route creation -->
    <Transition name="slide-right">
      <RouteCreatePanel
        v-if="creating"
        ref="createPanelRef"
        :map-click="lastMapClick"
        @close="stopCreating"
        @done="onCreated"
        @update:createMode="createMode = $event"
        @update:waypoints="createWaypoints = $event"
        @update:previewRoute="createPreviewRoute = $event"
        @update:loopCenter="createLoopCenter = $event"
      />
    </Transition>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoutesStore } from '../stores/routes'
import { useAuthStore } from '../stores/auth'
import AuthGate from '../components/AuthGate.vue'
import RoutesMap from '../components/RoutesMap.vue'
import RoutesPanel from '../components/RoutesPanel.vue'
import RouteDetailPanel from '../components/RouteDetailPanel.vue'
import RouteCreatePanel from '../components/RouteCreatePanel.vue'
import TrainingLocationsEditor from '../components/TrainingLocationsEditor.vue'

const routesStore = useRoutesStore()
const { t } = useI18n()
const authStore = useAuthStore()
const selectedRoute = ref(null)
const hoveredPointIdx = ref(null)

const hoveredPoint = computed(() => {
  if (hoveredPointIdx.value == null || !selectedRoute.value?.route_data) return null
  const pt = selectedRoute.value.route_data[hoveredPointIdx.value]
  if (!pt) return null
  return { lat: pt.lat, lon: pt.lon, elevation: pt.elevation, distance: pt.distance }
})

const onHoverPoint = (idx) => { hoveredPointIdx.value = idx }
const panelOpen = ref(true)
const showLocationSetup = ref(false)
const showLocations = ref(false)
const createPanelRef = ref(null)

// Create mode state
const creating = ref(false)
const createMode = ref(null)
const createWaypoints = ref([])
const createPreviewRoute = ref(null)
const createLoopCenter = ref(null)
const lastMapClick = ref(null)

// Training location
const locationName = ref('')
const locationLat = ref(null)
const locationLon = ref(null)
const locationSearch = ref('')
const locationResults = ref([])

// Search & Sort
const searchText = ref('')
const sortBy = ref('recent')
const activeTagFilters = ref([])

const availableTags = computed(() => {
  const tagSet = new Set()
  routesStore.routes.forEach(r => {
    (r.tags || []).forEach(t => { if (t !== 'favorite') tagSet.add(t) })
  })
  return Array.from(tagSet).sort()
})

const toggleTagFilter = (tag) => {
  const idx = activeTagFilters.value.indexOf(tag)
  if (idx >= 0) activeTagFilters.value.splice(idx, 1)
  else activeTagFilters.value.push(tag)
}

const sortedRoutes = computed(() => {
  let routes = [...routesStore.routes]

  if (searchText.value.trim()) {
    const q = searchText.value.toLowerCase()
    routes = routes.filter(r =>
      r.name?.toLowerCase().includes(q) ||
      (r.tags || []).some(t => t.toLowerCase().includes(q))
    )
  }

  if (activeTagFilters.value.length > 0) {
    routes = routes.filter(r =>
      activeTagFilters.value.every(tag => (r.tags || []).includes(tag))
    )
  }

  const favFirst = (a, b) => {
    const aFav = (a.tags || []).includes('favorite') ? 1 : 0
    const bFav = (b.tags || []).includes('favorite') ? 1 : 0
    return bFav - aFav
  }

  const difficulty = (route) => {
    const d = route.distance_km || 0
    const e = route.elevation_gain_m || 0
    return d + (e / 100)
  }

  switch (sortBy.value) {
    case 'distance_asc':
      routes.sort((a, b) => favFirst(a, b) || (a.distance_km || 0) - (b.distance_km || 0))
      break
    case 'distance_desc':
      routes.sort((a, b) => favFirst(a, b) || (b.distance_km || 0) - (a.distance_km || 0))
      break
    case 'elevation_asc':
      routes.sort((a, b) => favFirst(a, b) || (a.elevation_gain_m || 0) - (b.elevation_gain_m || 0))
      break
    case 'elevation_desc':
      routes.sort((a, b) => favFirst(a, b) || (b.elevation_gain_m || 0) - (a.elevation_gain_m || 0))
      break
    case 'difficulty':
      routes.sort((a, b) => favFirst(a, b) || difficulty(b) - difficulty(a))
      break
    case 'name':
      routes.sort((a, b) => favFirst(a, b) || (a.name || '').localeCompare(b.name || ''))
      break
    default:
      routes.sort((a, b) => favFirst(a, b))
  }

  return routes
})

onMounted(async () => {
  // Resolve auth before fetching: routes are per-account, so an anonymous
  // visitor should land on the gate rather than on a 401.
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  await routesStore.fetchRoutes()
  await routesStore.fetchTrainingLocation()

  if (routesStore.trainingLocation?.inferred) {
    locationLat.value = routesStore.trainingLocation.inferred.lat
    locationLon.value = routesStore.trainingLocation.inferred.lon
  }
})

// --- Browse mode ---

const onRouteClick = async (routeId) => {
  if (creating.value) return
  const full = await routesStore.fetchRoute(routeId)
  if (full) selectedRoute.value = full
}

const deleteRoute = async (id) => {
  if (confirm(t('routes.confirm_delete'))) {
    await routesStore.deleteRoute(id)
    selectedRoute.value = null
  }
}

const toggleSelectedFavorite = () => {
  if (!selectedRoute.value) return
  routesStore.toggleFavorite(selectedRoute.value.id)
}

// --- Create mode ---

const startCreating = () => {
  selectedRoute.value = null
  creating.value = true
  createMode.value = 'draw'
  createWaypoints.value = []
  createPreviewRoute.value = null
  createLoopCenter.value = null
  lastMapClick.value = null
}

const stopCreating = () => {
  creating.value = false
  createMode.value = null
  createWaypoints.value = []
  createPreviewRoute.value = null
  createLoopCenter.value = null
  lastMapClick.value = null
}

const onCreated = () => {
  stopCreating()
  routesStore.fetchRoutes()
}

const onMapClick = (latlng) => {
  // Increment a counter to ensure reactivity even if same coordinates
  lastMapClick.value = { ...latlng, _ts: Date.now() }
}

// --- Training location ---

const searchTrainingLocation = async () => {
  const q = locationSearch.value.trim()
  if (!q) return
  locationResults.value = []
  try {
    const resp = await fetch(
      `https://nominatim.openstreetmap.org/search?` +
      new URLSearchParams({ q, format: 'json', limit: '5', addressdetails: '1' })
    )
    locationResults.value = await resp.json()
  } catch {
    // silently fail
  }
}

const pickTrainingLocation = (result) => {
  locationLat.value = parseFloat(result.lat)
  locationLon.value = parseFloat(result.lon)
  locationName.value = result.display_name.split(',').slice(0, 2).join(',').trim()
  locationSearch.value = locationName.value
  locationResults.value = []
}

const saveLocation = async () => {
  await routesStore.setTrainingLocation(locationLat.value, locationLon.value, locationName.value)
  showLocationSetup.value = false
}
</script>

<style scoped>
.routes-fullscreen {
  width: 100%;
  height: calc(100vh - 4rem);
  height: calc(100dvh - 4rem); /* mobile: exclude the browser's collapsing URL bar */
  position: relative;
  overflow: hidden;
}

/* Logged-out / pre-auth states fill the map area instead of the map. */
.routes-gate,
.routes-booting {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
}
.routes-booting { color: #94a3b8; font-size: .875rem; }

/* Floating toolbar */
.toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  z-index: 1100;
  display: flex;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}

.toolbar--creating {
  right: 352px; /* avoid overlapping create panel */
}

.toolbar > * {
  pointer-events: auto;
}

.toolbar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: white;
  border: none;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  cursor: pointer;
  color: #334155;
  transition: all 0.2s;
}

.toolbar-btn:hover {
  background: #f8fafc;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
}

.create-route-btn {
  margin-left: auto;
  padding: 8px 16px;
  background: #059669;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(5, 150, 105, 0.3);
  transition: all 0.2s;
  white-space: nowrap;
}

.create-route-btn:hover {
  background: #047857;
  box-shadow: 0 2px 12px rgba(5, 150, 105, 0.4);
}

/* Floating undo/redo on map */
.map-undo-redo {
  position: absolute;
  bottom: 52px;
  left: 12px;
  z-index: 1100;
  display: flex;
  gap: 2px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.map-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: white;
  border: none;
  cursor: pointer;
  color: #334155;
  transition: all 0.15s;
}

.map-action-btn:first-child {
  border-right: 1px solid #e2e8f0;
}

.map-action-btn:hover:not(.disabled) {
  background: #f1f5f9;
}

.map-action-btn.disabled {
  color: #cbd5e1;
  cursor: default;
}

/* Map instruction hint */
.map-hint {
  position: absolute;
  top: 64px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1100;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(4px);
  padding: 8px 16px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  font-size: 13px;
  color: #475569;
  pointer-events: none;
}

/* Location popover */
.location-popover {
  position: absolute;
  top: 48px;
  right: 0;
  width: 280px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  padding: 12px;
  z-index: 1200;
}

@media (max-width: 640px) {
  .toolbar--creating { right: 12px; }
  .toolbar-btn, .map-action-btn { width: 44px; height: 44px; }
  .create-route-btn { min-height: 44px; }
  /* Keep undo/redo above the create bottom sheet (55% tall). */
  .map-undo-redo { bottom: calc(55% + 12px); }
  .map-hint { width: max-content; max-width: calc(100% - 24px); text-align: center; }
  .location-popover { width: min(280px, calc(100vw - 24px)); }
}

/* Panel transitions */
.slide-left-enter-active,
.slide-left-leave-active {
  transition: transform 0.25s ease;
}

.slide-left-enter-from,
.slide-left-leave-to {
  transform: translateX(-100%);
}

.slide-right-enter-active,
.slide-right-leave-active {
  transition: transform 0.25s ease;
}

.slide-right-enter-from,
.slide-right-leave-to {
  transform: translateX(100%);
}

@media (max-width: 640px) {
  .slide-left-enter-from,
  .slide-left-leave-to,
  .slide-right-enter-from,
  .slide-right-leave-to {
    transform: translateY(100%);
  }
}
</style>
