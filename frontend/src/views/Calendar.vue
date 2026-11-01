<template>
  <div class="cal">
    <AuthGate
      v-if="authStore.authChecked && !authStore.isAuthenticated"
      :title="$t('auth.calendar.title')"
      :text="$t('auth.calendar.text')"
    />

    <div v-else-if="!authStore.authChecked" class="cal-booting">
      {{ $t('common.loading') }}
    </div>

    <template v-else>
    <div class="cal-layout">
      <div class="cal-main">
        <header class="cal-header">
          <div>
            <h1 class="cal-title">{{ $t('calendar.title') }}</h1>
            <p class="cal-subtitle">{{ $t('calendar.subtitle') }}</p>
          </div>
          <div class="cal-nav">
            <button class="cal-nav-btn" @click="shiftWindow(-28)" :title="$t('calendar.prev_weeks')">‹</button>
            <button class="cal-nav-btn" @click="goToday" :title="$t('calendar.today')">{{ $t('calendar.today') }}</button>
            <button class="cal-nav-btn" @click="shiftWindow(28)" :title="$t('calendar.next_weeks')">›</button>
          </div>
        </header>

        <CalendarWeekList
          :days="planStore.calendarDays"
          :races="planStore.calendarRaces"
          :activities="planStore.calendarActivities"
          :from-date="windowFrom"
          :to-date="windowTo"
          :editable="true"
          @add-workout="onAddWorkout"
          @edit-workout="onEditWorkout"
          @ask-coach="onAskCoach"
          @open-race-drawer="onOpenRaceDrawer"
          @location-changed="reload"
          @moved="reload"
        />
      </div>

      <div class="cal-side" v-show="!chatCollapsed">
        <button
          class="cal-chat-collapse"
          @click="setChatCollapsed(true)"
          :title="$t('calendar.collapse_coach')"
        >›</button>
        <AgentChat
          ref="agentChatRef"
          :embedded="true"
          context-type="training-plan"
          :plan-id="agentPlanId"
          :welcome-text="welcomeText"
          @plan-saved="onPlanSaved"
          @week-generated="onPlanRefreshNeeded"
          @plan-adjusted="onPlanRefreshNeeded"
        />
      </div>
    </div>

    <button
      v-if="chatCollapsed"
      class="cal-chat-reopen"
      @click="setChatCollapsed(false)"
      :title="$t('calendar.open_coach')"
    >
      <span class="cal-chat-reopen-dot">AI</span>
      {{ $t('agentChat.title') }}
    </button>

    <Teleport to="body">
      <WorkoutTextEditor
        v-if="editorOpen && editorCtx.day"
        :plan-id="editorCtx.planId || 0"
        :week-number="editorCtx.weekNumber || 0"
        :day-name="editorCtx.dayName || ''"
        :day="editorCtx.day"
        :calendar-mode="editorCtx.calendarMode"
        :calendar-date="editorCtx.calendarDate"
        @close="editorOpen = false"
        @saved="onEditorSaved"
      />
    </Teleport>

    <Teleport to="body">
      <RaceDrawer
        v-if="raceDrawerPlanId"
        :plan-id="raceDrawerPlanId"
        @close="raceDrawerPlanId = null"
      />
    </Teleport>

    <TrainingPreferencesWizard
      :open="wizardOpen"
      :blocking="wizardBlocking"
      :schema="wizardSchema"
      @close="onWizardClose"
      @saved="onWizardSaved"
      @cta="onWizardCta"
    />
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import AgentChat from '../components/AgentChat.vue'
import AuthGate from '../components/AuthGate.vue'
import CalendarWeekList from '../components/CalendarWeekList.vue'
import WorkoutTextEditor from '../components/WorkoutTextEditor.vue'
import RaceDrawer from '../components/RaceDrawer.vue'
import TrainingPreferencesWizard from '../components/TrainingPreferencesWizard.vue'
import { useTrainingPlanStore } from '../stores/trainingPlan'
import { useAuthStore } from '../stores/auth'
import api from '../services/api'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

const props = defineProps({
  openRaceDrawer: { type: [Number, String], default: null },
})

const planStore = useTrainingPlanStore()
const authStore = useAuthStore()
const route = useRoute()
const agentChatRef = ref(null)

