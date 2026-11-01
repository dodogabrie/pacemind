<template>
  <div class="cwl" @click.capture="onClickCapture">
    <div v-if="preview" class="cwl-preview">
      <div class="cwl-preview-cap">
        {{ preview.route.name }} · {{ preview.route.distance_km }}km
        <span v-if="preview.circle"> · {{ preview.circle.name }}</span>
        <button class="cwl-icon-btn" :aria-label="$t('common.buttons.close')" @click="previewDate = null">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>
      <RoutePreviewMap :route-data="preview.route.route_data || []" :circle="preview.circle" class="cwl-preview-map" />
    </div>
    <div v-for="week in weeks" :key="week.start_date" class="cwl-week">
      <div class="cwl-week-header">
        <div class="cwl-week-title">
          <span class="cwl-week-label">{{ formatWeekLabel(week.start_date) }}</span>
          <span class="cwl-week-range">{{ formatWeekRange(week.start_date) }}</span>
        </div>
        <div class="cwl-week-stats">
          <span v-if="week.total_km > 0">{{ week.total_km.toFixed(1) }} km</span>
          <span v-if="week.total_elevation_m > 0">{{ week.total_elevation_m }}m D+</span>
        </div>
      </div>
      <div class="cwl-days">
        <div
          v-for="cell in week.cells"
          :key="cell.date"
          class="cwl-day"
          :draggable="canDrag(cell)"
          :data-date="cell.date"
          @pointerdown="onPointerDown($event, cell)"
          @contextmenu="touching && $event.preventDefault()"
          @dragstart="onDragStart($event, cell)"
          @dragend="dragFrom = dragOver = null"
          @dragover="onDragOver($event, cell)"
          @dragleave="dragOver = null"
          @drop.prevent="onDrop(cell)"
          :class="[
            cell.workout_type ? `cwl-day--${cell.workout_type}` : 'cwl-day--empty',
            { 'cwl-day--today': cell.is_today, 'cwl-day--past': cell.is_past, 'cwl-day--race': cell.race, 'cwl-day--drop': dragOver === cell.date },
          ]"
        >
          <div class="cwl-day-head">
            <span class="cwl-day-name">{{ dayShort(cell.date) }}</span>
            <span class="cwl-day-date">{{ formatDayNum(cell.date) }}</span>
          </div>

          <button
            v-if="cell.race"
            class="cwl-race-chip"
            :class="`cwl-race-chip--${cell.race.race_priority || 'B'}`"
            :title="$t('calendarWeek.race', { name: cell.race.plan_name })"
            @click.stop="$emit('open-race-drawer', cell.race.plan_id)"
          >
            {{ cell.race.race_priority || '•' }} {{ cell.race.plan_name }}
          </button>

          <router-link
            v-for="a in cell.done"
            :key="a.id"
            class="cwl-done-chip"
            :to="{ name: 'ActivityAnalysis', params: { id: a.id } }"
            :title="$t('calendarWeek.open_analysis', { name: a.name })"
            @click.stop
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            {{ a.distance_km }} km<span v-if="a.elevation_m"> · {{ a.elevation_m }} m</span>
          </router-link>

          <template v-if="cell.workout_type">
            <div class="cwl-day-body" @click="$emit('edit-workout', cell)">
              <div class="cwl-day-type" :style="{ background: typeColor(cell.workout_type) }">
                {{ typeLabel(cell.workout_type) }}
              </div>
              <div v-if="cell.title" class="cwl-day-title">{{ cell.title }}</div>
              <div v-if="cell.distance_km || cell.elevation_m || cell.duration_min" class="cwl-day-stats">
                <span v-if="cell.distance_km">{{ cell.distance_km }}km</span>
                <span v-if="cell.elevation_m">{{ cell.elevation_m }}m</span>
                <span v-if="cell.duration_min">{{ formatDuration(cell.duration_min) }}</span>
              </div>
              <div v-if="cell.route_id && routeById[cell.route_id]" class="cwl-day-stats" @click.stop>
                <span>{{ routeById[cell.route_id].name }} · {{ routeById[cell.route_id].distance_km }}km · {{ routeById[cell.route_id].elevation_gain_m }}m D+</span>
                <button class="cwl-icon-btn" :title="$t('routes.download_gpx')" @click="routesStore.downloadGpx(cell.route_id, routeById[cell.route_id].name)">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/></svg>
                </button>
              </div>
              <div v-if="cell.location_name" class="cwl-day-stats" @click.stop>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>
                <select class="cwl-loc" :value="cell.location_id ?? ''" :aria-label="$t('locations.for_workout')" @change="changeLocation(cell, $event.target.value)">
                  <option value="">{{ $t('locations.by_weekday') }}</option>
                  <option v-for="l in routesStore.locations" :key="l.id" :value="l.id">{{ l.name }}</option>
                </select>
                <button v-if="cell.route_id && routeById[cell.route_id]" class="cwl-icon-btn" :title="$t('locations.show_map')" @click="previewDate = previewDate === cell.date ? null : cell.date">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/></svg>
                </button>
              </div>
              <router-link
                v-else-if="cell.route_match_quality === 'unmatched'"
                :to="{ name: 'Routes' }"
                class="cwl-day-stats"
                @click.stop
              >{{ $t('calendarWeek.no_route') }}</router-link>
              <div v-if="cell.plan_name && cell.race_id" class="cwl-day-plan-tag">
                {{ cell.plan_name }}
              </div>
            </div>
            <div class="cwl-day-actions" @click.stop>
              <button class="cwl-icon-btn" :title="$t('calendarWeek.edit')" @click="$emit('edit-workout', cell)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
              </button>
              <button class="cwl-icon-btn" :title="$t('calendarWeek.ask_coach')" @click="$emit('ask-coach', cell)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
              </button>
            </div>
          </template>

          <button
            v-else-if="editable"
            class="cwl-add-btn"
            :title="$t('calendarWeek.add', { date: cell.date })"
            @click="$emit('add-workout', cell.date)"
          >
            +
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoutesStore } from '../stores/routes'
import { useTrainingPlanStore } from '../stores/trainingPlan'
import RoutePreviewMap from './RoutePreviewMap.vue'

