<template>
  <div class="map-container" ref="mapContainer">
    <div class="layer-switcher">
      <button
        :class="{ active: currentLayer === 'topo' }"
        @click="switchToTopo"
        :title="$t('routes.map.topo_title')">
        {{ $t('routes.map.topo') }}
      </button>
      <button
        :class="{ active: currentLayer === 'osm' }"
        @click="switchToOSM"
        :title="$t('routes.map.street_title')">
        {{ $t('routes.map.street') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useMapStore } from '../stores/map'

const props = defineProps({
  points: {
    type: Array,
    required: true
  },
  hoveredIndex: {
    type: Number,
    default: null
  },
  selectedRange: {
    type: Object,
    default: null
  },
  annotations: {
    type: Array,
    default: () => []
  },
  suggestedAnnotations: {
    type: Array,
    default: () => []
  }
})

const mapContainer = ref(null)
const mapStore = useMapStore()
const currentLayer = ref('topo')

let map = null
let routeLayer = L.layerGroup() // Changed to LayerGroup to hold multiple segments
let hoverMarker = null
let selectionLayer = null
let annotationMarkers = null
let suggestedAnnotationMarkers = null
let topoLayer = null
let osmLayer = null
let ctrlKeyHandler = null
let ctrlKeyUpHandler = null

const initMap = () => {
  // Touch devices: one finger scrolls the page, two fingers pan/zoom the map,
  // so the inline map never traps page scroll.
  map = L.map(mapContainer.value, { dragging: !L.Browser.mobile }).setView([mapStore.center.lat, mapStore.center.lon], mapStore.zoom)

  // OpenTopoMap layer (with contour lines, native tiles up to zoom 15)
  topoLayer = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    attribution: 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
    maxNativeZoom: 15,
    maxZoom: 19
  })

  // Standard OSM layer (no contours, zoom 0-19)
  osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  })

  // Start with topo layer
  topoLayer.addTo(map)

  routeLayer.addTo(map)

  annotationMarkers = L.layerGroup()
  annotationMarkers.addTo(map)

  suggestedAnnotationMarkers = L.layerGroup()
  suggestedAnnotationMarkers.addTo(map)

  map.on('zoomend', () => {
    mapStore.updateZoom(map.getZoom())
  })

  map.on('moveend', () => {
    const center = map.getCenter()
    mapStore.updateCenter({ lat: center.lat, lon: center.lng })
  })

  map.scrollWheelZoom.disable()
  ctrlKeyHandler = (event) => {
    if (!map) return
    if (event.key === 'Control') {
      map.scrollWheelZoom.enable()
    }
  }
  ctrlKeyUpHandler = (event) => {
    if (!map) return
    if (event.key === 'Control') {
      map.scrollWheelZoom.disable()
    }
  }
  window.addEventListener('keydown', ctrlKeyHandler)
  window.addEventListener('keyup', ctrlKeyUpHandler)
}

const drawRoute = (points) => {
  if (!map) return

  routeLayer.clearLayers()

  const latLngs = points.map(p => [p.lat, p.lon])
  L.polyline(latLngs, {
    color: '#0f172a',
    weight: 5,
    opacity: 0.9
  }).addTo(routeLayer)

  // Fit bounds
  if (latLngs.length > 0) {
    map.fitBounds(L.polyline(latLngs).getBounds())
  }
}

const updateHoverMarker = (index) => {
  if (hoverMarker) {
    map.removeLayer(hoverMarker)
    hoverMarker = null
  }

  if (index !== null && props.points[index]) {
    const point = props.points[index]
    hoverMarker = L.circleMarker([point.lat, point.lon], {
      radius: 4,
      color: '#000',
      fillColor: '#000',
      fillOpacity: 1,
      weight: 2
    }).addTo(map)
  }
}

const switchToTopo = () => {
  if (!map) return
  if (map.hasLayer(osmLayer)) {
    map.removeLayer(osmLayer)
  }
  if (!map.hasLayer(topoLayer)) {
    topoLayer.addTo(map)
    topoLayer.redraw()
  }
  currentLayer.value = 'topo'
}

const switchToOSM = () => {
  if (!map) return
  if (map.hasLayer(topoLayer)) {
    map.removeLayer(topoLayer)
  }
  if (!map.hasLayer(osmLayer)) {
    osmLayer.addTo(map)
  }
  currentLayer.value = 'osm'
}

const updateSelection = (range) => {
  if (selectionLayer) {
    map.removeLayer(selectionLayer)
    selectionLayer = null
  }

  if (range && range.start !== null && range.end !== null) {
    const selectedPoints = props.points.slice(range.start, range.end + 1)
    const latLngs = selectedPoints.map(p => [p.lat, p.lon])

    selectionLayer = L.polyline(latLngs, {
      color: 'red',
      weight: 5,
      opacity: 0.9
    }).addTo(map)
  }
}

