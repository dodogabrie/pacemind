<template>
  <div class="race-report">
    <AuthGate v-if="authStore.authChecked && !authStore.isAuthenticated" />
    <template v-else>
    <div v-if="planStore.loading && !planStore.raceReport" class="report-loading">
      {{ $t('raceReport.loading') }}
    </div>
    <div v-else-if="planStore.error" class="report-error">
      {{ planStore.error }}
    </div>
    <template v-else-if="planStore.raceReport">
      <!-- Header -->
      <div class="report-header">
        <h1 class="report-title">{{ $t('raceReport.title') }}</h1>
        <div class="report-summary">
          <div class="time-block">
            <span class="time-label">{{ $t('raceReport.actual') }}</span>
            <span class="time-value">{{ formatTime(report.actual_total_seconds) }}</span>
          </div>
          <div v-if="report.predicted_total_seconds" class="time-block">
            <span class="time-label">{{ $t('raceReport.predicted') }}</span>
            <span class="time-value predicted">{{ formatTime(report.predicted_total_seconds) }}</span>
          </div>
          <div v-if="report.difference_seconds != null" class="time-block">
            <span class="time-label">{{ $t('raceReport.difference') }}</span>
            <span class="time-value" :class="report.difference_seconds > 0 ? 'diff-slower' : 'diff-faster'">
              {{ report.difference_seconds > 0 ? '+' : '' }}{{ formatDiff(report.difference_seconds) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Split comparison chart -->
      <div v-if="report.split_comparison?.length" class="report-section">
        <h2 class="section-title">{{ $t('raceReport.pace_comparison') }}</h2>
        <div ref="chartEl" class="pace-chart"></div>
      </div>

      <!-- Insights -->
      <div v-if="report.insights?.length" class="report-section">
        <h2 class="section-title">{{ $t('raceReport.insights') }}</h2>
        <div class="insights-list">
          <div v-for="(insight, i) in report.insights" :key="i" class="insight-card">
            {{ insight }}
          </div>
        </div>
      </div>

      <!-- Split table -->
      <div v-if="report.split_comparison?.length" class="report-section">
        <h2 class="section-title">{{ $t('raceReport.splits') }}</h2>
        <div class="split-table-wrap">
          <table class="split-table">
            <thead>
              <tr>
                <th>KM</th>
                <th>{{ $t('raceReport.actual_pace') }}</th>
                <th>{{ $t('raceReport.predicted_pace') }}</th>
                <th>{{ $t('raceReport.diff') }}</th>
                <th>{{ $t('raceReport.grade') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in report.split_comparison" :key="s.km">
                <td>{{ s.km }}</td>
                <td>{{ formatPace(s.actual_pace) }}</td>
                <td>{{ s.predicted_pace != null ? formatPace(s.predicted_pace) : '—' }}</td>
                <td :class="diffClass(s.diff_seconds)">
                  {{ s.diff_seconds != null ? `${s.diff_seconds > 0 ? '+' : ''}${s.diff_seconds.toFixed(0)}s` : '—' }}
                </td>
                <td>{{ s.grade != null ? `${s.grade.toFixed(1)}%` : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTrainingPlanStore } from '../stores/trainingPlan'
import { useAuthStore } from '../stores/auth'
import AuthGate from '../components/AuthGate.vue'
import { formatTime, formatPaceCompact } from '../utils/formatters'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const route = useRoute()
const planStore = useTrainingPlanStore()
const authStore = useAuthStore()
const chartEl = ref(null)

const report = computed(() => planStore.raceReport || {})

const formatDiff = (seconds) => {
  if (seconds == null) return '—'
  const abs = Math.abs(seconds)
  const m = Math.floor(abs / 60)
  const s = Math.floor(abs % 60)
  if (m > 0) return `${m}:${String(s).padStart(2, '0')}`
  return `${s}s`
}

const formatPace = formatPaceCompact

const diffClass = (diff) => {
  if (diff == null) return ''
  return diff > 5 ? 'diff-slower' : diff < -5 ? 'diff-faster' : ''
}

const renderChart = async () => {
  if (!chartEl.value || !report.value.split_comparison?.length) return

  const { init } = await import('echarts/core')
  const { BarChart } = await import('echarts/charts')
  const { GridComponent, TooltipComponent, LegendComponent } = await import('echarts/components')
  const { CanvasRenderer } = await import('echarts/renderers')
  const echarts = await import('echarts/core')
  echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

  const splits = report.value.split_comparison
  const chart = init(chartEl.value)

  chart.setOption({
    tooltip: { trigger: 'axis', confine: true },
    legend: { data: [t('raceReport.actual'), t('raceReport.predicted')], bottom: 0 },
    grid: { left: 50, right: 28, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: splits.map(s => `${s.km}`),
      name: 'km',
      axisLabel: { hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      name: 'min/km',
      inverse: true,
    },
    series: [
      {
        name: t('raceReport.actual'),
        type: 'bar',
        data: splits.map(s => s.actual_pace),
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: t('raceReport.predicted'),
        type: 'bar',
        data: splits.map(s => s.predicted_pace),
        itemStyle: { color: '#94a3b8' },
      },
    ],
  })

  window.addEventListener('resize', () => chart.resize())
}

watch(() => report.value.split_comparison, async (val) => {
  if (val?.length) {
    await nextTick()
    renderChart()
  }
})

onMounted(async () => {
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  const planId = route.params.planId
  if (planId) {
    await planStore.fetchRaceReport(planId)
    await nextTick()
    renderChart()
  }
})
</script>

<style scoped>
.race-report {
  max-width: 900px;
  margin: 0 auto;
  padding: 1rem;
}

.report-loading, .report-error {
  text-align: center;
  padding: 3rem;
  color: #64748b;
  font-size: 0.875rem;
}
.report-error { color: #ef4444; }

.report-header {
  margin-bottom: 1.5rem;
}
.report-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 1rem;
}

.report-summary {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
}

.time-block {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
.time-label {
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #64748b;
}
.time-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
  font-family: monospace;
}
.time-value.predicted { color: #64748b; }
.time-value.diff-faster { color: #16a34a; }
.time-value.diff-slower { color: #dc2626; }

.report-section {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1rem;
  margin-bottom: 1rem;
}

.section-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin: 0 0 0.75rem;
}

.pace-chart {
  width: 100%;
  height: 300px;
}

.insights-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.insight-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.625rem 1rem;
  font-size: 0.8125rem;
  color: #334155;
}

.split-table-wrap {
  overflow-x: auto;
}
.split-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}
.split-table th {
  text-align: left;
  font-weight: 600;
  color: #64748b;
  padding: 0.375rem 0.75rem;
  border-bottom: 2px solid #e2e8f0;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.split-table td {
  padding: 0.375rem 0.75rem;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}
.split-table td { font-variant-numeric: tabular-nums; white-space: nowrap; }
@media (max-width: 640px) {
  .race-report { padding: 1rem 0; }
  .report-summary { gap: 1rem 1.5rem; }
  .split-table th, .split-table td { padding: 0.5rem 0.4rem; }
  .pace-chart { height: 240px; }
}
.diff-faster { color: #16a34a; font-weight: 600; }
.diff-slower { color: #dc2626; font-weight: 600; }
</style>
