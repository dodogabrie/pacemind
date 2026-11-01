<template>
  <div class="routes-panel">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-slate-200">
      <div class="flex items-center gap-2">
        <h2 class="text-sm font-bold text-slate-900 uppercase tracking-wide">{{ $t('routes.my_routes') }}</h2>
        <span class="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded-full font-medium">{{ routes.length }}</span>
      </div>
      <button @click="$emit('close')" :aria-label="$t('common.buttons.close')" class="w-11 h-11 -my-2 -mr-3 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="-rotate-90 sm:rotate-0"><path d="M15 18l-6-6 6-6"/></svg>
      </button>
    </div>

    <!-- Search & Sort -->
    <div class="px-4 py-2 border-b border-slate-100 space-y-2">
      <div class="relative">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <input
          :value="searchText"
          @input="$emit('update:searchText', $event.target.value)"
          :placeholder="$t('routes.search')"
          class="w-full text-base sm:text-sm pl-8 pr-3 py-2 sm:py-1.5 rounded-md border border-slate-200 focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400 outline-none"
        />
      </div>
      <div class="flex gap-2 items-center">
        <select
          :value="sortBy"
          @change="$emit('update:sortBy', $event.target.value)"
          class="text-sm sm:text-xs py-2 sm:py-1 px-2 rounded border border-slate-200 bg-white text-slate-600 outline-none flex-1"
        >
          <option value="recent">{{ $t('routes.sort.recent') }}</option>
          <option value="distance_asc">{{ $t('routes.sort.distance_asc') }}</option>
          <option value="distance_desc">{{ $t('routes.sort.distance_desc') }}</option>
          <option value="elevation_desc">{{ $t('routes.sort.elevation_desc') }}</option>
          <option value="difficulty">{{ $t('routes.sort.difficulty') }}</option>
          <option value="name">{{ $t('routes.sort.name') }}</option>
        </select>
      </div>
      <!-- Tag chips -->
      <div v-if="availableTags.length" class="flex gap-1 flex-wrap">
        <button
          v-for="tag in availableTags"
          :key="tag"
          @click="$emit('toggle-tag', tag)"
          class="px-3 py-1.5 sm:px-2 sm:py-0.5 text-xs sm:text-[10px] rounded-full border transition-colors"
          :class="activeTagFilters.includes(tag)
            ? 'bg-emerald-100 border-emerald-300 text-emerald-800'
            : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
        >
          {{ tag }}
        </button>
      </div>
    </div>

    <!-- Route List -->
    <div class="routes-list">
      <div v-if="routes.length === 0" class="px-4 py-8 text-center text-sm text-slate-400">
        {{ $t('routes.empty') }}
      </div>
      <div
        v-for="route in routes"
        :key="route.id"
        class="route-item flex gap-3 px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors border-b border-slate-100"
        :class="{ 'bg-blue-50 hover:bg-blue-50': route.id === selectedRouteId }"
        @click="$emit('route-click', route.id)"
        @mouseenter="$emit('route-hover', route.id)"
        @mouseleave="$emit('route-hover', null)"
      >
        <!-- Color indicator -->
        <div class="flex-shrink-0 w-1 rounded-full self-stretch" :style="{ background: route.id === selectedRouteId ? '#2563eb' : '#047857' }"></div>

        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-1.5">
            <h3 class="text-sm font-semibold text-slate-900 truncate">{{ route.name }}</h3>
            <svg v-if="isFavorite(route)" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" class="flex-shrink-0 text-amber-500"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          </div>
          <div class="flex gap-3 mt-0.5 text-xs text-slate-500">
            <span class="font-medium text-slate-700">{{ route.distance_km }} km</span>
            <span>{{ route.elevation_gain_m }}m D+</span>
          </div>
          <div class="flex items-center gap-2 mt-1">
            <div class="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden max-w-[80px]">
              <div class="h-full rounded-full" :style="{ width: difficulty(route).pct + '%', background: difficulty(route).color }"></div>
            </div>
            <span class="text-[10px] font-medium" :style="{ color: difficulty(route).color }">{{ difficulty(route).label }}</span>
            <span class="text-[10px] uppercase tracking-wider px-1 py-0.5 rounded font-medium ml-auto"
              :class="sourceClass(route.source)">
              {{ $te('routes.source.' + route.source) ? $t('routes.source.' + route.source) : route.source }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

defineProps({
  routes: { type: Array, default: () => [] },
  selectedRouteId: { type: [Number, String], default: null },
  searchText: { type: String, default: '' },
  sortBy: { type: String, default: 'recent' },
  activeTagFilters: { type: Array, default: () => [] },
  availableTags: { type: Array, default: () => [] },
})

defineEmits(['route-click', 'route-hover', 'close', 'update:searchText', 'update:sortBy', 'toggle-tag'])

const isFavorite = (route) => (route.tags || []).includes('favorite')

const difficulty = (route) => {
  const d = route.distance_km || 0
  const e = route.elevation_gain_m || 0
  const effort = d + (e / 100)
  const pct = Math.min(100, (effort / 60) * 100)
  let color, label
  if (pct < 25) { color = '#22c55e'; label = t('routes.difficulty.easy') }
  else if (pct < 50) { color = '#eab308'; label = t('routes.difficulty.moderate') }
  else if (pct < 75) { color = '#f97316'; label = t('routes.difficulty.hard') }
  else { color = '#ef4444'; label = t('routes.difficulty.extreme') }
  return { pct, color, label }
}

const sourceClass = (source) => ({
  'bg-blue-50 text-blue-700': source === 'strava',
  'bg-emerald-50 text-emerald-700': source === 'generated',
  'bg-slate-100 text-slate-600': source === 'imported',
})
</script>

<style scoped>
.routes-panel {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 320px;
  background: white;
  z-index: 1050;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.1);
}

.routes-list {
  flex: 1;
  overflow-y: auto;
}

@media (max-width: 640px) {
  /* Phones: bottom sheet over the lower part of the map so the map stays usable above it. */
  .routes-panel {
    top: auto;
    left: 0;
    right: 0;
    width: 100%;
    height: 50%;
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.15);
    padding-bottom: env(safe-area-inset-bottom);
  }
}
</style>