const CHAT_COLLAPSED_KEY = 'cal.chatCollapsed'
const chatCollapsed = ref(false)
// Below 1100px the coach panel is a full-screen sheet (see CSS), so it starts
// closed and opens from the floating button instead of sitting under 14 weeks.
const isNarrow = typeof window !== 'undefined' && window.matchMedia?.('(max-width: 1100px)').matches
try { chatCollapsed.value = isNarrow || localStorage.getItem(CHAT_COLLAPSED_KEY) === '1' } catch (_) {}
function setChatCollapsed(v) {
  chatCollapsed.value = !!v
  if (isNarrow) return // sheet open/close on phones isn't a layout preference
  try { localStorage.setItem(CHAT_COLLAPSED_KEY, v ? '1' : '0') } catch (_) {}
}

// Calendar window: rolling, default = today - 14d .. today + 84d
const windowFrom = ref('')
const windowTo = ref('')
function setWindow(fromIso, toIso) {
  windowFrom.value = fromIso
  windowTo.value = toIso
}
function isoOffset(days) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
function defaultWindow() {
  setWindow(isoOffset(-14), isoOffset(84))
}
function shiftWindow(days) {
  const from = new Date(windowFrom.value); from.setDate(from.getDate() + days)
  const to = new Date(windowTo.value); to.setDate(to.getDate() + days)
  setWindow(from.toISOString().slice(0, 10), to.toISOString().slice(0, 10))
  reload()
}
function goToday() {
  defaultWindow()
  reload()
}

async function reload() {
  await planStore.fetchCalendar(windowFrom.value, windowTo.value)
}

// Editor state
const editorOpen = ref(false)
const editorCtx = ref({})

function onAddWorkout(date) {
  // Manual add — calendar mode (no planId yet, backend resolves on save)
  editorCtx.value = {
    calendarMode: true,
    calendarDate: date,
    day: { day: dayNameFor(date), date, title: '' },
  }
  editorOpen.value = true
}

function onEditWorkout(cell) {
  // Existing workout — use the plan-day PATCH path
  editorCtx.value = {
    planId: cell.plan_id,
    weekNumber: cell.week_number,
    dayName: cell.day,
    day: cell,
    calendarMode: false,
  }
  editorOpen.value = true
}

async function onEditorSaved() {
  editorOpen.value = false
  await reload()
}

// Agent context: pick the most relevant active race plan if any, else null
const agentPlanId = computed(() => {
  const races = planStore.calendarRaces || []
  if (!races.length) return null
  return races[0].plan_id
})

const welcomeText = computed(() => t('calendar.welcome'))

function onAskCoach(cell) {
  setChatCollapsed(false)
  const dateStr = cell.date ? ` (${cell.date})` : ''
  const titleStr = cell.title ? ` — ${cell.title}` : ''
  const distStr = cell.distance_km ? ` ${cell.distance_km}km` : ''
  const elevStr = cell.elevation_m ? ` / ${cell.elevation_m}m D+` : ''
  const day = cell.date ? dayNameFor(cell.date) : cell.day
  const prompt = t('calendar.ask_about', { day: `${day}${dateStr}${titleStr}${distStr}${elevStr}` })
  requestAnimationFrame(() => {
    agentChatRef.value?.prefillInput?.(prompt)
  })
}

async function onPlanSaved() { await onPlanRefreshNeeded() }
async function onPlanRefreshNeeded() {
  await planStore.fetchPlans()
  await reload()
}

// Training-preferences wizard bootstrap (moved from the old TrainingPlan view).
const wizardOpen = ref(false)
const wizardBlocking = ref(false)
const wizardSchema = ref(null)

function openWizard(blocking) {
  wizardBlocking.value = !!blocking
  wizardSchema.value = null
  wizardOpen.value = true
}

function onWizardClose() {
  wizardOpen.value = false
  wizardBlocking.value = false
  wizardSchema.value = null
}

function onWizardSaved() {
  wizardOpen.value = false
  wizardBlocking.value = false
}

function onWizardCta(cta) {
  if (!agentChatRef.value?.sendMessage) return
  setChatCollapsed(false)
  if (cta?.action === 'generate') {
    agentChatRef.value.sendMessage(t('calendar.cta_generate'))
  } else if (cta?.action === 'upload') {
    agentChatRef.value.sendMessage(t('calendar.cta_upload'))
  }
}

async function bootstrapPreferencesWizard() {
  try {
    const { data } = await api.get('/training-plan/preferences')
    const p = data.preferences || {}
    if (!p.max_weekly_km || !p.terrain_profile) {
      openWizard(true)
    }
  } catch {
    // Auth or network — silently skip; the user can open it from elsewhere.
  }
}

// Race drawer state
const raceDrawerPlanId = ref(null)
function onOpenRaceDrawer(planId) {
  raceDrawerPlanId.value = planId
}