const { t, te, locale } = useI18n()
const routesStore = useRoutesStore()
const planStore = useTrainingPlanStore()
const routeById = computed(() => Object.fromEntries(routesStore.routes.map(r => [r.id, r])))
onMounted(() => {
  routesStore.fetchLocations()
  if (props.days.some(d => d.route_id && !routeById.value[d.route_id])) routesStore.fetchRoutes()
})

const props = defineProps({
  days: { type: Array, default: () => [] },
  races: { type: Array, default: () => [] },
  activities: { type: Array, default: () => [] },
  fromDate: { type: String, required: true },
  toDate: { type: String, required: true },
  editable: { type: Boolean, default: true },
})

const emit = defineEmits(['add-workout', 'edit-workout', 'ask-coach', 'open-race-drawer', 'location-changed', 'moved'])

const previewDate = ref(null)
const locationById = computed(() => Object.fromEntries(routesStore.locations.map(l => [l.id, l])))
const preview = computed(() => {
  const day = daysByDate.value.get(previewDate.value)
  const route = day && routeById.value[day.route_id]
  if (!route) return null
  const loc = locationById.value[day.location_id ?? day.resolved_location_id]
  return { route, circle: loc ? { lat: loc.lat, lon: loc.lon, radius_km: loc.radius_km, name: loc.name } : null }
})

async function changeLocation(cell, value) {
  await routesStore.setDayLocation(cell.plan_id, cell.week_number, cell.day, value === '' ? null : Number(value))
  emit('location-changed')
}

// Mouse: native HTML5 drag and drop. Touch: long-press + pointer events
// (HTML5 DnD does not fire on phones); both end in drop().
const dragFrom = ref(null)
const dragOver = ref(null)
const canDrag = (cell) => props.editable && !!cell.workout_type && !cell.is_past
const canDrop = (cell) => !!dragFrom.value && !cell.is_past && cell.date !== dragFrom.value
function onDragOver(e, cell) {
  if (!canDrop(cell)) return
  e.preventDefault()
  dragOver.value = cell.date
}
function onDrop(cell) {
  const from = dragFrom.value
  const ok = canDrop(cell)
  dragFrom.value = dragOver.value = null
  if (ok) drop(from, cell.date)
}
async function drop(from, to) {
  try {
    await planStore.moveCalendarWorkout(from, to)
  } catch {
    window.alert(planStore.error || t('calendarWeek.move_failed'))
  }
  emit('moved')
}

const LONG_PRESS_MS = 350
const MOVE_TOL = 8
const EDGE = 70
const touching = ref(false)
let press = null // { cell, el, id, x0, y0, x, y, timer, active, ghost, raf, dx, dy }
let justDragged = false
const allCells = () => weeks.value.flatMap(w => w.cells)
const noScroll = (e) => { if (press?.active && e.cancelable) e.preventDefault() }

