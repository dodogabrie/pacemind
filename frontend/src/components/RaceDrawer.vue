<template>
  <div class="rd-overlay" @click.self="$emit('close')">
    <aside class="rd-panel" role="dialog" :aria-label="plan.plan_name || $t('raceDrawer.details')">
      <header class="rd-header">
        <h2 class="rd-title">{{ plan.plan_name || $t('raceDrawer.race') }}</h2>
        <button class="rd-close" @click="$emit('close')" :aria-label="$t('common.buttons.close')">×</button>
      </header>

      <div v-if="loading && !planStore.dashboard" class="rd-loading">{{ $t('common.loading') }}</div>
      <div v-else-if="planStore.error" class="rd-error">{{ planStore.error }}</div>
      <template v-else-if="plan.id">
        <RaceHeader
          :plan-name="plan.plan_name"
          :race-date="plan.race_date"
          :countdown="planStore.dashboard?.race_countdown"
          :predicted-time="planStore.dashboard?.predicted_time"
          :compliance="compliance?.overall_compliance"
          :fitness-status="trainingLoad?.form"
          :tsb="trainingLoad?.tsb"
        />

        <div class="rd-actions">
          <a :href="`/api/training-plan/${plan.id}/export/ics`" class="rd-action" download>{{ $t('raceDrawer.export_ical') }}</a>
          <button class="rd-action" :disabled="exportingIcu" @click="exportToIntervals">{{ $t('raceDrawer.export_intervals') }}</button>
          <a v-if="plan.target_gpx_id" :href="raceBriefUrl" class="rd-action" download>{{ $t('raceDrawer.race_brief') }}</a>
          <button v-if="isRacePast && plan.status !== 'completed'" class="rd-action rd-action--primary" @click="showCompleteModal = true">
            {{ $t('raceDrawer.complete') }}
          </button>
        </div>

        <div v-if="currentWeekLowCompliance" class="rd-banner">
          {{ $t('raceDrawer.low_compliance') }}
        </div>

        <div class="rd-body">
          <PlanOverviewHeatmap
            v-if="compliance?.weeks?.length"
            :weeks-data="compliance.weeks"
            :current-week="compliance.current_week"
            @select-week="onSelectWeek"
          />

          <div v-if="compliance?.gated" class="rd-gated" @click="subscriptionStore.openUpgradeModal()">
            {{ $t('raceDrawer.gated_compliance') }} <span class="rd-cta">{{ $t('raceDrawer.upgrade') }}</span>
          </div>

          <PredictionTrendChart
            v-if="isPremium && planStore.dashboard?.prediction_history?.length"
            :history="planStore.dashboard.prediction_history"
          />
          <div v-else-if="!isPremium" class="rd-gated" @click="subscriptionStore.openUpgradeModal()">
            {{ $t('raceDrawer.gated_trend') }} <span class="rd-cta">{{ $t('raceDrawer.upgrade') }}</span>
          </div>

          <div
            v-if="!isPremium && planStore.dashboard?.race_countdown != null && planStore.dashboard.race_countdown <= 7"
            class="rd-promo"
            @click="subscriptionStore.openUpgradeModal()"
          >
            {{ $t('raceDrawer.promo') }}
          </div>

          <p v-if="plan.status === 'completed'" class="rd-link">
            <router-link :to="reportRoute">{{ $t('raceDrawer.view_report') }}</router-link>
          </p>
        </div>
      </template>

      <div v-if="showCompleteModal" class="rd-modal-backdrop" @click.self="showCompleteModal = false">
        <div class="rd-modal">
          <h3>{{ $t('raceDrawer.complete') }}</h3>
          <p>{{ $t('raceDrawer.select_activity') }}</p>
          <div v-if="loadingActivities" class="rd-modal-loading">{{ $t('raceDrawer.loading_activities') }}</div>
          <div v-else-if="!recentActivities.length" class="rd-modal-empty">{{ $t('raceDrawer.no_activities') }}</div>
          <div v-else class="rd-activity-list">
            <div
              v-for="act in recentActivities"
              :key="act.id"
              class="rd-activity"
              :class="{ 'rd-activity--selected': selectedActivityId === act.id }"
              @click="selectedActivityId = act.id"
            >
              <span class="rd-act-name">{{ act.name }}</span>
              <span class="rd-act-meta">
                {{ (act.distance / 1000).toFixed(1) }}km · {{ new Date(act.start_date).toLocaleDateString($i18n.locale) }}
              </span>
            </div>
          </div>
          <div class="rd-modal-actions">
            <button class="rd-action" @click="showCompleteModal = false">{{ $t('raceDrawer.cancel') }}</button>
            <button
              class="rd-action rd-action--primary"
              :disabled="!selectedActivityId || completing"
              @click="doComplete"
            >{{ completing ? $t('raceDrawer.generating') : $t('raceDrawer.generate') }}</button>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import RaceHeader from './RaceHeader.vue'
