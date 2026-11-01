<template>
  <div ref="chartContainer" class="chart-container" :class="{ compact: compact }"></div>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  TooltipComponent,
  GridComponent,
  ToolboxComponent,
  BrushComponent,
  DataZoomComponent,
  MarkPointComponent,
  VisualMapComponent,
} from 'echarts/components'

echarts.use([
  CanvasRenderer,
  LineChart,
  BarChart,
  TooltipComponent,
  GridComponent,
  ToolboxComponent,
  BrushComponent,
  DataZoomComponent,
  MarkPointComponent,
  VisualMapComponent,
])

const props = defineProps({
  points: {
    type: Array,
    required: true
  },
  compact: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['hover', 'select'])
const { t, locale } = useI18n()

const chartContainer = ref(null)
let chart = null

// Grade color scale (Strava-like: green=flat, yellow=moderate, orange=steep, red=very steep)
const gradeColor = (grade) => {
  const absGrade = Math.abs(grade)
  if (absGrade < 3) return '#22c55e'   // green - flat
  if (absGrade < 6) return '#84cc16'   // lime - gentle
  if (absGrade < 10) return '#eab308'  // yellow - moderate
  if (absGrade < 15) return '#f97316'  // orange - steep
  if (absGrade < 20) return '#ef4444'  // red - very steep
  return '#991b1b'                      // dark red - extreme
}

// Moving average smoothing — reduces ORS elevation quantization noise
// without flattening real terrain features. Window is centered, edges shrink.
const smoothSeries = (values, windowSize = 7) => {
  if (!values?.length || windowSize <= 1) return values.slice()
  const half = Math.floor(windowSize / 2)
  const out = new Array(values.length)
  for (let i = 0; i < values.length; i++) {
    const lo = Math.max(0, i - half)
    const hi = Math.min(values.length - 1, i + half)
    let sum = 0
    for (let j = lo; j <= hi; j++) sum += values[j]
    out[i] = sum / (hi - lo + 1)
  }
  return out
}

// Grades computed from smoothed elevations over a longer window (~50m * window)
// give a much cleaner % reading than raw point-to-point deltas.
const computeGrades = (points, smoothedElevations) => {
  const elevs = smoothedElevations || points.map(p => p.elevation)
  const grades = [0]
  const window = 3
  for (let i = 1; i < points.length; i++) {
    const lo = Math.max(0, i - window)
    const hi = Math.min(points.length - 1, i + window)
    const dElev = elevs[hi] - elevs[lo]
    const dDist = points[hi].distance - points[lo].distance
    const grade = dDist > 0 ? (dElev / dDist) * 100 : 0
    grades.push(Math.max(-50, Math.min(50, grade)))
  }
  return grades
}

const updateChart = (points) => {
  if (!chart || !points.length) return

  const distances = points.map(p => (p.distance / 1000).toFixed(2))
  const rawElevations = points.map(p => p.elevation)
  const elevations = smoothSeries(rawElevations, 7)
  const grades = computeGrades(points, elevations)

  // Find min/max elevation points
  let minIdx = 0, maxIdx = 0
  for (let i = 1; i < elevations.length; i++) {
    if (elevations[i] < elevations[minIdx]) minIdx = i
    if (elevations[i] > elevations[maxIdx]) maxIdx = i
  }

  // Create colored segments data for the gradient overlay
  const colorPieces = [
    { lte: 3, color: 'rgba(34, 197, 94, 0.45)' },
    { gt: 3, lte: 6, color: 'rgba(132, 204, 22, 0.45)' },
    { gt: 6, lte: 10, color: 'rgba(234, 179, 8, 0.45)' },
    { gt: 10, lte: 15, color: 'rgba(249, 115, 22, 0.45)' },
    { gt: 15, lte: 20, color: 'rgba(239, 68, 68, 0.45)' },
    { gt: 20, color: 'rgba(153, 27, 27, 0.45)' },
  ]

  const absGrades = grades.map(g => Math.abs(g))

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#334155', fontSize: 12 },
      formatter: (params) => {
        const idx = params[0]?.dataIndex ?? 0
        const elev = elevations[idx]
        const grade = grades[idx]
        const dist = distances[idx]
        const gradeStr = grade >= 0 ? `+${grade.toFixed(1)}` : grade.toFixed(1)
        const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${gradeColor(grade)};margin-right:4px"></span>`
        return `<div style="font-size:12px;line-height:1.6">
          <strong>${dist} km</strong><br/>
          ${t('profile.elevation')}: <strong>${Math.round(elev)}m</strong><br/>
          ${dot}${t('profile.slope')}: <strong>${gradeStr}%</strong>
        </div>`
      }
    },
    visualMap: {
      show: false,
      dimension: 0,
      seriesIndex: 1,
      pieces: colorPieces.map(p => ({
        ...p,
        // Map from grade values - we use the absGrades series
      })),
    },
    xAxis: {
      type: 'category',
      data: distances,
      axisLabel: {
        fontSize: 10,
        color: '#94a3b8',
        formatter: (v) => {
          const n = parseFloat(v)
          return n === Math.floor(n) ? `${n}` : ''
        }
      },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
      name: 'km',
      nameLocation: 'end',
      nameTextStyle: { fontSize: 10, color: '#94a3b8', padding: [0, 0, 0, -20] },
    },
    yAxis: [{
      type: 'value',
      name: 'm',
      nameLocation: 'end',
      nameTextStyle: { fontSize: 10, color: '#94a3b8', padding: [0, 0, -5, 0] },
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
      min: (value) => Math.max(0, Math.floor((value.min - 20) / 50) * 50),
    }],
    series: [
      // Main elevation line
      {
        type: 'line',
        data: elevations,
        smooth: 0.3,
        symbol: 'none',
        lineStyle: {
          color: '#0f766e',
          width: 2,
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(15, 118, 110, 0.35)' },
              { offset: 0.5, color: 'rgba(15, 118, 110, 0.15)' },
              { offset: 1, color: 'rgba(15, 118, 110, 0.02)' },
            ]
          }
        },
        markPoint: props.compact ? undefined : {
          symbol: 'circle',
          symbolSize: 6,
          label: {
            fontSize: 10,
            color: '#334155',
            formatter: (p) => `${Math.round(p.value)}m`,
            position: 'top',
            distance: 8,
          },
          data: [
            {
              coord: [distances[maxIdx], elevations[maxIdx]],
              value: elevations[maxIdx],
              itemStyle: { color: '#ef4444', borderColor: '#fff', borderWidth: 1.5 },
            },
            {
              coord: [distances[minIdx], elevations[minIdx]],
              value: elevations[minIdx],
              itemStyle: { color: '#3b82f6', borderColor: '#fff', borderWidth: 1.5 },
              label: { position: 'bottom', distance: 8 },
            },
          ]
        },
        z: 2,
      },
      // Grade-colored area overlay
      {
        type: 'line',
        data: elevations,
        smooth: 0.3,
        symbol: 'none',
        lineStyle: { width: 0 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: (() => {
              // Dynamic color based on average steepness
              const avgGrade = absGrades.reduce((a, b) => a + b, 0) / absGrades.length
              const c = gradeColor(avgGrade)
              return [
                { offset: 0, color: c.replace(')', ', 0.3)').replace('rgb', 'rgba') },
                { offset: 1, color: c.replace(')', ', 0.02)').replace('rgb', 'rgba') },
              ]
            })()
          }
        },
        z: 1,
      },
    ],
    grid: {
      left: props.compact ? 45 : 55,
      right: props.compact ? 15 : 25,
      top: props.compact ? 20 : 35,
      bottom: props.compact ? 25 : 40,
    },
    ...(props.compact ? {} : {
      toolbox: {
        feature: {
          brush: {
            type: ['lineX', 'clear'],
            title: { lineX: t('profile.select_area'), clear: t('profile.clear_selection') }
          }
        },
        left: 20,
        top: 5,
        iconStyle: { borderColor: '#94a3b8', borderWidth: 1 },
        emphasis: {
          iconStyle: {
            borderColor: '#0f766e',
            borderWidth: 2,
            shadowBlur: 6,
            shadowColor: 'rgba(15, 118, 110, 0.3)'
          }
        }
      },
      brush: {
        xAxisIndex: 0,
        brushStyle: {
          borderWidth: 2,
          color: 'rgba(15, 118, 110, 0.12)',
          borderColor: 'rgba(15, 118, 110, 0.6)'
        },
        outOfBrush: { colorAlpha: 0.3 },
        throttleType: 'debounce',
        throttleDelay: 300,
      },
    }),
  }

  chart.setOption(option, true)
}

