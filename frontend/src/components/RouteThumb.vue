<template>
  <canvas ref="canvas" class="w-full h-full" :width="width" :height="height"></canvas>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'

const props = defineProps({
  route: { type: Object, required: true },
  width: { type: Number, default: 400 },
  height: { type: Number, default: 128 },
})

const canvas = ref(null)

const draw = () => {
  const el = canvas.value
  if (!el) return

  const ctx = el.getContext('2d')
  const rd = props.route.route_data
  if (!rd?.length || rd.length < 2) {
    // No route data available in summary - draw placeholder with stats
    ctx.fillStyle = '#f1f5f9'
    ctx.fillRect(0, 0, props.width, props.height)
    ctx.fillStyle = '#94a3b8'
    ctx.font = '11px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(`${props.route.distance_km} km`, props.width / 2, props.height / 2 - 6)
    ctx.fillText(`${props.route.elevation_gain_m}m D+`, props.width / 2, props.height / 2 + 10)
    return
  }

  const padding = 12
  const w = props.width - padding * 2
  const h = props.height - padding * 2

  // Get bounds
  let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity
  for (const p of rd) {
    if (p.lat < minLat) minLat = p.lat
    if (p.lat > maxLat) maxLat = p.lat
    if (p.lon < minLon) minLon = p.lon
    if (p.lon > maxLon) maxLon = p.lon
  }

  const latRange = maxLat - minLat || 0.001
  const lonRange = maxLon - minLon || 0.001

  // Maintain aspect ratio
  const scaleX = w / lonRange
  const scaleY = h / latRange
  const scale = Math.min(scaleX, scaleY)
  const offsetX = padding + (w - lonRange * scale) / 2
  const offsetY = padding + (h - latRange * scale) / 2

  const toX = (lon) => offsetX + (lon - minLon) * scale
  const toY = (lat) => offsetY + (maxLat - lat) * scale  // flip Y

  // Background
  ctx.fillStyle = '#f8fafc'
  ctx.fillRect(0, 0, props.width, props.height)

  // Draw route shadow
  ctx.beginPath()
  ctx.moveTo(toX(rd[0].lon), toY(rd[0].lat))
  for (let i = 1; i < rd.length; i++) {
    ctx.lineTo(toX(rd[i].lon), toY(rd[i].lat))
  }
  ctx.strokeStyle = 'rgba(4, 120, 87, 0.15)'
  ctx.lineWidth = 6
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.stroke()

  // Draw route line
  ctx.beginPath()
  ctx.moveTo(toX(rd[0].lon), toY(rd[0].lat))
  for (let i = 1; i < rd.length; i++) {
    ctx.lineTo(toX(rd[i].lon), toY(rd[i].lat))
  }
  ctx.strokeStyle = '#047857'
  ctx.lineWidth = 2.5
  ctx.stroke()

  // Start point
  ctx.beginPath()
  ctx.arc(toX(rd[0].lon), toY(rd[0].lat), 4, 0, Math.PI * 2)
  ctx.fillStyle = '#10b981'
  ctx.fill()
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 1.5
  ctx.stroke()
}

onMounted(draw)
watch(() => props.route, draw, { deep: true })
</script>
