<template>
  <div ref="mapEl" class="races-map w-full h-full"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  races: { type: Array, default: () => [] },
  selectedRaceId: { type: [Number, String], default: null },
  trainingLocation: { type: Object, default: null },
})

const emit = defineEmits(['race-click'])

const mapEl = ref(null)
let map = null
let markers = new Map()
let baseMarker = null
let savedView = null  // { center: LatLng, zoom: number } captured when a race is first selected

const COLOR_BY_TYPE = {
  road: '#2563eb',
  trail: '#047857',
  ultra: '#b45309',
  vertical: '#7c3aed',
}

function makeIcon(color, selected) {
  const size = selected ? 18 : 13
  const inner = selected ? 8 : 5
  // Hit area is a fixed 32px box (finger-sized) with the visible dot centred in it.
  const hit = 32
  const html = `<span style="display:flex;align-items:center;justify-content:center;width:${hit}px;height:${hit}px;">
    <span style="
      display:inline-block;
      width:${size}px;height:${size}px;
      border-radius:50%;
      background:${color};
      border:2px solid white;
      box-shadow:0 0 0 1px rgba(0,0,0,0.3);
    "></span></span>`
  return L.divIcon({ html, className: '', iconSize: [hit, hit], iconAnchor: [hit / 2, hit / 2] })
}

function initMap() {
  map = L.map(mapEl.value, {
    zoomControl: true,
    scrollWheelZoom: true,
    minZoom: 2, // below this a phone-width map shows grey beyond the poles
    attributionControl: true,
  }).setView([45.5, 9.0], 5)

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map)
}

function clearMarkers() {
  markers.forEach((m) => m.remove())
  markers.clear()
}

function drawMarkers({ fit = false } = {}) {
  if (!map) return
  clearMarkers()
  const bounds = []
  for (const race of props.races) {
    if (race.lat == null || race.lon == null) continue
    const color = COLOR_BY_TYPE[race.race_type] || '#475569'
    const isSelected = race.id === props.selectedRaceId
    const m = L.marker([race.lat, race.lon], { icon: makeIcon(color, isSelected) })
    m.on('click', () => emit('race-click', race))
    m.bindTooltip(`<strong>${race.name}</strong><br/>${race.location || ''}`, {
      direction: 'top',
      offset: [0, -8],
    })
    m.addTo(map)
    markers.set(race.id, m)
    bounds.push([race.lat, race.lon])
  }
  if (fit && bounds.length) {
    try {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 })
    } catch (_) {
      /* no-op */
    }
  }
}

function drawTrainingBase() {
  if (!map) return
  if (baseMarker) {
    baseMarker.remove()
    baseMarker = null
  }
  const loc = props.trainingLocation
  if (!loc?.lat || !loc?.lon) return
  baseMarker = L.marker([loc.lat, loc.lon], {
    icon: L.divIcon({
      html: '<span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#0f172a;border:3px solid #fef3c7;"></span>',
      className: '',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    }),
  }).addTo(map)
  baseMarker.bindTooltip(loc.name || 'Training base', { direction: 'top', offset: [0, -8] })
}

onMounted(() => {
  if (!mapEl.value) return
  initMap()
  drawMarkers({ fit: true })
  drawTrainingBase()
})

onBeforeUnmount(() => {
  if (map) {
    map.remove()
    map = null
  }
})

function focusSelected(id, prevId) {
  if (!map) return
  if (id != null) {
    const race = props.races.find((r) => r.id === id)
    if (!race || race.lat == null || race.lon == null) return
    if (prevId == null) {
      savedView = { center: map.getCenter(), zoom: map.getZoom() }
    }
    map.flyTo([race.lat, race.lon], Math.max(map.getZoom(), 11), { duration: 0.6 })
  } else if (savedView) {
    map.flyTo(savedView.center, savedView.zoom, { duration: 0.6 })
    savedView = null
  }
}

watch(() => props.races, () => drawMarkers({ fit: true }), { deep: true })
watch(() => props.selectedRaceId, (id, prev) => {
  drawMarkers({ fit: false })
  focusSelected(id, prev)
})
watch(() => props.trainingLocation, drawTrainingBase, { deep: true })
</script>

<style scoped>
.races-map {
  position: relative;
  z-index: 0;
}
</style>
