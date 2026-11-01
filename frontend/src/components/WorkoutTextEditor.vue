<template>
  <div class="wte-overlay" @click.self="$emit('close')">
    <div class="wte">
      <div class="wte-header">
        <div>
          <h3 class="wte-title">{{ $t('workoutEditor.title') }}</h3>
          <div class="wte-subtitle"><template v-if="weekNumber">{{ $t('workoutEditor.week', { n: weekNumber }) }} &middot; </template>{{ displayDay }}</div>
        </div>
        <button class="wte-close" :aria-label="$t('common.buttons.close')" @click="$emit('close')">&times;</button>
      </div>

      <div class="wte-meta">
        <input v-model="title" :placeholder="$t('workoutEditor.title_placeholder')" class="wte-input wte-title-input" />
      </div>

      <div class="wte-grid">
        <div class="wte-pane">
          <label class="wte-label">{{ $t('workoutEditor.text_label') }}</label>
          <textarea
            v-model="text"
            class="wte-textarea"
            spellcheck="false"
            rows="14"
            @input="onTextChange"
          ></textarea>
          <details class="wte-cheatsheet">
            <summary>{{ $t('workoutEditor.cheatsheet') }}</summary>
            <pre class="wte-cheatsheet-body">{{ $t('workoutEditor.cheatsheet_body') }}</pre>
          </details>
        </div>

        <div class="wte-pane">
          <label class="wte-label">{{ $t('workoutEditor.preview') }}</label>
          <div class="wte-preview" :class="{ 'wte-preview--invalid': !previewValid }">
            <div v-if="loading" class="wte-loading">{{ $t('workoutEditor.parsing') }}</div>
            <template v-else>
              <div v-if="parseErrors.length" class="wte-errors">
                <div v-for="(e, i) in parseErrors" :key="i" class="wte-error">
                  {{ $t('workoutEditor.line_error', { line: e.line, msg: e.message }) }}
                </div>
              </div>
              <div v-if="schemaError" class="wte-error">{{ schemaError }}</div>

              <div class="wte-summary" v-if="summary">
                <span v-if="summary.distance_km !== null">{{ summary.distance_km }} km</span>
                <span v-if="summary.duration_min !== null">{{ formatDuration(summary.duration_min) }}</span>
                <span v-if="summary.elevation_m !== null">{{ summary.elevation_m }}m D+</span>
                <span class="wte-summary-count">{{ $t('workoutEditor.steps', summary.step_count) }}</span>
              </div>

              <ol class="wte-steps">
                <li v-for="(step, i) in steps" :key="i" class="wte-step" :class="`wte-step--${step.type}`">
                  <template v-if="step.type === 'repeat'">
                    <strong>{{ step.repeats }}×</strong>
                    <ol class="wte-substeps">
                      <li v-for="(child, j) in step.steps" :key="j" :class="`wte-step--${child.type}`">
                        {{ formatStep(child) }}
                      </li>
                    </ol>
                  </template>
                  <template v-else>
                    {{ formatStep(step) }}
                  </template>
                </li>
              </ol>
            </template>
          </div>
        </div>
      </div>

      <div class="wte-footer">
        <span v-if="error" class="wte-error">{{ error }}</span>
        <button class="wte-btn wte-btn--ghost" @click="$emit('close')">{{ $t('workoutEditor.cancel') }}</button>
        <button
          class="wte-btn wte-btn--primary"
          :disabled="!canSave"
          @click="save"
        >{{ saving ? $t('workoutEditor.saving') : $t('workoutEditor.save') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useTrainingPlanStore } from '../stores/trainingPlan'
import api from '../services/api'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  planId: { type: Number, default: 0 },
  weekNumber: { type: Number, default: 0 },
  dayName: { type: String, default: '' },
  day: { type: Object, required: true },
  // Calendar mode: when true, save calls /calendar/days (auto-resolves the
  // target plan and creates the Personal plan if needed) instead of the
  // plan-day PATCH endpoint.
  calendarMode: { type: Boolean, default: false },
  calendarDate: { type: String, default: '' },
})

