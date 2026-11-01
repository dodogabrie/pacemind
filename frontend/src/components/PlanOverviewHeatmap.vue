<template>
  <div class="plan-overview">
    <h3 class="overview-title">{{ $t('planOverview.title') }}</h3>
    <div class="weeks-grid">
      <div
        v-for="week in weeksData"
        :key="week.week_number"
        class="week-bar"
        :class="{ 'week-bar--selected': selectedWeek === week.week_number, 'week-bar--current': week.week_number === currentWeek }"
        @click="$emit('select-week', week.week_number)"
        :title="$t('planOverview.bar_title', { n: week.week_number, theme: week.theme || '', status: week.compliance != null ? week.compliance + '%' : $t('planOverview.upcoming') })"
      >
        <div class="week-bar-fill" :style="{ height: barHeight(week), background: barColor(week) }"></div>
        <span class="week-label">{{ $t('planOverview.week_short', { n: week.week_number }) }}</span>
        <span v-if="week.compliance != null" class="week-pct">{{ week.compliance }}%</span>
      </div>
    </div>
    <!-- Expanded week detail -->
    <div v-if="expandedWeek" class="expanded-detail">
      <div class="expanded-header">
        <strong>{{ $t('calendarWeek.week', { n: expandedWeek.week_number }) }}</strong>
        <span v-if="expandedWeek.theme" class="expanded-theme">{{ expandedWeek.theme }}</span>
        <span v-if="expandedWeek.compliance != null" class="expanded-compliance" :class="complianceClass(expandedWeek.compliance)">
          {{ expandedWeek.compliance }}%
        </span>
      </div>
      <div class="expanded-days">
        <div
          v-for="day in expandedWeek.days"
          :key="day.day"
          class="day-chip"
          :class="`day-chip--${day.status}`"
        >
          <span class="day-name">{{ $te(`calendarWeek.days.${day.day}`) ? $t(`calendarWeek.days.${day.day}`) : day.day.slice(0, 3) }}</span>
          <span class="day-type">{{ day.planned?.workout_type ? ($te(`calendarWeek.types.${day.planned.workout_type}`) ? $t(`calendarWeek.types.${day.planned.workout_type}`) : day.planned.workout_type) : '-' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  weeksData: { type: Array, default: () => [] },
  currentWeek: { type: Number, default: 1 },
})

const emit = defineEmits(['select-week'])

const selectedWeek = ref(null)

watch(() => props.currentWeek, (val) => {
  if (selectedWeek.value === null) selectedWeek.value = val
}, { immediate: true })

const expandedWeek = computed(() => {
  if (selectedWeek.value === null) return null
  return props.weeksData.find(w => w.week_number === selectedWeek.value) || null
})

// Click handler updates selectedWeek
watch(() => selectedWeek.value, () => {})

// Override emit handler to also set local selected
const onSelectWeek = (weekNum) => {
  selectedWeek.value = weekNum
  emit('select-week', weekNum)
}

const barHeight = (week) => {
  if (week.compliance == null) return '20%'
  return `${Math.max(15, week.compliance)}%`
}

const barColor = (week) => {
  if (week.compliance == null) return '#cbd5e1' // gray for upcoming
  if (week.compliance >= 80) return '#34d399' // green
  if (week.compliance >= 60) return '#fbbf24' // yellow
  return '#f87171' // red
}

const complianceClass = (val) => {
  if (val >= 80) return 'compliance-good'
  if (val >= 60) return 'compliance-ok'
  return 'compliance-low'
}
</script>

<style scoped>
.plan-overview {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1rem;
}

.overview-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin: 0 0 0.75rem;
}

.weeks-grid {
  display: flex;
  gap: 0.25rem;
  align-items: flex-end;
  height: 80px;
}

.week-bar {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  position: relative;
  height: 100%;
  justify-content: flex-end;
  border-radius: 0.25rem;
  transition: background 0.15s;
}
.week-bar:hover {
  background: #f0fdf4;
}
.week-bar--selected {
  background: #f0fdf4;
}
.week-bar--current .week-label {
  font-weight: 800;
  color: #047857;
}

.week-bar-fill {
  width: 100%;
  border-radius: 0.25rem 0.25rem 0 0;
  min-height: 4px;
  transition: height 0.3s;
}

.week-label {
  font-size: 0.5625rem;
  color: #64748b;
  margin-top: 0.125rem;
}

.week-pct {
  font-size: 0.5rem;
  color: #94a3b8;
}

.expanded-detail {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid #e2e8f0;
}

.expanded-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  font-size: 0.8125rem;
}

.expanded-theme {
  color: #64748b;
  font-style: italic;
}

.expanded-compliance {
  font-weight: 700;
  font-size: 0.75rem;
  padding: 0.0625rem 0.375rem;
  border-radius: 9999px;
}
.compliance-good { background: #dcfce7; color: #047857; }
.compliance-ok { background: #fef9c3; color: #92400e; }
.compliance-low { background: #fee2e2; color: #b91c1c; }

.expanded-days {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.day-chip {
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 0.6875rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 3.5rem;
  border: 1px solid #e2e8f0;
}
.day-chip--completed { background: #dcfce7; border-color: #86efac; }
.day-chip--partial { background: #fef9c3; border-color: #fde68a; }
.day-chip--missed { background: #fee2e2; border-color: #fca5a5; }
.day-chip--rest { background: #f1f5f9; border-color: #e2e8f0; }
.day-chip--upcoming { background: #f8fafc; border-color: #e2e8f0; }

.day-name {
  font-weight: 600;
  font-size: 0.625rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.day-type {
  font-size: 0.5625rem;
  color: #64748b;
}

/* Phones: long plans would squeeze bars to ~10px; give each week a tappable
   width and let the strip scroll sideways. Days become a 7-column row. */
@media (max-width: 640px) {
  .weeks-grid {
    height: 96px;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
    padding-bottom: 2px;
  }
  .week-bar { flex: 1 0 32px; }
  .week-label { font-size: 0.625rem; }
  .expanded-header { flex-wrap: wrap; }
  .expanded-days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .day-chip { min-width: 0; padding: 0.375rem 0.125rem; min-height: 44px; justify-content: center; }
  .day-type { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
</style>