watch(() => props.openRaceDrawer, (v) => {
  if (v) raceDrawerPlanId.value = Number(v)
}, { immediate: true })

onMounted(async () => {
  defaultWindow()
  // Views mount before App.vue's onMounted, so resolve auth first — otherwise
  // these calls 401 for a logged-out visitor and the gate flashes for a
  // logged-in one.
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  await Promise.all([planStore.fetchPlans(), reload()])
  // Deep link: /race/:planId mounts Calendar with this prop set
  if (props.openRaceDrawer) raceDrawerPlanId.value = Number(props.openRaceDrawer)
  // Or via route param fallback
  const pid = route.params?.planId
  if (pid && !raceDrawerPlanId.value) raceDrawerPlanId.value = Number(pid)
  // Handoff from the post-workout page: ?ask=<question> opens the coach on it.
  if (route.query.ask) {
    setChatCollapsed(false)
    const q = String(route.query.ask)
    requestAnimationFrame(() => agentChatRef.value?.sendMessage?.(q))
    return
  }
  // Required preferences gate (only on first calendar visit if missing).
  bootstrapPreferencesWizard()
})

function dayNameFor(iso) {
  return new Date(iso + 'T00:00:00').toLocaleDateString(locale.value, { weekday: 'long' })
}
</script>

<style scoped>
.cal { padding: 1rem; min-height: calc(100vh - 64px); }
.cal-booting {
  min-height: 60vh; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; font-size: .875rem;
}
.cal-layout {
  display: grid; grid-template-columns: 1fr 380px; gap: 1rem;
  align-items: start;
}
@media (max-width: 1100px) {
  .cal-layout { grid-template-columns: 1fr; }
}
.cal-main { min-width: 0; }
.cal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.cal-title { font-size: 1.25rem; font-weight: 600; color: #0f172a; margin: 0; }
.cal-subtitle { font-size: .85rem; color: #64748b; margin: 2px 0 0; }
.cal-nav { display: flex; gap: 4px; }
.cal-nav-btn {
  padding: 4px 12px; background: white; border: 1px solid #cbd5e1;
  border-radius: 4px; cursor: pointer; font-size: .85rem;
}
.cal-nav-btn:hover { background: #f1f5f9; }
.cal-side { position: sticky; top: 1rem; height: calc(100vh - 96px); display: flex; flex-direction: column; position: relative; }
.cal-chat-collapse { position: absolute; right: -8px; top: 8px; z-index: 5; background: white; border: 1px solid #cbd5e1; border-radius: 50%; width: 22px; height: 22px; cursor: pointer; }
.cal-chat-reopen {
  position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 50;
  background: #6366f1; color: white; border: none; padding: .6rem 1rem;
  border-radius: 999px; cursor: pointer; display: flex; gap: .5rem; align-items: center;
}
.cal-chat-reopen-dot { background: white; color: #6366f1; padding: 1px 5px; border-radius: 3px; font-weight: 700; font-size: .7rem; }

@media (max-width: 1100px) {
  /* Coach panel = full-screen sheet over the calendar, sized to the visual
     viewport (--vvh/--vvt set by AgentChat) so the input clears the keyboard. */
  .cal-side {
    position: fixed; left: 0; right: 0; top: var(--vvt, 0px); z-index: 70;
    height: var(--vvh, 100dvh); background: white;
    padding: env(safe-area-inset-top) 0 0;
  }
  .cal-side :deep(.agent-panel--embedded) { border-radius: 0; border: none; box-shadow: none; }
  .cal-side :deep(.agent-header) { padding-right: 3.25rem; }
  .cal-chat-collapse {
    right: 6px; top: calc(env(safe-area-inset-top) + 4px); z-index: 1001; /* AgentChat root is a z:1000 flex item */
    width: 40px; height: 40px; font-size: 1.25rem; line-height: 1;
    transform: rotate(90deg);
  }
  .cal-chat-reopen {
    bottom: calc(1rem + env(safe-area-inset-bottom)); right: 1rem;
    min-height: 48px; padding: .75rem 1.1rem;
    box-shadow: 0 6px 18px rgba(99, 102, 241, .35);
  }
}
@media (max-width: 640px) {
  .cal { padding: .5rem 0 5rem; }
  .cal-header { flex-wrap: wrap; gap: .75rem; }
  .cal-nav { width: 100%; }
  .cal-nav-btn { flex: 1; min-height: 44px; font-size: 1rem; border-radius: 8px; }
}
</style>
