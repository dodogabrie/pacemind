<template>
  <div ref="mapEl" class="w-full h-full"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  routeData: { type: Array, required: true },
  circle: { type: Object, default: null }, // {lat, lon, radius_km}
})

const mapEl = ref(null)
let map = null

onMounted(() => {
  if (!mapEl.value || !props.routeData?.length) return
  initMap(props.routeData)
})

onBeforeUnmount(() => {
  if (map) { map.remove(); map = null }
})

watch(() => [props.routeData, props.circle], () => {
  const data = props.routeData
  if (map) { map.remove(); map = null }
  if (data?.length && mapEl.value) initMap(data)
})

const initMap = (points) => {
  map = L.map(mapEl.value, {
    zoomControl: true,
    attributionControl: false,
    dragging: true,
    scrollWheelZoom: true,
  }).setView([points[0].lat, points[0].lon], 13)

  L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    maxNativeZoom: 15,
    maxZoom: 19,
  }).addTo(map)

  const latLngs = points.map(p => [p.lat, p.lon])
  const polyline = L.polyline(latLngs, {
    color: '#047857',
    weight: 3,
    opacity: 0.9,
  }).addTo(map)

  // Start marker
  L.circleMarker(latLngs[0], {
    radius: 5, color: '#047857', fillColor: '#10b981', fillOpacity: 1, weight: 2,
  }).addTo(map)

  if (props.circle) {
    L.circle([props.circle.lat, props.circle.lon], {
      radius: props.circle.radius_km * 1000, color: '#047857', weight: 1, dashArray: '4 4', fillOpacity: 0.08,
    }).addTo(map)
  }

  map.fitBounds(polyline.getBounds(), { padding: [20, 20] })
}
</script>
