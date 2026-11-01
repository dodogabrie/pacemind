<template>
  <div class="tle-backdrop" @click.self="$emit('close')">
    <div class="tle" role="dialog" :aria-label="$t('locations.title')">
      <div class="tle-head">
        <h2>{{ $t('locations.title') }}</h2>
        <button class="tle-x" :aria-label="$t('common.buttons.close')" @click="$emit('close')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>
      <p class="tle-sub">{{ $t('locations.intro') }}</p>

      <div class="tle-body">
        <div class="tle-list">
          <div v-for="l in store.locations" :key="l.id" class="tle-place" :class="{ sel: l.id === selId }" @click="selId = l.id">
            <div class="tle-row">
              <input class="tle-name" :value="l.name" :aria-label="$t('locations.name')" @change="update(l, { name: $event.target.value })" />
              <button class="tle-x" :title="$t('locations.remove')" :aria-label="$t('locations.remove')" @click.stop="remove(l)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
              </button>
            </div>
            <label class="tle-radius">{{ $t('locations.radius') }}
              <input type="number" min="1" max="200" :value="l.radius_km" @change="update(l, { radius_km: +$event.target.value || l.radius_km })" /> km
            </label>
            <div class="tle-days">
              <button
                v-for="(d, i) in DAYS" :key="d" class="tle-d" :class="{ on: l.weekdays.includes(i) }"
                :aria-pressed="l.weekdays.includes(i)"
                @click.stop="update(l, { weekdays: toggle(l.weekdays, i) })"
              >{{ $t(`calendarWeek.days.${d}`) }}</button>
            </div>
          </div>
          <p v-if="!store.locations.length" class="tle-sub">{{ $t('locations.empty') }}</p>
          <button class="tle-add" @click="add">{{ $t('locations.add') }}</button>
        </div>
        <div class="tle-mapcol">
          <div ref="mapEl" class="tle-map"></div>
          <p class="tle-sub">{{ $t('locations.map_hint') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useRoutesStore } from '../stores/routes'

defineEmits(['close'])
const { t } = useI18n()
const store = useRoutesStore()
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const selId = ref(null)
const mapEl = ref(null)
let map = null
let layer = null

const toggle = (days, i) => (days.includes(i) ? days.filter(d => d !== i) : [...days, i])

async function update(loc, patch) {
  await store.saveLocation({ id: loc.id, ...patch })
}
async function remove(loc) {
  await store.deleteLocation(loc.id)
  if (selId.value === loc.id) selId.value = null
}
async function add() {
  const c = map.getCenter()
  await store.saveLocation({ name: t('locations.new'), lat: c.lat, lon: c.lng, radius_km: 10, weekdays: [] })
  selId.value = store.locations[store.locations.length - 1]?.id
}

function draw() {
  if (!map) return
  layer.clearLayers()
  for (const l of store.locations) {
    const on = l.id === selId.value
    L.circle([l.lat, l.lon], { radius: l.radius_km * 1000, color: '#047857', weight: on ? 3 : 1, dashArray: '4 4', fillOpacity: on ? 0.18 : 0.06 })
      .bindTooltip(l.name, { permanent: true, direction: 'center' }).addTo(layer)
  }
}

onMounted(async () => {
  await store.fetchLocations()
  await nextTick()
  const first = store.locations[0] || store.trainingLocation
  map = L.map(mapEl.value, { attributionControl: false })
    .setView(first?.lat != null ? [first.lat, first.lon] : [42.5, 12.5], first ? 9 : 5)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map)
  layer = L.layerGroup().addTo(map)
  map.on('click', e => {
    const loc = store.locations.find(l => l.id === selId.value)
    if (loc) update(loc, { lat: e.latlng.lat, lon: e.latlng.lng })
  })
  draw()
})
onBeforeUnmount(() => { if (map) { map.remove(); map = null } })
watch(() => [store.locations, selId.value], draw, { deep: true })
</script>

<style scoped>
.tle-backdrop { position: fixed; inset: 0; z-index: 2000; background: rgba(15, 23, 42, .45); display: flex; align-items: center; justify-content: center; padding: 16px; }
.tle { background: white; border-radius: 12px; width: min(920px, 100%); max-height: 100%; overflow: auto; padding: 16px; display: grid; gap: 10px; }
.tle-head { display: flex; justify-content: space-between; align-items: center; }
.tle-head h2 { font-size: 1.1rem; font-weight: 600; margin: 0; }
.tle-sub { font-size: .8rem; color: #64748b; margin: 0; }
.tle-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 16px; }
@media (max-width: 720px) { .tle-body { grid-template-columns: 1fr; } }
.tle-list { display: grid; gap: 8px; align-content: start; }
.tle-place { border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; display: grid; gap: 8px; cursor: pointer; }
.tle-place.sel { border-color: #047857; background: #ecfdf5; }
.tle-row { display: flex; gap: 6px; align-items: center; }
.tle-name { flex: 1; min-width: 0; font-weight: 600; border: 1px solid transparent; border-radius: 4px; padding: 2px 4px; background: transparent; }
.tle-name:focus { border-color: #94a3b8; background: white; }
.tle-radius { font-size: .8rem; color: #475569; display: flex; gap: 6px; align-items: center; }
.tle-radius input { width: 60px; border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px 4px; }
.tle-days { display: flex; gap: 4px; flex-wrap: wrap; }
.tle-d { width: 38px; height: 30px; font-size: .75rem; font-weight: 600; border: 1px solid #cbd5e1; border-radius: 6px; background: none; color: #64748b; cursor: pointer; }
.tle-d.on { background: #047857; border-color: #047857; color: white; }
.tle-add { padding: 8px; border: 1px solid #047857; color: #047857; background: none; border-radius: 8px; font-weight: 600; cursor: pointer; }
.tle-x { background: none; border: none; color: #64748b; cursor: pointer; padding: 4px; }
.tle-mapcol { display: grid; gap: 6px; align-content: start; }
.tle-map { height: 360px; border-radius: 8px; border: 1px solid #e2e8f0; }
:focus-visible { outline: 2px solid #047857; outline-offset: 2px; }
</style>
