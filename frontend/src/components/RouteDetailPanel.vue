<template>
  <div class="detail-panel">
    <!-- Header -->
    <div class="flex items-start justify-between px-4 py-3 border-b border-slate-200">
      <div class="min-w-0 flex-1">
        <h2 class="text-lg font-bold text-slate-900 truncate">{{ route.name }}</h2>
        <div class="flex items-center gap-2 mt-1">
          <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded font-medium"
            :class="sourceClass(route.source)">
            {{ $te('routes.source.' + route.source) ? $t('routes.source.' + route.source) : route.source }}
          </span>
          <span class="text-[10px] font-medium px-1.5 py-0.5 rounded"
            :style="{ color: difficulty.color, background: difficulty.color + '15' }">
            {{ difficulty.label }}
          </span>
        </div>
      </div>
      <div class="flex gap-1 items-center flex-shrink-0 ml-2">
        <button
          @click="$emit('toggle-favorite')"
          :aria-label="$t('routes.favorite')"
          :title="$t('routes.favorite')"
          class="w-11 h-11 sm:w-8 sm:h-8 rounded-full flex items-center justify-center transition-colors"
          :class="isFavorite ? 'text-amber-500 bg-amber-50' : 'text-slate-300 hover:text-slate-400 bg-slate-50'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" :fill="isFavorite ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        </button>
        <button @click="$emit('close')" :aria-label="$t('common.buttons.close')" class="w-11 h-11 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-600 bg-slate-50 hover:bg-slate-100 transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="detail-content">
      <!-- Elevation Profile -->
      <div v-if="route.route_data?.length" class="px-4 py-3">
        <ElevationProfile
          :points="route.route_data"
          :compact="true"
          @hover="(idx) => $emit('hover-point', idx)"
        />
      </div>

      <!-- Stats -->
      <div class="grid grid-cols-3 gap-3 px-4 py-3 border-t border-slate-100">
        <div>
          <div class="text-[10px] text-slate-400 uppercase tracking-wider">{{ $t('routes.stats.distance') }}</div>
          <div class="text-sm font-bold text-slate-900">{{ route.distance_km }} km</div>
        </div>
        <div>
          <div class="text-[10px] text-slate-400 uppercase tracking-wider">{{ $t('routes.stats.gain') }}</div>
          <div class="text-sm font-bold text-slate-900">{{ route.elevation_gain_m }}m</div>
        </div>
        <div>
          <div class="text-[10px] text-slate-400 uppercase tracking-wider">{{ $t('routes.stats.loss') }}</div>
          <div class="text-sm font-bold text-slate-900">{{ route.elevation_loss_m }}m</div>
        </div>
      </div>

      <!-- Terrain -->
      <div v-if="route.terrain_summary && Object.keys(route.terrain_summary).length" class="px-4 py-3 border-t border-slate-100">
        <div class="text-[10px] text-slate-400 uppercase tracking-wider mb-1.5">{{ $t('routes.stats.terrain') }}</div>
        <div class="flex gap-1.5 flex-wrap">
          <span v-for="(pct, terrain) in route.terrain_summary" :key="terrain"
            class="px-2 py-0.5 text-xs rounded bg-emerald-50 text-emerald-700">
            {{ $te('routes.terrain.' + terrain) ? $t('routes.terrain.' + terrain) : terrain }}: {{ pct }}%
          </span>
        </div>
      </div>

      <!-- Tags -->
      <div v-if="visibleTags.length" class="px-4 py-3 border-t border-slate-100">
        <div class="text-[10px] text-slate-400 uppercase tracking-wider mb-1.5">{{ $t('routes.stats.tags') }}</div>
        <div class="flex gap-1.5 flex-wrap">
          <span v-for="tag in visibleTags" :key="tag"
            class="px-2 py-0.5 text-xs rounded bg-slate-100 text-slate-600">
            {{ tag }}
          </span>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
        <span class="text-xs text-slate-400">{{ new Date(route.created_at).toLocaleDateString($i18n.locale) }}</span>
        <button @click="routesStore.downloadGpx(route.id, route.name)" class="text-xs text-slate-600 hover:text-slate-900 transition-colors flex items-center gap-1">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/></svg>
          {{ $t('routes.download_gpx') }}
        </button>
        <button @click="$emit('delete', route.id)" class="text-xs text-rose-400 hover:text-rose-600 transition-colors">
          {{ $t('routes.delete') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ElevationProfile from './ElevationProfile.vue'
import { useRoutesStore } from '../stores/routes'

const { t } = useI18n()
const routesStore = useRoutesStore()

const props = defineProps({
  route: { type: Object, required: true },
})

defineEmits(['close', 'delete', 'toggle-favorite', 'hover-point'])

const isFavorite = computed(() => (props.route.tags || []).includes('favorite'))
const visibleTags = computed(() => (props.route.tags || []).filter(t => t !== 'favorite'))

const difficulty = computed(() => {
  const d = props.route.distance_km || 0
  const e = props.route.elevation_gain_m || 0
  const effort = d + (e / 100)
  const pct = Math.min(100, (effort / 60) * 100)
  let color, label
  if (pct < 25) { color = '#22c55e'; label = t('routes.difficulty.easy') }
  else if (pct < 50) { color = '#eab308'; label = t('routes.difficulty.moderate') }
  else if (pct < 75) { color = '#f97316'; label = t('routes.difficulty.hard') }
  else { color = '#ef4444'; label = t('routes.difficulty.extreme') }
  return { pct, color, label }
})

const sourceClass = (source) => ({
  'bg-blue-50 text-blue-700': source === 'strava',
  'bg-emerald-50 text-emerald-700': source === 'generated',
  'bg-slate-100 text-slate-600': source === 'imported',
})
</script>

<style scoped>
.detail-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 380px;
  background: white;
  z-index: 1050;
  display: flex;
  flex-direction: column;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.1);
}

.detail-content {
  flex: 1;
  overflow-y: auto;
}

@media (max-width: 640px) {
  /* Phones: bottom sheet over the lower part of the map so the map stays usable above it. */
  .detail-panel {
    top: auto;
    left: 0;
    right: 0;
    width: 100%;
    height: 60%;
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.15);
    padding-bottom: env(safe-area-inset-bottom);
  }
}
</style>
