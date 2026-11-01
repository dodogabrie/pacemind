<template>
  <div v-if="open" class="tpw-backdrop" @click.self="onBackdrop">
    <div class="tpw-modal" role="dialog" aria-modal="true">
      <header class="tpw-header">
        <h2>{{ $t('trainingPrefs.title') }}</h2>
        <div class="tpw-progress">
          <span
            v-for="(s, i) in visibleSteps"
            :key="s.id"
            class="tpw-dot"
            :class="{ 'tpw-dot--on': i <= activeIdx }"
          />
        </div>
        <button v-if="!blocking" class="tpw-x" @click="close" :aria-label="$t('common.buttons.close')">×</button>
      </header>

      <section class="tpw-body">
        <div v-if="!currentStep" class="tpw-loading">{{ $t('common.loading') }}</div>
        <div v-else>
          <h3 class="tpw-step-title">{{ stepTitle(currentStep.id) }}</h3>
          <p v-if="stepHelp(currentStep.id)" class="tpw-step-help">{{ stepHelp(currentStep.id) }}</p>

          <div v-for="f in currentStep.fields" :key="f.key" class="tpw-field">
            <label class="tpw-label">
              {{ fieldLabel(f) }}
              <span v-if="!f.optional" class="tpw-req">*</span>
            </label>
            <p v-if="fieldHelp(f)" class="tpw-help">{{ fieldHelp(f) }}</p>

            <input
              v-if="f.type === 'number'"
              v-model.number="answers[f.key]"
              type="number"
              inputmode="decimal"
              :min="f.min"
              :max="f.max"
              :step="f.step || 1"
              class="tpw-input"
            />

            <select
              v-else-if="f.type === 'select'"
              v-model="answers[f.key]"
              class="tpw-input"
            >
              <option v-for="opt in f.options" :key="opt" :value="opt">
                {{ optionLabel(f.key, opt) }}
              </option>
            </select>

            <div v-else-if="f.type === 'multiselect'" class="tpw-chips">
              <button
                v-for="opt in f.options"
                :key="opt"
                type="button"
                class="tpw-chip"
                :class="{ 'tpw-chip--on': (answers[f.key] || []).includes(opt) }"
                @click="toggleMulti(f.key, opt)"
              >{{ dayShort(opt) }}</button>
            </div>

            <div v-else-if="f.type === 'route_picker'" class="tpw-route-picker">
              <select v-model="answers[f.key]" class="tpw-input">
                <option :value="null">{{ $t('trainingPrefs.none') }}</option>
                <option v-for="r in routes" :key="r.id" :value="r.id">
                  {{ r.name }} — {{ r.distance_km?.toFixed?.(1) || r.distance_km }}km / {{ Math.round(r.elevation_gain_m || 0) }}m D+
                </option>
              </select>
              <div class="tpw-cta-row">
                <button
                  v-for="cta in (f.cta_actions || [])"
                  :key="cta.action"
                  type="button"
                  class="tpw-cta"
                  @click="$emit('cta', cta)"
                >{{ ctaLabel(cta) }}</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer class="tpw-footer">
        <button
          type="button"
          class="tpw-btn tpw-btn--ghost"
          @click="prev"
          :disabled="activeIdx === 0"
        >{{ $t('trainingPrefs.back') }}</button>
        <button
          type="button"
          class="tpw-btn"
          @click="next"
          :disabled="!canAdvance"
        >{{ isLast ? $t('trainingPrefs.save') : $t('trainingPrefs.next') }}</button>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../services/api'
import { useI18n } from 'vue-i18n'

const { t, te } = useI18n()

const props = defineProps({
  open: { type: Boolean, default: false },
  blocking: { type: Boolean, default: false },
  schema: { type: Object, default: null },
})

const emit = defineEmits(['close', 'saved', 'cta'])

const wizardSchema = ref(null)
const answers = ref({})
const activeIdx = ref(0)
const routes = ref([])

// Field/step copy may arrive from the backend schema as Italian-only
// (label_it/help_it); prefer the locale file, fall back to the backend text.
const tOr = (key, fallback) => (te(key) ? t(key) : fallback)
const stepTitle = (id) => tOr(`trainingPrefs.steps.${id}.title`, '')
const stepHelp = (id) => tOr(`trainingPrefs.steps.${id}.help`, '')
const fieldLabel = (f) => tOr(`trainingPrefs.fields.${f.key}.label`, f.label_it)
const fieldHelp = (f) => tOr(`trainingPrefs.fields.${f.key}.help`, f.help_it)
const ctaLabel = (cta) => tOr(`trainingPrefs.cta.${cta.action}`, cta.label_it)