import PlanOverviewHeatmap from './PlanOverviewHeatmap.vue'
import PredictionTrendChart from './PredictionTrendChart.vue'
import { useTrainingPlanStore } from '../stores/trainingPlan'
import { useSubscriptionStore } from '../stores/subscription'
import api from '../services/api'

const props = defineProps({
  planId: { type: [Number, String], required: true },
})
const emit = defineEmits(['close'])

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const planStore = useTrainingPlanStore()
const subscriptionStore = useSubscriptionStore()

const loading = ref(false)
const showCompleteModal = ref(false)
const recentActivities = ref([])
const loadingActivities = ref(false)
const selectedActivityId = ref(null)
const completing = ref(false)

const plan = computed(() => planStore.dashboard?.plan || {})
const compliance = computed(() => planStore.dashboard?.compliance)
const trainingLoad = computed(() => planStore.dashboard?.training_load)
const isPremium = computed(() => planStore.dashboard?.is_premium ?? subscriptionStore.isPremium)

const isRacePast = computed(() => {
  if (!plan.value?.race_date) return false
  return new Date(plan.value.race_date) < new Date()
})

const currentWeekLowCompliance = computed(() => {
  const weeks = compliance.value?.weeks || []
  const cw = compliance.value?.current_week
  const wk = weeks.find(w => w.week_number === cw) || weeks[0]
  if (!wk) return false
  return wk.compliance != null && wk.compliance < 60
})

const raceBriefUrl = computed(() => {
  const gpxId = plan.value?.target_gpx_id
  if (!gpxId) return ''
  const params = new URLSearchParams({ gpx_id: String(gpxId), effort: 'race' })
  if (plan.value?.race_date) params.append('race_date', plan.value.race_date)
  return `/api/agent/race-brief.pdf?${params.toString()}`
})

const reportRoute = computed(() => {
  const langParam = route.params?.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'RaceReport',
    params: { ...(useLang ? { lang: langParam } : {}), planId: plan.value.id },
  }
})

const exportingIcu = ref(false)

// The intervals.icu key stays in this browser only; the server never stores it.
async function exportToIntervals() {
  let key = null
  try { key = localStorage.getItem('icuApiKey') } catch {}
  key = window.prompt(t('raceDrawer.intervals_key_prompt'), key || '')
  if (!key) return
  try { localStorage.setItem('icuApiKey', key) } catch {}
  exportingIcu.value = true
  try {
    const { data } = await api.post(`/training-plan/${plan.value.id}/export/intervals`, { api_key: key })
    window.alert(t('raceDrawer.intervals_done', { n: data.exported }))
  } catch (e) {
    window.alert(e.response?.data?.error || t('raceDrawer.intervals_failed'))
  } finally {
    exportingIcu.value = false
  }
}

async function load() {
  if (!props.planId) return
  loading.value = true
  try {
    await planStore.fetchRaceDashboard(Number(props.planId))
  } finally {
    loading.value = false
  }
}

watch(() => props.planId, load, { immediate: false })

function onKey(e) { if (e.key === 'Escape') emit('close') }

onMounted(() => {
  load()
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
})

watch(showCompleteModal, async (open) => {
  if (!open) return
  selectedActivityId.value = null
  loadingActivities.value = true
  try {
    const { data } = await api.get('/strava/activities')
    recentActivities.value = (data.activities || []).slice(0, 10)
  } catch {
    recentActivities.value = []
  } finally {
    loadingActivities.value = false
  }
})

function onSelectWeek() {
  // Week selection currently handled inside PlanOverviewHeatmap.
}

