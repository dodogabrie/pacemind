<template>
  <Teleport to="body">
    <div class="fixed inset-0 bg-black/50 z-[1010] flex items-center justify-center p-4" @click.self="$emit('close')">
      <div class="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[85vh] overflow-auto">
        <div class="p-6">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-lg font-bold text-slate-900">{{ $t('routes.browser.title') }}</h2>
            <button @click="$emit('close')" :aria-label="$t('common.buttons.close')" class="text-slate-400 hover:text-slate-600 text-xl">&times;</button>
          </div>

          <!-- Filters -->
          <div class="flex gap-2 mb-3 flex-wrap items-center">
            <div class="relative flex-1 min-w-[150px] max-w-xs">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
              <input v-model="searchText" :placeholder="$t('routes.browser.search')" class="input w-full text-sm pl-7" />
            </div>
            <input v-model.number="filters.min_distance_km" type="number" step="1" :placeholder="$t('routes.browser.min_km')" class="input w-20 text-sm" />
            <input v-model.number="filters.max_distance_km" type="number" step="1" :placeholder="$t('routes.browser.max_km')" class="input w-20 text-sm" />
            <input v-model.number="filters.min_elevation_m" type="number" step="50" :placeholder="$t('routes.browser.min_gain')" class="input w-24 text-sm" />
            <input v-model.number="filters.max_elevation_m" type="number" step="50" :placeholder="$t('routes.browser.max_gain')" class="input w-24 text-sm" />
            <button @click="applyFilters" class="btn btn-secondary text-sm">{{ $t('routes.browser.filter') }}</button>
          </div>

          <!-- Tag chips -->
          <div v-if="availableTags.length > 0" class="flex gap-1 mb-3 flex-wrap">
            <button
              v-for="tag in availableTags"
              :key="tag"
              @click="toggleTag(tag)"
              class="px-2 py-0.5 text-[10px] rounded-full border transition-colors"
              :class="activeTagFilters.includes(tag)
                ? 'bg-emerald-100 border-emerald-300 text-emerald-800'
                : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
            >
              {{ tag }}
            </button>
          </div>

          <!-- Content: list + map preview -->
          <div class="flex gap-4">
            <!-- Route List -->
            <div class="flex-1 min-w-0">
              <div v-if="loading" class="text-center py-8 text-slate-400">{{ $t('common.loading') }}</div>
              <div v-else-if="displayRoutes.length === 0" class="text-center py-8 text-slate-400">
                {{ $t('routes.browser.no_match') }}
              </div>
              <div v-else class="space-y-2 max-h-[55vh] overflow-y-auto pr-1">
                <div
                  v-for="route in displayRoutes"
                  :key="route.id"
                  class="flex items-center justify-between p-3 rounded-lg border transition-all cursor-pointer"
                  :class="selectedId === route.id ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 hover:border-emerald-200'"
                  @click="selectRoute(route.id)"
                >
                  <div class="min-w-0">
                    <div class="font-medium text-sm text-slate-900 truncate">{{ route.name }}</div>
                    <div class="flex gap-3 text-xs text-slate-500 mt-0.5">
                      <span class="font-medium">{{ route.distance_km }} km</span>
                      <span>{{ route.elevation_gain_m }}m D+</span>
                      <span v-for="tag in (route.tags || []).filter(t => t !== 'favorite')" :key="tag" class="px-1 bg-slate-100 rounded">{{ tag }}</span>
                    </div>
                  </div>
                  <button
                    v-if="selectedId === route.id"
                    @click.stop="$emit('select', route)"
                    class="btn btn-primary text-xs py-1 px-3 flex-shrink-0"
                  >
                    {{ $t('routes.browser.select') }}
                  </button>
                </div>
              </div>
            </div>

            <!-- Map + Elevation Preview -->
            <div class="w-96 flex-shrink-0 overflow-y-auto">
              <div v-if="!selectedId" class="h-64 rounded-lg border border-dashed border-slate-300 flex items-center justify-center text-sm text-slate-400">
                {{ $t('routes.browser.pick_preview') }}
              </div>
              <div v-else-if="loadingPreview" class="h-64 rounded-lg border border-slate-200 flex items-center justify-center text-sm text-slate-400">
                {{ $t('routes.browser.loading_map') }}
              </div>
              <template v-else-if="previewRoute?.route_data?.length">
                <div class="h-52 rounded-lg border border-slate-200 overflow-hidden">
                  <RoutePreviewMap :route-data="previewRoute.route_data" />
                </div>
                <div class="mt-2">
                  <ElevationProfile :points="previewRoute.route_data" :compact="true" />
                </div>
              </template>
              <div v-if="previewRoute" class="mt-2 text-xs text-slate-500 space-y-0.5">
                <div class="font-medium text-slate-700">{{ previewRoute.name }}</div>
                <div>{{ previewRoute.distance_km }} km &middot; {{ previewRoute.elevation_gain_m }}m D+ &middot; {{ previewRoute.elevation_loss_m }}m D-</div>
                <div v-if="previewRoute.terrain_summary" class="flex gap-1 flex-wrap">
                  <span v-for="(pct, terrain) in previewRoute.terrain_summary" :key="terrain" class="px-1 bg-slate-100 rounded">{{ $te('routes.terrain.' + terrain) ? $t('routes.terrain.' + terrain) : terrain }} {{ pct }}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoutesStore } from '../stores/routes'