const visibleSteps = computed(() => {
  if (!wizardSchema.value) return []
  return wizardSchema.value.steps.filter(s => {
    if (!s.conditional) return true
    return !!wizardSchema.value[s.conditional]
  })
})

const currentStep = computed(() => visibleSteps.value[activeIdx.value] || null)
const isLast = computed(() => activeIdx.value === visibleSteps.value.length - 1)

const canAdvance = computed(() => {
  const step = currentStep.value
  if (!step) return false
  for (const f of step.fields) {
    if (f.optional) continue
    const v = answers.value[f.key]
    if (v === undefined || v === null || v === '') return false
    if (f.type === 'multiselect' && (!Array.isArray(v) || v.length === 0)) return false
  }
  return true
})

const dayShort = (d) => tOr(`calendarWeek.days.${d}`, d)

const optionLabel = (key, opt) => {
  if (key === 'terrain_profile') {
    return tOr(`trainingPrefs.terrain.${opt}`, opt)
  }
  return dayShort(opt) === opt ? opt : dayShort(opt)
}

const loadSchema = async () => {
  if (props.schema) {
    wizardSchema.value = props.schema
  } else {
    // No external schema — fetch onboarding schema from agent endpoint or build minimal
    try {
      const { data } = await api.get('/training-plan/preferences')
      const current = data.preferences || {}
      const inferred = await api.get('/training-plan/terrain-profile/infer')
        .then(r => r.data).catch(() => ({}))
      wizardSchema.value = {
        wizard_id: 'training_preferences_v1',
        inferred,
        current,
        requires_sample_route: !(inferred.max_single_run_elev >= 300),
        steps: defaultSteps(inferred),
      }
    } catch (e) {
      // fallthrough — empty
      wizardSchema.value = { steps: [] }
    }
  }

  // Hydrate answers from current prefs + inferred defaults.
  const cur = wizardSchema.value.current || {}
  const inferred = wizardSchema.value.inferred || {}
  for (const step of wizardSchema.value.steps || []) {
    for (const f of step.fields) {
      if (f.key in cur && cur[f.key] !== null && cur[f.key] !== undefined) {
        answers.value[f.key] = cur[f.key]
      } else if (f.default !== undefined) {
        answers.value[f.key] = f.default
      } else if (f.key === 'terrain_profile' && inferred.profile) {
        answers.value[f.key] = inferred.profile
      } else if (f.type === 'multiselect') {
        answers.value[f.key] = []
      }
    }
  }
}

const defaultSteps = (inferred) => {
  // Minimal fallback when no external schema is provided (e.g. opened from menu)
  const days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
  return [
    { id: 'volume', fields: [
      { key: 'max_weekly_km', type: 'number', min: 10, max: 200 },
      { key: 'max_long_run_km', type: 'number', min: 5, max: 80 },
      { key: 'max_long_run_hours', type: 'number', min: 0.5, max: 12, optional: true },
      { key: 'long_run_day', type: 'select', options: ['Saturday','Sunday','Friday','Monday'] },
    ]},
    { id: 'mountain', fields: [
      { key: 'mountain_access_per_week', type: 'number', min: 0, max: 7, step: 0.5 },
      { key: 'mountain_days', type: 'multiselect', options: days },
      { key: 'max_mountain_elevation_m', type: 'number', min: 0, max: 5000 },
    ]},
    { id: 'terrain', fields: [
      { key: 'terrain_profile', type: 'select', options: ['flat_urban','rolling_hills','mountain'],
        default: inferred.profile || 'rolling_hills' },
    ]},
  ]
}

const loadRoutes = async () => {
  try {
    const { data } = await api.get('/routes')
    routes.value = data.routes || data || []
  } catch {
    routes.value = []
  }
}

watch(() => props.open, (v) => {
  if (v) {
    activeIdx.value = 0
    loadSchema()
    loadRoutes()
  }
})

onMounted(() => {
  if (props.open) {
    loadSchema()
    loadRoutes()
  }
})

const toggleMulti = (key, val) => {
  const cur = answers.value[key] || []
  const idx = cur.indexOf(val)
  if (idx === -1) answers.value[key] = [...cur, val]
  else answers.value[key] = cur.filter(v => v !== val)
}

const next = async () => {
  if (!isLast.value) {
    activeIdx.value += 1
    return
  }
  await save()
}