const emit = defineEmits(['close', 'saved'])

const planStore = useTrainingPlanStore()
const { t, locale } = useI18n()

// dayName is the backend's English key; show a localized weekday when we know the date.
const displayDay = computed(() => {
  const iso = props.calendarDate || props.day?.date
  return iso ? new Date(iso + 'T00:00:00').toLocaleDateString(locale.value, { weekday: 'long', day: 'numeric', month: 'short' }) : props.dayName
})

const text = ref('')
const title = ref(props.day?.title || '')
const steps = ref([])
const summary = ref(null)
const parseErrors = ref([])
const schemaError = ref(null)
const previewValid = ref(true)
const loading = ref(false)
const saving = ref(false)
const error = ref('')

let debounceTimer = null

const canSave = computed(() => previewValid.value && !saving.value && steps.value.length > 0)

onMounted(() => {
  text.value = stepsToText(props.day?.steps || [])
  if (text.value) onTextChange()
})

function stepsToText(steps) {
  if (!steps || !steps.length) return ''
  // Lightweight client-side renderer; backend round-trips on save anyway.
  const lines = []
  const TYPE_LABEL = stepLabels()
  const run = TYPE_LABEL.work
  const fmtDist = (m) => (m >= 1000 ? `${+(m / 1000).toFixed(2)}km` : `${Math.round(m)}m`)
  const fmtDur = (min) => {
    if (min >= 60 && Number.isInteger(min)) {
      const h = Math.floor(min / 60); const r = min - h * 60
      return r ? `${h}h${r}min` : `${h}h`
    }
    return `${+min.toFixed(2)}min`
  }
  const elevSign = (s, indented) => {
    const d = s.elevation_direction
    if (d === 'up') return '+'
    if (d === 'down') return '-'
    if (d === 'round_trip') return '+-'
    return indented ? '+' : '+-'
  }
  const renderStep = (s, indent) => {
    const prefix = '  '.repeat(indent)
    if (s.type === 'repeat') {
      lines.push(`${prefix}${s.repeats}x:`)
      for (const c of (s.steps || [])) renderStep(c, indent + 1)
      return
    }
    const parts = [TYPE_LABEL[s.type] || run]
    if (s.distance_m) parts.push(fmtDist(s.distance_m))
    if (s.elevation_gain_m) parts.push(`${elevSign(s, indent > 0)}${Math.round(s.elevation_gain_m)}m`)
    if (s.duration_min) parts.push(fmtDur(s.duration_min))
    const t = s.target || {}
    if (t.type === 'effort') parts.push(`RPE ${t.rpe}`)
    else if (t.type === 'hr' && t.zone) parts.push(`Z${t.zone}`)
    else if (t.type === 'pace' && t.zone) {
      const z = String(t.zone)
      parts.push(z.match(/^\d+:\d{2}/) ? `@ ${z.includes('/km') ? z : z + '/km'}` : `@ ${z}`)
    }
    if (s.terrain) parts.push(`on ${terrainLabel(s.terrain)}`)
    let line = parts.join(' ')
    if (s.notes) line += ` # ${s.notes}`
    lines.push(`${prefix}${line}`)
  }
  for (const s of steps) renderStep(s, 0)
  return lines.join('\n')
}

function onTextChange() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(parseText, 250)
}

