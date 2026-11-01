<template>
  <div class="prediction-trend">
    <h3 class="trend-title">{{ $t('prediction.trend.title') }}</h3>
    <div v-if="!history || history.length === 0" class="trend-empty">
      {{ $t('prediction.trend.empty') }}
    </div>
    <div v-else ref="chartRef" class="trend-chart"></div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatTime } from '../utils/formatters'

const props = defineProps({
  history: { type: Array, default: () => [] },
})

const { t, locale } = useI18n()
const chartRef = ref(null)
let chartInstance = null
let resizeObserver = null

const formatTimeShort = (seconds) => {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}:${String(m).padStart(2, '0')}`
}

const renderChart = async () => {
  if (!chartRef.value || !props.history?.length) return

  const echarts = await import('echarts/core')
  const { LineChart } = await import('echarts/charts')
  const { GridComponent, TooltipComponent } = await import('echarts/components')
  const { CanvasRenderer } = await import('echarts/renderers')

  echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)
  // Follow container width (drawer open animation, rotation, window resize).
  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver(() => chartInstance?.resize())
  resizeObserver.observe(chartRef.value)

  const dates = props.history.map(h => h.date)
  const values = props.history.map(h => h.predicted_seconds)

  chartInstance.setOption({
    grid: { left: 60, right: 16, top: 8, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params) => {
        const val = params[0]?.value
        return val ? `${val[0]}<br/>${t('prediction.trend.tooltip')}: <b>${formatTimeShort(val[1])}</b>` : ''
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, color: '#94a3b8', hideOverlap: true },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 10,
        color: '#94a3b8',
        formatter: (v) => formatTimeShort(v),
      },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [{
      type: 'line',
      data: dates.map((d, i) => [d, values[i]]),
      smooth: true,
      lineStyle: { color: '#047857', width: 2 },
      itemStyle: { color: '#047857' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(4,120,87,0.15)' },
            { offset: 1, color: 'rgba(4,120,87,0.01)' },
          ],
        },
      },
      symbolSize: 6,
    }],
  })
}

watch(locale, () => nextTick(renderChart))
watch(() => props.history, () => {
  nextTick(renderChart)
}, { deep: true })

onMounted(() => nextTick(renderChart))
onUnmounted(() => {
  resizeObserver?.disconnect()
  if (chartInstance) chartInstance.dispose()
})
</script>

<style scoped>
.prediction-trend {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1rem;
}

.trend-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin: 0 0 0.75rem;
}

.trend-chart {
  width: 100%;
  height: 160px;
}

.trend-empty {
  text-align: center;
  color: #94a3b8;
  font-size: 0.75rem;
  padding: 1.5rem 0;
}
</style>