const prev = () => {
  if (activeIdx.value > 0) activeIdx.value -= 1
}

const save = async () => {
  // Strip undefined / null
  const payload = {}
  for (const [k, v] of Object.entries(answers.value)) {
    if (v !== undefined && v !== null && v !== '') payload[k] = v
  }
  try {
    const { data } = await api.put('/training-plan/preferences', payload)
    emit('saved', data.preferences || payload)
    emit('close')
  } catch (e) {
    console.error('Failed to save preferences', e)
  }
}

const onBackdrop = () => {
  if (!props.blocking) emit('close')
}
const close = () => emit('close')
</script>

<style scoped>
.tpw-backdrop {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.55);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.tpw-modal {
  background: #fff; border-radius: 12px;
  width: min(560px, 92vw); max-height: 90vh;
  display: flex; flex-direction: column;
  box-shadow: 0 18px 48px -8px rgba(15, 23, 42, 0.3);
}
.tpw-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1rem 1.25rem; border-bottom: 1px solid #e2e8f0;
}
.tpw-header h2 { font-size: 1.05rem; font-weight: 700; color: #0f172a; margin: 0; }
.tpw-progress { display: flex; gap: 4px; }
.tpw-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #cbd5e1; transition: background 0.2s;
}
.tpw-dot--on { background: #2563eb; }
.tpw-x {
  background: none; border: none; font-size: 1.5rem; line-height: 1;
  cursor: pointer; color: #64748b;
}
.tpw-body {
  padding: 1.25rem; overflow-y: auto; flex: 1;
}
.tpw-step-title { font-size: 1rem; font-weight: 600; color: #0f172a; margin: 0 0 0.25rem; }
.tpw-step-help { color: #64748b; font-size: 0.85rem; margin: 0 0 1rem; }
.tpw-field { margin-bottom: 1rem; }
.tpw-label { display: block; font-size: 0.875rem; font-weight: 600; color: #334155; margin-bottom: 0.25rem; }
.tpw-req { color: #dc2626; }
.tpw-help { font-size: 0.75rem; color: #64748b; margin: 0 0 0.4rem; }
.tpw-input {
  width: 100%; padding: 0.5rem 0.625rem; border: 1px solid #cbd5e1;
  border-radius: 6px; font-size: 0.9rem; background: #fff;
}
.tpw-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.tpw-chip {
  padding: 4px 10px; border: 1px solid #cbd5e1; background: #f8fafc;
  border-radius: 999px; font-size: 0.8rem; cursor: pointer;
}
.tpw-chip--on { background: #2563eb; color: white; border-color: #2563eb; }
.tpw-route-picker { display: flex; flex-direction: column; gap: 0.5rem; }
.tpw-cta-row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.tpw-cta {
  padding: 0.4rem 0.75rem; border: 1px solid #2563eb; color: #2563eb;
  background: white; border-radius: 6px; font-size: 0.8rem; cursor: pointer;
}
.tpw-cta:hover { background: #eff6ff; }
.tpw-footer {
  padding: 0.875rem 1.25rem; border-top: 1px solid #e2e8f0;
  display: flex; justify-content: space-between; gap: 0.5rem;
}
.tpw-btn {
  padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.875rem;
  font-weight: 600; cursor: pointer; border: none;
  background: #2563eb; color: white;
}
.tpw-btn:disabled { background: #94a3b8; cursor: not-allowed; }
.tpw-btn--ghost { background: white; color: #475569; border: 1px solid #cbd5e1; }
.tpw-loading { color: #64748b; padding: 2rem; text-align: center; }

/* Phones: bottom sheet, thumb-sized controls, 16px inputs (no iOS focus zoom). */
@media (max-width: 640px) {
  .tpw-backdrop { align-items: flex-end; }
  .tpw-modal {
    width: 100%; max-height: 92dvh;
    border-radius: 16px 16px 0 0;
  }
  .tpw-body { padding: 1rem; }
  .tpw-input { font-size: 16px; min-height: 44px; }
  .tpw-chip { min-height: 44px; min-width: 44px; padding: 0 14px; font-size: 0.875rem; }
  .tpw-cta { min-height: 44px; }
  .tpw-x { min-width: 44px; min-height: 44px; }
  .tpw-footer { padding: 0.75rem 1rem calc(0.75rem + env(safe-area-inset-bottom)); }
  .tpw-btn { flex: 1; min-height: 48px; font-size: 1rem; }
}
</style>
