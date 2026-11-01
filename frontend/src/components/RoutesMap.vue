<template>
  <div ref="mapEl" class="w-full h-full"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import L from 'leaflet'
import { useI18n } from 'vue-i18n'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  routes: { type: Array, default: () => [] },
  selectedRouteId: { type: [Number, String], default: null },
  selectedRouteFull: { type: Object, default: null },
  hoveredPoint: { type: Object, default: null },
  trainingLocation: { type: Object, default: null },
  // Create mode
  createMode: { type: String, default: null }, // null | 'draw' | 'loop'
  createWaypoints: { type: Array, default: () => [] },
  createPreviewRoute: { type: Array, default: null },
  createLoopCenter: { type: Object, default: null },
})

const emit = defineEmits(['route-click', 'map-click'])
const { t } = useI18n()

const mapEl = ref(null)
const currentLayer = ref('topo')

let map = null
let routePolylines = new Map()
let topoLayer = null
let osmLayer = null
let locationMarker = null
let hoverMarker = null
let selectedFullPolyline = null

// Create mode layers
let waypointMarkers = null
let previewPolyline = null
let loopCenterMarker = null

const ROUTE_STYLE = { color: '#047857', weight: 3, opacity: 0.7 }
const ROUTE_HOVER_STYLE = { weight: 5, opacity: 1 }
const ROUTE_SELECTED_STYLE = { color: '#2563eb', weight: 5, opacity: 0.9 }
const ROUTE_DIM_STYLE = { color: '#047857', weight: 2, opacity: 0.3 }

onMounted(() => {
  if (!mapEl.value) return
  initMap()
  drawRoutes()
  drawTrainingLocation()
})

onBeforeUnmount(() => {
  if (map) { map.remove(); map = null }
})

watch(() => props.routes, () => { drawRoutes() }, { deep: true })
watch(() => props.selectedRouteId, () => { updateSelection(); drawSelectedFull() })
watch(() => props.selectedRouteFull, () => { drawSelectedFull() }, { deep: true })
watch(() => props.trainingLocation, () => { drawTrainingLocation() }, { deep: true })
watch(() => props.hoveredPoint, () => { drawHoverMarker() }, { deep: true })

// Create mode watchers
watch(() => props.createMode, (mode) => {
  if (mode) {
    // Dim existing routes
    routePolylines.forEach(p => p.setStyle(ROUTE_DIM_STYLE))
  } else {
    // Restore & clean up creation layers
    updateSelection()
    clearCreateLayers()
  }
})

watch(() => props.createWaypoints, () => { drawCreateWaypoints() }, { deep: true })
watch(() => props.createPreviewRoute, () => { drawCreatePreview() }, { deep: true })
watch(() => props.createLoopCenter, () => { drawLoopCenter() }, { deep: true })

const initMap = () => {
  map = L.map(mapEl.value, {
    zoomControl: false,
    attributionControl: true,
    scrollWheelZoom: true,
  }).setView([43.77, 11.25], 10)

  L.control.zoom({ position: 'topright' }).addTo(map)

  topoLayer = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
    maxNativeZoom: 15,
    maxZoom: 19,
  })

  osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  })

  topoLayer.addTo(map)

  waypointMarkers = L.layerGroup().addTo(map)

  // Layer switcher control
  const LayerControl = L.Control.extend({
    options: { position: 'bottomleft' },
    onAdd() {
      const container = L.DomUtil.create('div', 'routes-layer-switcher')
      container.innerHTML = `
        <button class="active" data-layer="topo" title="OpenTopoMap">${t('routes.map.topo')}</button>
        <button data-layer="osm" title="OpenStreetMap">${t('routes.map.street')}</button>
      `
      L.DomEvent.disableClickPropagation(container)
      container.addEventListener('click', (e) => {
        const btn = e.target.closest('button')
        if (!btn) return
        const layer = btn.dataset.layer
        if (layer === 'topo') switchToTopo(container)
        else if (layer === 'osm') switchToOSM(container)
      })
      return container
    }
  })
  new LayerControl().addTo(map)

  map.on('click', (e) => {
    if (props.createMode) {
      const round6 = (n) => Math.round(n * 1e6) / 1e6
      emit('map-click', { lat: round6(e.latlng.lat), lon: round6(e.latlng.lng) })
    }
  })
}