function onDragStart(e, cell) {
  // Android fires native dragstart on long-press: the pointer path owns touch.
  if (touching.value) return e.preventDefault()
  dragFrom.value = cell.date
}
function onPointerDown(e, cell) {
  touching.value = e.pointerType === 'touch'
  if (!touching.value || !canDrag(cell) || press || e.target.closest('button, a, select')) return
  const el = e.currentTarget
  press = { cell, el, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, active: false }
  press.timer = setTimeout(startTouchDrag, LONG_PRESS_MS)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerEnd)
  window.addEventListener('pointercancel', onPointerEnd)
  window.addEventListener('touchmove', noScroll, { passive: false })
}
function startTouchDrag() {
  const r = press.el.getBoundingClientRect()
  press.active = true
  press.dx = press.x0 - r.left
  press.dy = press.y0 - r.top
  const g = press.el.cloneNode(true)
  g.removeAttribute('draggable')
  Object.assign(g.style, {
    position: 'fixed', left: '0', top: '0', width: `${r.width}px`, zIndex: 9999,
    pointerEvents: 'none', opacity: '.9', boxShadow: '0 8px 24px rgba(15,23,42,.3)',
  })
  document.body.appendChild(g)
  press.ghost = g
  dragFrom.value = press.cell.date
  navigator.vibrate?.(30)
  moveGhost()
  press.raf = requestAnimationFrame(tick)
}
function moveGhost() {
  press.ghost.style.transform = `translate(${press.x - press.dx}px, ${press.y - press.dy}px)`
  const day = document.elementFromPoint(press.x, press.y)?.closest('[data-date]')
  const cell = day && allCells().find(c => c.date === day.dataset.date)
  dragOver.value = cell && canDrop(cell) ? cell.date : null
}
function tick() {
  if (!press?.active) return
  const h = window.innerHeight
  const v = press.y < EDGE ? -(EDGE - press.y) : press.y > h - EDGE ? press.y - (h - EDGE) : 0
  if (v) { window.scrollBy(0, v / 4); moveGhost() }
  press.raf = requestAnimationFrame(tick)
}
function onPointerMove(e) {
  if (!press) return
  press.x = e.clientX
  press.y = e.clientY
  if (press.active) return moveGhost()
  // Moved before the long-press fired: it is a normal scroll.
  if (Math.hypot(press.x - press.x0, press.y - press.y0) > MOVE_TOL) endPress(false)
}
function onPointerEnd(e) {
  endPress(e.type === 'pointerup')
}
function endPress(commit) {
  if (!press) return
  const { active, ghost, timer, raf } = press
  const to = dragOver.value
  const from = dragFrom.value
  clearTimeout(timer)
  cancelAnimationFrame(raf)
  ghost?.remove()
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerEnd)
  window.removeEventListener('pointercancel', onPointerEnd)
  window.removeEventListener('touchmove', noScroll)
  press = null
  if (!active) return
  dragFrom.value = dragOver.value = null
  justDragged = true // swallow the click the release may generate
  setTimeout(() => { justDragged = false }, 400)
  if (commit && to) drop(from, to)
}
function onClickCapture(e) {
  if (justDragged) { e.stopPropagation(); e.preventDefault() }
}
onBeforeUnmount(() => endPress(false))

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const todayIso = new Date().toISOString().slice(0, 10)

const daysByDate = computed(() => {
  // First day-entry per date wins; race plans take precedence over Personal in
  // the unlikely case of conflicting entries (the API already orders by date,
  // so just keep the first non-Personal entry per date if present).
  const map = new Map()
  for (const d of props.days) {
    const existing = map.get(d.date)
    if (!existing) {
      map.set(d.date, d)
    } else if (d.race_id && !existing.race_id) {
      map.set(d.date, d)
    }
  }
  return map
})

const racesByDate = computed(() => {
  const map = new Map()
  for (const r of props.races) {
    map.set(r.race_date, r)
  }
  return map
})

const activitiesByDate = computed(() => {
  const map = new Map()
  for (const a of props.activities) {
    if (!map.has(a.date)) map.set(a.date, [])
    map.get(a.date).push(a)
  }
  return map
})