async function doComplete() {
  if (!selectedActivityId.value) return
  completing.value = true
  try {
    await planStore.completePlan(plan.value.id, selectedActivityId.value)
    showCompleteModal.value = false
    router.push(reportRoute.value)
    emit('close')
  } finally {
    completing.value = false
  }
}
</script>

<style scoped>
.rd-overlay {
  position: fixed; inset: 0; z-index: 900;
  background: rgba(15, 23, 42, .35);
  display: flex; justify-content: flex-end;
}
.rd-panel {
  width: min(520px, 100%); height: 100vh; height: 100dvh;
  background: white; box-shadow: -8px 0 24px rgba(0, 0, 0, .15);
  display: flex; flex-direction: column;
  animation: rd-slide-in .2s ease-out;
  overflow: hidden;
}
@keyframes rd-slide-in { from { transform: translateX(100%); } to { transform: translateX(0); } }
.rd-header { display: flex; justify-content: space-between; align-items: center; padding: .75rem 1rem; padding-top: max(.75rem, env(safe-area-inset-top)); border-bottom: 1px solid #e2e8f0; }
.rd-title { font-size: 1rem; font-weight: 600; color: #0f172a; margin: 0; }
.rd-close { background: none; border: none; font-size: 1.5rem; color: #94a3b8; cursor: pointer; line-height: 1; width: 44px; height: 44px; margin: -.5rem -.75rem -.5rem 0; flex-shrink: 0; }
.rd-loading, .rd-error { padding: 1rem; color: #64748b; }
.rd-error { color: #b91c1c; }
.rd-actions { display: flex; gap: .5rem; padding: .75rem 1rem; flex-wrap: wrap; border-bottom: 1px solid #f1f5f9; }
.rd-action {
  padding: .35rem .75rem; border: 1px solid #cbd5e1; border-radius: 4px;
  background: white; color: #475569; cursor: pointer; font-size: .8rem;
  text-decoration: none; display: inline-block;
}
.rd-action:hover { background: #f1f5f9; }
.rd-action--primary { background: #6366f1; color: white; border-color: #6366f1; }
.rd-action--primary:hover { background: #4f46e5; }
.rd-action--primary:disabled { background: #c7d2fe; cursor: not-allowed; }
.rd-banner {
  margin: .75rem 1rem; padding: .5rem .75rem;
  background: #fef3c7; border: 1px solid #f59e0b; border-radius: 4px;
  font-size: .8rem; color: #92400e;
}
.rd-body { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 1rem; padding-bottom: max(1rem, env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 1rem; }
.rd-gated, .rd-promo {
  padding: .65rem .85rem; border-radius: 4px;
  font-size: .8rem; cursor: pointer;
}
.rd-gated { background: #f1f5f9; color: #475569; }
.rd-promo { background: linear-gradient(135deg, #fde68a 0%, #fbbf24 100%); color: #78350f; font-weight: 600; }
.rd-cta { color: #6366f1; font-weight: 600; }
.rd-link { font-size: .85rem; }
.rd-modal-backdrop {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(15, 23, 42, .55);
  display: flex; align-items: center; justify-content: center;
  padding: 1rem;
}
.rd-modal {
  background: white; border-radius: 8px; padding: 1.25rem;
  max-width: 500px; width: 100%; max-height: 80vh; max-height: 80dvh; overflow-y: auto;
}
.rd-modal h3 { margin: 0 0 .5rem; font-size: 1rem; }
.rd-modal-loading, .rd-modal-empty { color: #64748b; padding: .75rem 0; font-size: .85rem; }
.rd-activity-list { max-height: 320px; overflow-y: auto; margin: .75rem 0; display: flex; flex-direction: column; gap: 4px; }
.rd-activity {
  padding: .5rem .75rem; border: 1px solid #e2e8f0; border-radius: 4px;
  cursor: pointer; display: flex; flex-direction: column; gap: 2px;
}
.rd-activity:hover { background: #f8fafc; }
.rd-activity--selected { border-color: #6366f1; background: #eef2ff; }
.rd-act-name { font-size: .85rem; color: #0f172a; }
.rd-act-meta { font-size: .75rem; color: #64748b; }
.rd-modal-actions { display: flex; gap: .5rem; justify-content: flex-end; margin-top: .75rem; }
@media (max-width: 640px) {
  .rd-action { min-height: 44px; display: inline-flex; align-items: center; }
}
</style>