const initChart = () => {
  chart = echarts.init(chartContainer.value)

  // Handle hover
  chart.getZr().on('mousemove', (event) => {
    const pointInGrid = [event.offsetX, event.offsetY]
    if (chart.containPixel('grid', pointInGrid)) {
      const xAxisIndex = chart.convertFromPixel({ seriesIndex: 0 }, pointInGrid)[0]
      const dataIndex = Math.round(xAxisIndex)
      if (dataIndex >= 0 && dataIndex < props.points.length) {
        emit('hover', dataIndex)
      }
    } else {
      emit('hover', null)
    }
  })

  chart.getZr().on('mouseout', () => {
    emit('hover', null)
  })

  // Handle brush selection
  chart.on('brushEnd', (params) => {
    if (params.areas && params.areas.length > 0) {
      const area = params.areas[0]
      const coordRange = area.coordRange
      const startIndex = Math.floor(coordRange[0])
      const endIndex = Math.floor(coordRange[1])
      if (startIndex >= 0 && endIndex < props.points.length) {
        emit('select', { start: startIndex, end: endIndex })
      }
    } else {
      emit('select', null)
    }
  })

  chart.on('brushSelected', (params) => {
    if (!params.batch || params.batch.length === 0 || !params.batch[0].areas || params.batch[0].areas.length === 0) {
      emit('select', null)
    }
  })

  if (props.points && props.points.length > 0) {
    updateChart(props.points)
  }
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chart) {
    chart.dispose()
  }
})

const handleResize = () => {
  if (chart) chart.resize()
}

watch(locale, () => { if (props.points?.length) updateChart(props.points) })
watch(() => props.points, (newPoints) => {
  if (newPoints && newPoints.length > 0) {
    updateChart(newPoints)
  }
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 220px;
  background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%);
  border-radius: 8px;
  box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.06), 0 1px 2px -1px rgb(0 0 0 / 0.06);
}
.chart-container.compact {
  height: 140px;
}
</style>