const weeks = computed(() => {
  const out = []
  if (!props.fromDate || !props.toDate) return out
  const startDate = mondayOf(parseIso(props.fromDate))
  const endDate = parseIso(props.toDate)
  const cursor = new Date(startDate)
  while (cursor <= endDate) {
    const weekStart = new Date(cursor)
    const cells = []
    let totalKm = 0
    let totalElev = 0
    for (let i = 0; i < 7; i++) {
      const d = new Date(weekStart)
      d.setDate(d.getDate() + i)
      const iso = isoDate(d)
      const day = daysByDate.value.get(iso) || {}
      const race = racesByDate.value.get(iso) || null
      const cell = {
        date: iso,
        day: DAY_NAMES[i],
        is_today: iso === todayIso,
        is_past: iso < todayIso,
        race,
        ...day,
        location_name: day.workout_type && !day.treadmill && (day.route_id || day.route_match_quality === 'unmatched')
          ? locationById.value[day.location_id ?? day.resolved_location_id]?.name ?? t('locations.base') : null,
        done: activitiesByDate.value.get(iso) || [],
      }
      if (typeof cell.distance_km === 'number') totalKm += cell.distance_km
      if (typeof cell.elevation_m === 'number') totalElev += cell.elevation_m
      cells.push(cell)
    }
    out.push({
      start_date: isoDate(weekStart),
      total_km: totalKm,
      total_elevation_m: totalElev,
      cells,
    })
    cursor.setDate(cursor.getDate() + 7)
  }
  return out
})

