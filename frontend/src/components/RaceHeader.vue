<template>
  <div class="race-header">
    <div class="race-header-main">
      <h1 class="race-name">{{ planName }}</h1>
      <div class="race-meta">
        <span v-if="raceDate" class="meta-item">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          {{ formattedDate }}
        </span>
        <span v-if="countdown !== null" class="meta-item meta-countdown" :class="countdownClass">
          {{ $t('race_header.countdown', countdown) }}
        </span>
      </div>
    </div>
    <div class="race-header-stats">
      <div class="stat-card" v-if="predictedTime">
        <span class="stat-label">{{ $t('race_header.predicted') }}</span>
        <span class="stat-value">{{ formattedPrediction }}</span>
      </div>
      <div class="stat-card" v-if="compliance !== null">
        <span class="stat-label">{{ $t('race_header.compliance') }}</span>
        <span class="stat-value" :class="complianceClass">{{ compliance }}%</span>
      </div>
      <div class="stat-card" v-if="fitnessStatus">
        <span class="stat-label">{{ $t('race_header.fitness') }}</span>
        <span class="stat-value" :class="fitnessClass">{{ fitnessLabel }}</span>
        <span v-if="tsb !== null" class="stat-sub">TSB {{ tsb > 0 ? '+' : '' }}{{ tsb }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t, te, locale } = useI18n()

const props = defineProps({
  planName: { type: String, default: '' },
  raceDate: { type: String, default: null },
  countdown: { type: Number, default: null },
  predictedTime: { type: Number, default: null },
  compliance: { type: Number, default: null },
  fitnessStatus: { type: String, default: null },
  tsb: { type: Number, default: null },
})

const formattedDate = computed(() => {
  if (!props.raceDate) return ''
  const d = new Date(props.raceDate)
  return d.toLocaleDateString(locale.value, { day: 'numeric', month: 'long', year: 'numeric' })
})

const formattedPrediction = computed(() => {
  if (!props.predictedTime) return '--'
  const totalSec = Math.round(props.predictedTime)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

const countdownClass = computed(() => {
  if (props.countdown === null) return ''
  if (props.countdown <= 7) return 'countdown-urgent'
  if (props.countdown <= 14) return 'countdown-soon'
  return ''
})

const complianceClass = computed(() => {
  if (props.compliance === null) return ''
  if (props.compliance >= 80) return 'compliance-good'
  if (props.compliance >= 60) return 'compliance-ok'
  return 'compliance-low'
})

const fitnessLabel = computed(() => {
  const key = `race_header.status.${props.fitnessStatus}`
  return (props.fitnessStatus && te(key)) ? t(key) : (props.fitnessStatus || '--')
})

const fitnessClass = computed(() => {
  if (!props.fitnessStatus) return ''
  if (props.fitnessStatus.includes('fresh')) return 'fitness-fresh'
  if (props.fitnessStatus === 'neutral') return 'fitness-neutral'
  return 'fitness-fatigued'
})
</script>

<style scoped>
.race-header {
  background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
  border-radius: 0.75rem;
  padding: 1.25rem 1.5rem;
  color: white;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.race-name {
  font-size: 1.25rem;
  font-weight: 800;
  margin: 0 0 0.375rem;
  letter-spacing: -0.01em;
}

.race-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  align-items: center;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  opacity: 0.85;
}

.meta-countdown {
  font-weight: 700;
  background: rgba(255,255,255,0.15);
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
}
.countdown-urgent {
  background: rgba(239, 68, 68, 0.3);
}
.countdown-soon {
  background: rgba(234, 179, 8, 0.25);
}

.race-header-stats {
  display: flex;
  gap: 1rem;
}

.stat-card {
  background: rgba(255,255,255,0.1);
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  text-align: center;
  min-width: 80px;
}

.stat-label {
  display: block;
  font-size: 0.625rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.7;
  margin-bottom: 0.125rem;
}

.stat-value {
  display: block;
  font-size: 1rem;
  font-weight: 700;
}

.stat-sub {
  display: block;
  font-size: 0.625rem;
  opacity: 0.7;
}

.compliance-good { color: #86efac; }
.compliance-ok { color: #fde68a; }
.compliance-low { color: #fca5a5; }

.fitness-fresh { color: #86efac; }
.fitness-neutral { color: #e2e8f0; }
.fitness-fatigued { color: #fca5a5; }

@media (max-width: 640px) {
  .race-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .race-header {
    padding: 1rem;
  }
  .race-header-stats {
    width: 100%;
    gap: 0.5rem;
  }
  .stat-card {
    flex: 1;
    min-width: 0;
  }
}
</style>