import RoutePreviewMap from './RoutePreviewMap.vue'
import ElevationProfile from './ElevationProfile.vue'

defineEmits(['close', 'select'])

const routesStore = useRoutesStore()
const loading = ref(false)
const selectedId = ref(null)
const searchResults = ref(null)
const loadingPreview = ref(false)
const previewRoute = ref(null)
const searchText = ref('')
const activeTagFilters = ref([])

const filters = ref({
  min_distance_km: null,
  max_distance_km: null,
  min_elevation_m: null,
  max_elevation_m: null,
})

onMounted(async () => {
  if (routesStore.routes.length === 0) {
    loading.value = true
    await routesStore.fetchRoutes()
    loading.value = false
  }
})

const availableTags = computed(() => {
  const tags = new Set()
  routesStore.routes.forEach(r => {
    (r.tags || []).forEach(t => { if (t !== 'favorite') tags.add(t) })
  })
  return Array.from(tags).sort()
})

const toggleTag = (tag) => {
  const idx = activeTagFilters.value.indexOf(tag)
  if (idx >= 0) activeTagFilters.value.splice(idx, 1)
  else activeTagFilters.value.push(tag)
}

const displayRoutes = computed(() => {
  let routes = searchResults.value || routesStore.routes

  // Text search
  if (searchText.value.trim()) {
    const q = searchText.value.toLowerCase()
    routes = routes.filter(r => r.name?.toLowerCase().includes(q))
  }

  // Tag filter
  if (activeTagFilters.value.length > 0) {
    routes = routes.filter(r =>
      activeTagFilters.value.every(tag => (r.tags || []).includes(tag))
    )
  }

  return routes
})

const applyFilters = async () => {
  const hasFilter = Object.values(filters.value).some(v => v != null && v !== '')
  if (!hasFilter) {
    searchResults.value = null
    return
  }
  loading.value = true
  searchResults.value = await routesStore.searchRoutes(filters.value)
  loading.value = false
}

const selectRoute = async (routeId) => {
  selectedId.value = routeId
  loadingPreview.value = true
  previewRoute.value = null

  try {
    const data = await routesStore.fetchRoute(routeId)
    if (!data || selectedId.value !== routeId) return
    previewRoute.value = data
  } finally {
    if (selectedId.value === routeId) {
      loadingPreview.value = false
    }
  }
}
</script>