function parseIso(s) {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function isoDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
function mondayOf(d) {
  const out = new Date(d)
  const day = (out.getDay() + 6) % 7  // 0=Mon, 6=Sun
  out.setDate(out.getDate() - day)
  return out
}
function formatWeekLabel(startIso) {
  const d = parseIso(startIso)
  // ISO week number
  const target = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNum = (target.getUTCDay() + 6) % 7
  target.setUTCDate(target.getUTCDate() - dayNum + 3)
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4))
  const week = 1 + Math.round(((target - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7)
  return t('calendarWeek.week', { n: week })
}
function formatWeekRange(startIso) {
  const start = parseIso(startIso)
  const end = new Date(start)
  end.setDate(end.getDate() + 6)
  const fmt = (d) => d.toLocaleDateString(locale.value, { month: 'short', day: 'numeric' })
  return `${fmt(start)} – ${fmt(end)}`
}
function formatDayNum(iso) {
  return iso.slice(8)
}
function formatDuration(min) {
  if (!min) return ''
  if (min >= 60) {
    const h = Math.floor(min / 60); const r = Math.round(min - h * 60)
    return r ? `${h}h${r}m` : `${h}h`
  }
  return `${Math.round(min)}min`
}
const TYPE_COLORS = {
  easy: '#86efac', tempo: '#fde047', intervals: '#fb923c', long_run: '#a78bfa', hill_repeats: '#f87171',
  rest: '#cbd5e1', cross_train: '#7dd3fc', recovery: '#bef264', vert_session: '#fda4af',
  back_to_back: '#c4b5fd', race_simulation: '#fbbf24', strength: '#94a3b8',
}
function typeLabel(type) {
  const key = `calendarWeek.types.${type}`
  return te(key) ? t(key) : type
}
function dayShort(iso) {
  return t(`calendarWeek.days.${DAY_NAMES[(parseIso(iso).getDay() + 6) % 7]}`)
}
function typeColor(type) { return TYPE_COLORS[type] || '#cbd5e1' }
</script>

<style scoped>
.cwl { display: flex; flex-direction: column; gap: 1rem; }
.cwl-week { background: white; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
.cwl-week-header {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: .5rem .75rem; background: #f8fafc; border-bottom: 1px solid #e2e8f0;
}
.cwl-week-title { display: flex; gap: .5rem; align-items: baseline; }
.cwl-week-label { font-weight: 600; font-size: .85rem; color: #0f172a; }
.cwl-week-range { font-size: .75rem; color: #64748b; }
.cwl-week-stats { display: flex; gap: .5rem; font-size: .75rem; color: #475569; }
.cwl-days {
  display: grid; grid-template-columns: repeat(7, 1fr);
  gap: 4px; padding: 4px;
}
.cwl-day {
  position: relative;
  min-height: 92px;
  padding: 6px;
  border-radius: 6px;
  background: #f8fafc;
  display: flex; flex-direction: column;
  font-size: .75rem;
}
.cwl-day--empty { background: white; border: 1px dashed #e2e8f0; }
.cwl-day--today { box-shadow: 0 0 0 2px #6366f1 inset; }
.cwl-day--past { opacity: .85; }
.cwl-day--drop { box-shadow: 0 0 0 2px #6366f1; background: #eef2ff; }
.cwl-day[draggable="true"]:focus-visible { outline: 2px solid #6366f1; }
@media (pointer: coarse) {
  .cwl-day[draggable="true"] { -webkit-touch-callout: none; user-select: none; }
}
.cwl-day--race { background: #fef3c7; }
.cwl-day-head {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: .65rem; color: #64748b; text-transform: uppercase; letter-spacing: .03em;
}
.cwl-day-name { font-weight: 600; }
.cwl-day-date { font-weight: 500; }
.cwl-day-body { cursor: pointer; flex: 1; display: flex; flex-direction: column; gap: 3px; margin-top: 4px; }
.cwl-day-type {
  align-self: flex-start;
  padding: 1px 6px; border-radius: 3px;
  font-size: .65rem; font-weight: 600;
  color: #1e293b;
}
.cwl-day-title { font-size: .7rem; color: #334155; line-height: 1.2; }
.cwl-day-stats { display: flex; gap: 4px; flex-wrap: wrap; font-size: .65rem; color: #64748b; }
.cwl-loc { max-width: 90px; font-size: .65rem; border: none; background: transparent; color: #64748b; cursor: pointer; }
.cwl-preview { background: white; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
.cwl-preview-cap { display: flex; justify-content: space-between; align-items: center; padding: .4rem .75rem; font-size: .8rem; color: #334155; background: #f8fafc; }
.cwl-preview-map { height: 260px; }
.cwl-day-plan-tag { font-size: .6rem; color: #94a3b8; margin-top: auto; }
.cwl-day-actions { display: flex; gap: 2px; margin-top: 4px; }
.cwl-icon-btn {
  background: white; border: 1px solid #e2e8f0; border-radius: 3px;
  padding: 2px 4px; cursor: pointer; color: #64748b;
}
.cwl-icon-btn:hover { color: #6366f1; border-color: #6366f1; }
.cwl-add-btn {
  flex: 1;
  margin-top: auto;
  padding: 4px;
  background: white;
  border: 1px dashed #cbd5e1;
  border-radius: 4px;
  font-size: 1rem;
  color: #94a3b8;
  cursor: pointer;
}
.cwl-add-btn:hover { color: #6366f1; border-color: #6366f1; background: #eef2ff; }
.cwl-race-chip {
  align-self: flex-start;
  margin-top: 4px;
  padding: 1px 6px;
  background: #f59e0b;
  color: white;
  border: none; border-radius: 3px;
  font-size: .6rem; font-weight: 600;
  cursor: pointer;
}
.cwl-race-chip--A { background: #dc2626; }
.cwl-race-chip--B { background: #f59e0b; }
.cwl-race-chip--C { background: #eab308; }
/* Phones: one compact row per day (day | workout | actions) instead of a
   stacked card per day, so a week fits in about one screen. */
@media (max-width: 720px) {
  .cwl-days { grid-template-columns: 1fr; }
  .cwl-day {
    min-height: 48px; flex-direction: row; flex-wrap: wrap; align-items: center;
    gap: 4px 10px; padding: 4px 6px 4px 10px;
  }
  .cwl-day-head { flex-direction: column; align-items: flex-start; width: 34px; flex: none; }
  .cwl-day-date { font-size: .8rem; color: #0f172a; }
  .cwl-day-body { flex: 1; min-width: 0; margin-top: 0; padding: 4px 0; }
  .cwl-day-title { font-size: .8rem; }
  .cwl-day-stats { font-size: .7rem; }
  .cwl-day-actions { margin-top: 0; gap: 4px; }
  .cwl-icon-btn {
    width: 40px; height: 40px; display: inline-flex; align-items: center; justify-content: center;
    border-radius: 8px;
  }
  .cwl-icon-btn svg { width: 16px; height: 16px; }
  .cwl-add-btn {
    margin-top: 0; align-self: stretch; min-height: 40px;
    border-color: transparent; text-align: right; padding: 0 14px; font-size: 1.25rem;
  }
  .cwl-race-chip { margin-top: 0; padding: 4px 8px; font-size: .7rem; min-height: 28px; }
}

.cwl-done-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 8px;
  margin-bottom: 4px;
  border-radius: 999px;
  border: 1px solid #047857;
  color: #047857;
  background: #ecfdf5;
  text-decoration: none;
  width: fit-content;
}
.cwl-done-chip:hover { background: #d1fae5; }
</style>