async function parseText() {
  loading.value = true
  try {
    const { data } = await api.post('/api/training-plan/parse-workout', { text: text.value })
    steps.value = data.steps || []
    summary.value = data.summary
    parseErrors.value = data.errors || []
    schemaError.value = data.schema_error
    previewValid.value = !!data.valid
  } catch (e) {
    error.value = e?.response?.data?.error || t('workoutEditor.parse_failed')
    previewValid.value = false
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  error.value = ''
  try {
    const cleanSteps = steps.value.map(stripPredictedFlag)
    if (props.calendarMode) {
      const date = props.calendarDate || props.day?.date
      if (!date) throw new Error('Missing date for calendar workout')
      await planStore.addCalendarWorkout(date, {
        title: title.value || undefined,
        steps: cleanSteps,
      })
    } else {
      await planStore.updateWorkoutDay(props.planId, props.weekNumber, props.dayName, {
        title: title.value || props.day.title,
        steps: cleanSteps,
      })
    }
    emit('saved', { steps: cleanSteps, title: title.value })
    emit('close')
  } catch (e) {
    error.value = e?.response?.data?.error || e?.message || t('workoutEditor.save_failed')
  } finally {
    saving.value = false
  }
}

function stripPredictedFlag(step) {
  const out = { ...step }
  delete out.duration_predicted
  if (out.steps) out.steps = out.steps.map(stripPredictedFlag)
  return out
}

function formatStep(step) {
  const parts = []
  const labels = stepLabels()
  parts.push(labels[step.type] || step.type)
  if (step.distance_m) parts.push(step.distance_m >= 1000 ? `${(step.distance_m / 1000).toFixed(2)} km` : `${Math.round(step.distance_m)} m`)
  if (step.elevation_gain_m) {
    const dir = step.elevation_direction
    const sign = dir === 'down' ? '−' : dir === 'round_trip' ? '±' : '+'
    parts.push(`${sign}${Math.round(step.elevation_gain_m)} m`)
  }
  if (step.duration_min) {
    const tag = step.duration_predicted ? '~' : ''
    parts.push(`${tag}${formatDuration(step.duration_min)}`)
  }
  const t = step.target || {}
  if (t.type === 'effort') parts.push(`RPE ${t.rpe}`)
  else if (t.type === 'hr') parts.push(`Z${t.zone}`)
  else if (t.type === 'pace') parts.push(`@ ${t.zone}`)
  if (step.terrain) parts.push(terrainLabel(step.terrain))
  if (step.notes) parts.push(`— ${step.notes}`)
  return parts.join(' · ')
}

// Step keywords double as parser syntax; the backend accepts both EN and IT.
function stepLabels() {
  return Object.fromEntries(['warmup', 'work', 'rest', 'cooldown'].map((k) => [k, t(`workoutEditor.kw.${k}`)]))
}

function terrainLabel(terrain) {
  return ['road', 'trail', 'mixed'].includes(terrain) ? t(`workoutEditor.terrain.${terrain}`) : terrain
}

function formatDuration(min) {
  if (!min && min !== 0) return ''
  if (min >= 60) {
    const h = Math.floor(min / 60)
    const r = Math.round(min - h * 60)
    return r ? `${h}h${r}m` : `${h}h`
  }
  return `${Math.round(min)} min`
}
</script>

<style scoped>
.wte-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, .55); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 1rem; }
.wte { background: white; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,.25); width: min(960px, 100%); max-height: 90vh; overflow: auto; display: flex; flex-direction: column; }
.wte-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 1rem 1.25rem; border-bottom: 1px solid #e2e8f0; }
.wte-title { font-size: 1.1rem; font-weight: 600; color: #0f172a; margin: 0; }
.wte-subtitle { font-size: .8rem; color: #64748b; margin-top: 2px; }
.wte-close { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #94a3b8; padding: 0 .25rem; }
.wte-meta { padding: .75rem 1.25rem 0; }
.wte-input { width: 100%; padding: .5rem .75rem; border: 1px solid #cbd5e1; border-radius: 6px; font-size: .9rem; }
.wte-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; padding: 1rem 1.25rem; flex: 1; min-height: 0; }
@media (max-width: 720px) { .wte-grid { grid-template-columns: 1fr; } }
.wte-pane { display: flex; flex-direction: column; min-height: 0; }
.wte-label { font-size: .75rem; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: #64748b; margin-bottom: .25rem; }
.wte-textarea { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: .85rem; line-height: 1.5; padding: .75rem; border: 1px solid #cbd5e1; border-radius: 6px; resize: vertical; min-height: 280px; background: #f8fafc; }
.wte-textarea:focus { outline: none; border-color: #6366f1; background: white; }
.wte-cheatsheet { margin-top: .5rem; font-size: .75rem; color: #64748b; }
.wte-cheatsheet summary { cursor: pointer; user-select: none; }
.wte-cheatsheet-body { font-family: ui-monospace, monospace; background: #f1f5f9; padding: .5rem .75rem; border-radius: 4px; margin-top: .25rem; white-space: pre-wrap; }
.wte-preview { border: 1px solid #cbd5e1; border-radius: 6px; padding: .75rem; overflow: auto; background: white; min-height: 280px; }
.wte-preview--invalid { border-color: #f87171; }
.wte-loading { color: #94a3b8; font-size: .85rem; }
.wte-errors { background: #fef2f2; padding: .5rem .75rem; border-radius: 4px; margin-bottom: .5rem; }
.wte-error { color: #b91c1c; font-size: .8rem; }
.wte-summary { display: flex; gap: .75rem; font-size: .85rem; color: #334155; padding: .25rem .5rem; background: #eef2ff; border-radius: 4px; margin-bottom: .5rem; flex-wrap: wrap; }
.wte-summary-count { margin-left: auto; color: #6366f1; font-weight: 500; }
.wte-steps { list-style: none; padding: 0; margin: 0; font-size: .85rem; }
.wte-step { padding: .35rem .5rem; border-left: 3px solid #cbd5e1; margin-bottom: .25rem; }
.wte-step--warmup { border-color: #fcd34d; }
.wte-step--cooldown { border-color: #93c5fd; }
.wte-step--rest { border-color: #cbd5e1; }
.wte-step--work { border-color: #f97316; }
.wte-substeps { list-style: none; padding-left: .75rem; margin: .25rem 0 0; }
.wte-substeps li { padding: .15rem .35rem; border-left: 2px dashed #e2e8f0; margin-bottom: .15rem; }
.wte-footer { display: flex; gap: .5rem; align-items: center; padding: .75rem 1.25rem; border-top: 1px solid #e2e8f0; }
.wte-footer .wte-error { margin-right: auto; }
.wte-btn { padding: .5rem 1rem; border-radius: 6px; font-size: .85rem; font-weight: 500; cursor: pointer; border: 1px solid transparent; }
.wte-btn--ghost { background: white; border-color: #cbd5e1; color: #475569; }
.wte-btn--primary { background: #6366f1; color: white; }
.wte-btn--primary:disabled { background: #c7d2fe; cursor: not-allowed; }

/* Phones: full-screen sheet, sticky footer above the home indicator,
   16px fields so iOS doesn't zoom on focus. */
@media (max-width: 640px) {
  .wte-overlay { padding: 0; align-items: stretch; }
  .wte { border-radius: 0; max-height: none; height: 100dvh; padding-top: env(safe-area-inset-top); }
  .wte-header { padding: .5rem .5rem .5rem 1rem; align-items: center; }
  .wte-close { min-width: 44px; min-height: 44px; font-size: 1.75rem; }
  .wte-meta { padding: .75rem 1rem 0; }
  .wte-grid { padding: .75rem 1rem; gap: .75rem; flex: none; align-content: start; }
  .wte-input, .wte-textarea { font-size: 16px; }
  .wte-input { min-height: 44px; }
  .wte-textarea { min-height: 180px; height: 38dvh; }
  .wte-preview { min-height: 0; }
  .wte-cheatsheet summary { padding: .5rem 0; }
  .wte-cheatsheet-body { overflow-x: auto; }
  .wte-footer {
    position: sticky; bottom: 0; background: white; flex-wrap: wrap;
    padding: .625rem 1rem calc(.625rem + env(safe-area-inset-bottom));
  }
  .wte-footer .wte-error { flex-basis: 100%; }
  .wte-btn { min-height: 44px; flex: 1; font-size: .95rem; }
}
</style>