const ANNOTATION_TYPE_CLASS = {
  aid_station: 'annotation-label--aid',
  water: 'annotation-label--water',
  checkpoint: 'annotation-label--checkpoint',
  caution: 'annotation-label--caution',
  generic: 'annotation-label--default',
}

const resolveClosestPoint = (distance_km) => {
  const targetDist = distance_km * 1000
  let closest = null
  let minDiff = Infinity
  for (const point of props.points) {
    const diff = Math.abs(point.distance - targetDist)
    if (diff < minDiff) {
      minDiff = diff
      closest = point
    }
  }
  return closest
}

const updateAnnotationMarkers = (annotations) => {
  if (!annotationMarkers) return

  annotationMarkers.clearLayers()

  annotations.forEach(ann => {
    const closest = resolveClosestPoint(ann.distance_km)
    if (closest) {
      const cssClass = ANNOTATION_TYPE_CLASS[ann.type] || 'annotation-label--default'
      const icon = L.divIcon({
        html: '<div class="annotation-label ' + cssClass + '">' + ann.label + '</div>',
        className: 'annotation-icon',
        iconAnchor: [0, 40]
      })
      L.marker([closest.lat, closest.lon], { icon }).addTo(annotationMarkers)
    }
  })
}

const updateSuggestedAnnotationMarkers = (suggestions) => {
  if (!suggestedAnnotationMarkers) return

  suggestedAnnotationMarkers.clearLayers()

  suggestions.forEach(s => {
    if (s.status !== 'pending') return
    const closest = s.lat && s.lon ? s : resolveClosestPoint(s.distance_km)
    if (!closest) return

    const cssClass = ANNOTATION_TYPE_CLASS[s.type] || 'annotation-label--default'
    const icon = L.divIcon({
      html: '<div class="annotation-label annotation-label--suggested ' + cssClass + '">' + s.label + '</div>',
      className: 'annotation-icon',
      iconAnchor: [0, 40]
    })
    L.marker([closest.lat, closest.lon], { icon }).addTo(suggestedAnnotationMarkers)
  })
}

onMounted(() => {
  initMap()
  if (props.points && props.points.length > 0) {
    drawRoute(props.points)
  }
})

onBeforeUnmount(() => {
  if (ctrlKeyHandler) {
    window.removeEventListener('keydown', ctrlKeyHandler)
    ctrlKeyHandler = null
  }
  if (ctrlKeyUpHandler) {
    window.removeEventListener('keyup', ctrlKeyUpHandler)
    ctrlKeyUpHandler = null
  }
  if (map) {
    map.scrollWheelZoom.disable()
  }
})

watch(() => props.points, (newPoints) => {
  if (newPoints && newPoints.length > 0) {
    drawRoute(newPoints)
  }
})

watch(() => props.hoveredIndex, (index) => {
  updateHoverMarker(index)
})

watch(() => props.selectedRange, (range) => {
  updateSelection(range)
})

watch(() => props.annotations, (annotations) => {
  updateAnnotationMarkers(annotations)
}, { deep: true, immediate: true })

watch(() => props.suggestedAnnotations, (suggestions) => {
  updateSuggestedAnnotationMarkers(suggestions)
}, { deep: true, immediate: true })
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  z-index: 0;
}

.layer-switcher {
  position: absolute;
  bottom: 10px;
  left: 10px;
  z-index: 1000;
  background: white;
  border-radius: 4px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  display: flex;
  overflow: hidden;
}

@media (max-width: 640px) {
  /* Bottom-left is covered by the wrapped attribution on phones. */
  .layer-switcher { bottom: auto; top: 10px; left: auto; right: 10px; }
}

.layer-switcher button {
  padding: 6px 12px;
  border: none;
  background: white;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: #333;
  transition: all 0.2s;
}

.layer-switcher button:hover {
  background: #f0f0f0;
}

.layer-switcher button.active {
  background: #3b82f6;
  color: white;
}

.layer-switcher button:not(:last-child) {
  border-right: 1px solid #e0e0e0;
}

:global(.annotation-icon) {
  background: transparent;
  border: none;
  width: auto;
  height: auto;
}

:global(.annotation-label) {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  color: #fff;
  box-sizing: border-box;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

:global(.annotation-label--aid) {
  background: #10b981;
}

:global(.annotation-label--water) {
  background: #3b82f6;
}

:global(.annotation-label--checkpoint) {
  background: #f59e0b;
}

:global(.annotation-label--caution) {
  background: #ef4444;
}

:global(.annotation-label--default) {
  background: #8b5cf6;
}

:global(.annotation-label--suggested) {
  opacity: 0.6;
  border: 2px dashed rgba(255, 255, 255, 0.8);
}

@media (max-width: 640px) {
  .layer-switcher button { padding: 12px 14px; }
}
</style>