const switchToTopo = (container) => {
  if (!map) return
  if (map.hasLayer(osmLayer)) map.removeLayer(osmLayer)
  if (!map.hasLayer(topoLayer)) { topoLayer.addTo(map); topoLayer.redraw() }
  currentLayer.value = 'topo'
  updateLayerButtons(container, 'topo')
}

const switchToOSM = (container) => {
  if (!map) return
  if (map.hasLayer(topoLayer)) map.removeLayer(topoLayer)
  if (!map.hasLayer(osmLayer)) osmLayer.addTo(map)
  currentLayer.value = 'osm'
  updateLayerButtons(container, 'osm')
}

const updateLayerButtons = (container, active) => {
  container.querySelectorAll('button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.layer === active)
  })
}

// --- Browse mode: route polylines ---

const drawRoutes = () => {
  if (!map) return

  if (selectedFullPolyline) { map.removeLayer(selectedFullPolyline); selectedFullPolyline = null }
  routePolylines.forEach(p => map.removeLayer(p))
  routePolylines.clear()

  const allBounds = []

  props.routes.forEach(route => {
    const points = route.route_data
    if (!points?.length) return

    const latLngs = points.map(p => [p.lat, p.lon])
    const isSelected = route.id === props.selectedRouteId
    const style = props.createMode
      ? { ...ROUTE_DIM_STYLE }
      : isSelected ? { ...ROUTE_SELECTED_STYLE } : { ...ROUTE_STYLE }

    const polyline = L.polyline(latLngs, style).addTo(map)
    polyline.bindTooltip(route.name, { sticky: true, className: 'route-tooltip' })

    polyline.on('mouseover', () => {
      if (!props.createMode && route.id !== props.selectedRouteId) {
        polyline.setStyle(ROUTE_HOVER_STYLE)
        polyline.bringToFront()
      }
    })
    polyline.on('mouseout', () => {
      if (!props.createMode && route.id !== props.selectedRouteId) {
        polyline.setStyle(ROUTE_STYLE)
      }
    })
    polyline.on('click', () => {
      if (!props.createMode) emit('route-click', route.id)
    })

    routePolylines.set(route.id, polyline)
    allBounds.push(...latLngs)
  })

  if (allBounds.length > 0 && !props.createMode) {
    map.fitBounds(L.latLngBounds(allBounds), { padding: [50, 50] })
  }
}

const updateSelection = () => {
  // If a full-resolution polyline is about to be drawn for the selected route,
  // hide the thumbnail underneath; otherwise highlight the thumbnail itself.
  const hasFull = props.selectedRouteFull?.id === props.selectedRouteId
                  && props.selectedRouteFull?.route_data?.length > 0
  routePolylines.forEach((polyline, id) => {
    if (props.createMode) {
      polyline.setStyle(ROUTE_DIM_STYLE)
    } else if (id === props.selectedRouteId) {
      if (hasFull) {
        polyline.setStyle({ ...ROUTE_SELECTED_STYLE, opacity: 0 })
      } else {
        polyline.setStyle(ROUTE_SELECTED_STYLE)
        polyline.bringToFront()
      }
    } else {
      polyline.setStyle(ROUTE_STYLE)
    }
  })
}

const drawTrainingLocation = () => {
  if (locationMarker) { map.removeLayer(locationMarker); locationMarker = null }
  if (!map || !props.trainingLocation?.lat) return

  locationMarker = L.circleMarker(
    [props.trainingLocation.lat, props.trainingLocation.lon],
    { radius: 8, color: '#6b7280', fillColor: '#9ca3af', fillOpacity: 0.4, weight: 2 }
  ).addTo(map)
  locationMarker.bindTooltip(t('routes.map.training_base'), { direction: 'top' })
}

