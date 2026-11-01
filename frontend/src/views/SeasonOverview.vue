<template>
  <div class="season-overview">
    <AuthGate v-if="authStore.authChecked && !authStore.isAuthenticated" />
    <template v-else>
    <h1 class="season-title">{{ $t('season.title') }}</h1>

    <div v-if="planStore.loading && !planStore.season" class="season-loading">
      {{ $t('season.loading') }}
    </div>
    <div v-else-if="planStore.error" class="season-error">
      {{ planStore.error }}
    </div>
    <template v-else-if="planStore.season">
      <!-- Warnings -->
      <div v-if="planStore.season.warnings?.length" class="season-warnings">
        <div v-for="(w, i) in planStore.season.warnings" :key="i" class="warning-card">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          {{ w }}
        </div>
      </div>

      <!-- Timeline -->
      <div v-if="planStore.season.races?.length" class="timeline">
        <div
          v-for="race in planStore.season.races"
          :key="race.id"
          class="race-card"
          :class="[`priority-${(race.race_priority || 'none').toLowerCase()}`]"
          @click="goToRace(race)"
        >
          <div class="race-header">
            <span v-if="race.race_priority" class="priority-badge" :class="`badge-${race.race_priority.toLowerCase()}`">
              {{ race.race_priority }}
            </span>
            <h3 class="race-name">{{ race.plan_name }}</h3>
          </div>

          <div class="race-meta">
            <span v-if="race.race_date" class="race-date">
              {{ formatDate(race.race_date) }}
            </span>
            <span v-if="race.countdown != null && race.countdown > 0" class="race-countdown">
              {{ $t('season.days_to_go', { n: race.countdown }) }}
            </span>
            <span v-else-if="race.countdown === 0" class="race-countdown race-today">
              {{ $t('season.race_day') }}
            </span>
          </div>

          <div class="race-details">
            <span v-if="race.predicted_time" class="race-prediction">
              {{ formatTime(race.predicted_time) }}
            </span>
            <span class="race-status" :class="`status-${race.status}`">
              {{ $te(`season.status.${race.status}`) ? $t(`season.status.${race.status}`) : race.status }}
            </span>
            <span v-if="race.has_result" class="race-has-report">{{ $t('season.report_available') }}</span>
          </div>
        </div>
      </div>

      <div v-else class="season-empty">
        {{ $t('season.empty') }}
      </div>
    </template>
    </template>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useTrainingPlanStore } from '../stores/trainingPlan'
import { useAuthStore } from '../stores/auth'
import AuthGate from '../components/AuthGate.vue'
import { formatTime } from '../utils/formatters'
import { useI18n } from 'vue-i18n'

const { locale } = useI18n()

const router = useRouter()
const route = useRoute()
const planStore = useTrainingPlanStore()
const authStore = useAuthStore()

const formatDate = (iso) => {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(locale.value, { month: 'short', day: 'numeric', year: 'numeric' })
}

const goToRace = (race) => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  const params = { ...(useLang ? { lang: langParam } : {}), planId: race.id }

  if (race.has_result) {
    router.push({ name: 'RaceReport', params })
  } else {
    router.push({ name: 'RaceDashboard', params })
  }
}

onMounted(async () => {
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  planStore.fetchSeason()
})
</script>

<style scoped>
.season-overview {
  max-width: 900px;
  margin: 0 auto;
  padding: 1rem;
}

.season-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 1.5rem;
}

.season-loading, .season-error, .season-empty {
  text-align: center;
  padding: 3rem;
  color: #64748b;
  font-size: 0.875rem;
}
.season-error { color: #ef4444; }

.season-warnings {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.warning-card {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #fef3c7;
  border: 1px solid #f59e0b;
  border-radius: 0.5rem;
  padding: 0.625rem 1rem;
  font-size: 0.8125rem;
  color: #92400e;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.race-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
  cursor: pointer;
  transition: all 0.15s;
  border-left: 4px solid #94a3b8;
}
.race-card:hover {
  border-color: #047857;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.race-card.priority-a { border-left-color: #eab308; }
.race-card.priority-b { border-left-color: #94a3b8; }
.race-card.priority-c { border-left-color: #d97706; }

.race-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}

.priority-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  font-size: 0.6875rem;
  font-weight: 800;
  color: white;
}
.badge-a { background: #eab308; }
.badge-b { background: #94a3b8; }
.badge-c { background: #d97706; }

.race-name {
  font-size: 0.9375rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.race-meta {
  display: flex;
  gap: 0.75rem;
  font-size: 0.8125rem;
  color: #64748b;
  margin-bottom: 0.5rem;
}

.race-countdown {
  font-weight: 600;
  color: #047857;
}
.race-today {
  color: #dc2626;
}

.race-details {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  font-size: 0.75rem;
}

.race-prediction {
  font-weight: 700;
  color: #334155;
  font-family: monospace;
}

.race-status {
  padding: 0.125rem 0.5rem;
  border-radius: 999px;
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.625rem;
  letter-spacing: 0.03em;
}
.status-active { background: #dcfce7; color: #166534; }
.status-draft { background: #f1f5f9; color: #64748b; }
.status-completed { background: #e0e7ff; color: #4338ca; }

.race-has-report {
  color: #6366f1;
  font-weight: 600;
}

/* Phones: the app shell already provides the side gutter. */
@media (max-width: 640px) {
  .season-overview { padding: 0.5rem 0 1rem; }
  .season-loading, .season-error, .season-empty { padding: 3rem 1rem; }
  .race-card { padding: 0.875rem 1rem; }
  .race-name { overflow-wrap: anywhere; }
  .race-meta, .race-details { flex-wrap: wrap; row-gap: 0.375rem; }
}
</style>