const drawSelectedFull = () => {
  if (selectedFullPolyline) { map.removeLayer(selectedFullPolyline); selectedFullPolyline = null }
  if (!map || props.createMode) return
  const full = props.selectedRouteFull
  if (!full || full.id !== props.selectedRouteId || !full.route_data?.length) return

  // Hide the thumbnail polyline for the selected route so they don't overlap
  const thumb = routePolylines.get(full.id)
  if (thumb) thumb.setStyle({ opacity: 0 })

  const latLngs = full.route_data.map(p => [p.lat, p.lon])
  selectedFullPolyline = L.polyline(latLngs, { ...ROUTE_SELECTED_STYLE }).addTo(map)
  selectedFullPolyline.bringToFront()
}

const drawHoverMarker = () => {
  if (hoverMarker) { map.removeLayer(hoverMarker); hoverMarker = null }
  if (!map || !props.hoveredPoint) return

  const { lat, lon, elevation, distance } = props.hoveredPoint
  hoverMarker = L.circleMarker([lat, lon], {
    radius: 7,
    color: '#ffffff',
    weight: 2,
    fillColor: '#dc2626',
    fillOpacity: 1,
    interactive: false,
  }).addTo(map)
  if (elevation != null && distance != null) {
    hoverMarker.bindTooltip(
      `${(distance / 1000).toFixed(2)} km · ${Math.round(elevation)}m`,
      { permanent: true, direction: 'top', offset: [0, -6], className: 'route-tooltip' }
    ).openTooltip()
  }
}

// --- Create mode layers ---

const drawCreateWaypoints = () => {
  if (!waypointMarkers) return
  waypointMarkers.clearLayers()

  props.createWaypoints.forEach((wp, i) => {
    const isFirst = i === 0
    const isLast = i === props.createWaypoints.length - 1
    const color = isFirst ? '#047857' : isLast ? '#dc2626' : '#047857'
    const icon = L.divIcon({
      html: `<div style="width:22px;height:22px;border-radius:50%;background:${color};color:white;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3)">${i + 1}</div>`,
      className: '',
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    })
    L.marker([wp.lat, wp.lon], { icon }).addTo(waypointMarkers)
  })
}

const drawCreatePreview = () => {
  if (previewPolyline) { map.removeLayer(previewPolyline); previewPolyline = null }
  if (!props.createPreviewRoute?.length) return

  const latLngs = props.createPreviewRoute.map(p => [p.lat, p.lon])
  previewPolyline = L.polyline(latLngs, {
    color: '#047857',
    weight: 4,
    opacity: 0.85,
  }).addTo(map)
}

const drawLoopCenter = () => {
  if (loopCenterMarker) { map.removeLayer(loopCenterMarker); loopCenterMarker = null }
  if (!props.createLoopCenter) return

  const icon = L.divIcon({
    html: '<div style="width:14px;height:14px;border-radius:50%;background:#3b82f6;border:3px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.3)"></div>',
    className: '',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  })
  loopCenterMarker = L.marker(
    [props.createLoopCenter.lat, props.createLoopCenter.lon],
    { icon }
  ).addTo(map)
}

const clearCreateLayers = () => {
  if (waypointMarkers) waypointMarkers.clearLayers()
  if (previewPolyline) { map.removeLayer(previewPolyline); previewPolyline = null }
  if (loopCenterMarker) { map.removeLayer(loopCenterMarker); loopCenterMarker = null }
}
</script>

<style scoped>
:deep(.routes-layer-switcher) {
  background: white;
  border-radius: 4px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  display: flex;
  overflow: hidden;
}

:deep(.routes-layer-switcher button) {
  padding: 6px 12px;
  border: none;
  background: white;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: #333;
  transition: all 0.2s;
}

:deep(.routes-layer-switcher button:hover) {
  background: #f0f0f0;
}

:deep(.routes-layer-switcher button.active) {
  background: #3b82f6;
  color: white;
}

:deep(.routes-layer-switcher button:not(:last-child)) {
  border-right: 1px solid #e0e0e0;
}

:deep(.route-tooltip) {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 8px;
}

/* Push zoom control down to avoid toolbar overlap */
:deep(.leaflet-top.leaflet-right) {
  top: 60px;
}
</style>
