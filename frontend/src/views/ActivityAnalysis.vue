<template>
  <div class="aa layout">
    <AuthGate
      v-if="authStore.authChecked && !authStore.isAuthenticated"
      :title="$t('auth.calendar.title')"
      :text="$t('auth.calendar.text')"
    />
    <p v-else-if="loading" class="aa-note">{{ t('activityAnalysis.loading') }}</p>
    <p v-else-if="error" class="aa-note">{{ error }}</p>

    <template v-else-if="data">
      <router-link :to="{ name: 'Calendar' }" class="aa-back">&lsaquo; {{ t('activityAnalysis.back') }}</router-link>

      <header class="aa-top">
        <div>
          <div class="aa-eyebrow">{{ longDate }}<span v-if="data.sport_type"> - {{ data.sport_type.replace('_', ' ') }}</span></div>
          <h1>{{ d.name }}</h1>
        </div>
        <div v-if="plan.matched" class="aa-pills">
          <span class="aa-pill">{{ t('activityAnalysis.plan.plan_tag', { plan: planName, week: plan.week, day: dayLabel(plan.day) }) }}</span>
          <span class="aa-pill" :class="verdict.ok ? 'ok' : 'warn'">{{ verdict.ok ? t('activityAnalysis.plan.on_plan') : t('activityAnalysis.plan.off_plan') }}</span>
        </div>
      </header>

      <section class="aa-card aa-stats">
        <div><div class="aa-eyebrow">{{ t('activityAnalysis.stats.distance') }}</div><div class="aa-v">{{ num(d.distance_km, 2) }} km</div></div>
        <div><div class="aa-eyebrow">{{ t('activityAnalysis.stats.moving') }}</div><div class="aa-v">{{ hms(d.moving_time_s) }}</div></div>
        <div><div class="aa-eyebrow">{{ t('activityAnalysis.stats.elevation') }}</div><div class="aa-v">+{{ d.elevation_gain_m }} m</div></div>
        <div>
          <div class="aa-eyebrow">{{ t('activityAnalysis.stats.pace') }}</div>
          <div class="aa-v">{{ pace(avgPace) }}</div>
          <div v-if="avgGap" class="aa-s">{{ t('activityAnalysis.stats.gap', { v: pace(avgGap) }) }}</div>
        </div>
        <div v-if="hrAvg">
          <div class="aa-eyebrow">{{ t('activityAnalysis.stats.hr') }}</div>
          <div class="aa-v">{{ hrAvg }}</div>
          <div class="aa-s">{{ t('activityAnalysis.stats.hr_max', { v: hrMax }) }}</div>
        </div>
      </section>

      <p v-if="d.error" class="aa-note">{{ t('activityAnalysis.no_streams') }}</p>

      <div class="aa-grid2">
        <section class="aa-card">
          <h2>{{ t('activityAnalysis.plan.title') }}</h2>
          <template v-if="plan.matched">
            <div class="aa-eyebrow">{{ plan.planned.title || plan.planned.workout_type }}</div>
            <div class="aa-cmp">
              <span></span><span class="h">{{ t('activityAnalysis.plan.planned') }}</span><span class="h">{{ t('activityAnalysis.plan.done') }}</span><span></span>
              <template v-for="r in cmpRows" :key="r.label">
                <span>{{ r.label }}</span><span class="m">{{ r.planned }}</span><span class="m">{{ r.done }}</span>
                <span class="m" :class="r.cls">{{ r.pct }}</span>
              </template>
            </div>
            <div class="aa-verdict" :class="{ ok: verdict.ok }">{{ verdict.text }}</div>
            <p v-if="plan.treadmill" class="aa-note">{{ t('activityAnalysis.plan.treadmill') }}</p>
            <p v-if="plan.planned.notes" class="aa-note">{{ plan.planned.notes }}</p>
          </template>
          <p v-else class="aa-note">{{ t('activityAnalysis.plan.none') }}</p>
        </section>

        <section class="aa-card">
          <h2>{{ t('activityAnalysis.zones.title') }}</h2>
          <template v-if="zones.length">
            <div class="aa-zbar"><div v-for="z in zones" :key="z.k" :style="{ width: z.pct + '%', background: z.color }" :title="`${z.k} ${z.pct}%`"></div></div>
            <div v-for="z in zones" :key="z.k" class="aa-zrow">
              <b>{{ z.k }}</b>
              <span><span class="aa-muted">{{ z.name }}</span><div class="aa-zb" :style="{ width: Math.min(100, z.pct * 2) + '%', background: z.color }"></div></span>
              <span class="m r">{{ mmss(z.seconds) }}</span><span class="m r">{{ num(z.pct, 1) }}%</span>
            </div>
            <p v-if="d.hr_drift" class="aa-note">
              {{ t('activityAnalysis.zones.drift', { a: d.hr_drift.hr_first_half, b: d.hr_drift.hr_second_half }) }}
              {{ hilly ? t('activityAnalysis.zones.drift_hilly') : t('activityAnalysis.zones.decoupling', { v: num(d.hr_drift.decoupling_pct, 1) }) }}
            </p>
          </template>
          <p v-else class="aa-note">{{ t('activityAnalysis.zones.none') }}</p>
        </section>
      </div>

      <section v-if="profile.length" class="aa-card">
        <div class="aa-top">
          <h2>{{ t('activityAnalysis.profile.title') }}</h2>
          <div class="aa-legend">
            <span v-if="d.altitude_available"><i class="alt"></i>{{ t('activityAnalysis.profile.alt') }}</span>
            <span v-if="hasHr"><i class="hr"></i>{{ t('activityAnalysis.profile.hr') }}</span>
            <span v-if="climbs.length"><i class="seg"></i>{{ t('activityAnalysis.profile.seg') }}</span>
          </div>
        </div>
        <p v-if="!d.altitude_available" class="aa-note">{{ t('activityAnalysis.profile.treadmill') }}</p>
        <div class="aa-scroll">
          <svg :viewBox="`0 0 ${W} ${H}`" class="aa-prof" role="img" :aria-label="t('activityAnalysis.profile.title')">
            <rect v-for="(c, i) in climbs" :key="'c' + i" :x="x(c.start_km * 1000)" :y="T" :width="x(c.start_km * 1000 + c.length_m) - x(c.start_km * 1000)" :height="H - T - B" :fill="c.type === 'climb' ? '#b45309' : '#0284c7'" opacity=".1" />
            <template v-if="d.altitude_available">
              <g v-for="a in altTicks" :key="'a' + a">
                <line :x1="L" :x2="W - R" :y1="ya(a)" :y2="ya(a)" stroke="#e2e8f0" />
                <text :x="L - 6" :y="ya(a) + 3" text-anchor="end">{{ a }}</text>
              </g>
              <path :d="altPath" fill="#cbd5e1" opacity=".6" />
            </template>
            <template v-if="hasHr">
              <g v-if="hrTarget">
                <rect :x="L" :y="yh(hrTarget[1])" :width="W - L - R" :height="yh(hrTarget[0]) - yh(hrTarget[1])" fill="#047857" opacity=".08" />
                <text :x="L + 6" :y="yh(hrTarget[1]) + 12" class="t-forest">{{ t('activityAnalysis.profile.target', { lo: hrTarget[0], hi: hrTarget[1] }) }}</text>
              </g>
              <text v-for="h in hrTicks" :key="'h' + h" :x="W - R + 6" :y="yh(h) + 3" class="t-hr">{{ h }}</text>
              <path :d="hrPath" fill="none" stroke="#b91c1c" stroke-width="1.6" />
            </template>
            <text v-for="k in kmTicks" :key="'k' + k" :x="x(k * 1000)" :y="H - 6" text-anchor="middle">{{ k }} km</text>
            <rect v-if="sel" :x="x(sel[0] * 1000)" :y="T" :width="Math.max(2, x(sel[1] * 1000) - x(sel[0] * 1000))" :height="H - T - B" fill="none" stroke="#047857" stroke-width="2" stroke-dasharray="5 3" />
          </svg>
        </div>
      </section>

      <section v-if="profile.length && d.altitude_available !== undefined" class="aa-card">
        <div class="aa-top"><h2>{{ t('activityAnalysis.idx.title') }}</h2></div>
        <p class="aa-muted aa-p">{{ t('activityAnalysis.idx.intro') }}</p>
        <div class="aa-chips">
          <button v-for="c in climbs" :key="c.start_km" class="aa-chip" :class="{ on: stretchKey === c.start_km }" @click="pickClimb(c)">
            {{ t(c.type === 'climb' ? 'activityAnalysis.idx.climb_chip' : 'activityAnalysis.idx.descent_chip', { a: num(c.start_km, 1), b: num(c.start_km + c.length_m / 1000, 1) }) }}
          </button>
          <button class="aa-chip" :class="{ on: stretchKey === 'manual' }" @click="stretchKey = 'manual'">{{ t('activityAnalysis.idx.manual') }}</button>
        </div>
        <div v-if="stretchKey === 'manual'" class="aa-ctrl">
          <label for="aa-r0">{{ t('activityAnalysis.idx.start') }} <b class="m">{{ num(manual[0], 1) }} km</b></label>
          <input id="aa-r0" v-model.number="manual[0]" type="range" min="0" :max="maxKm" step="0.1" @change="clampManual" />
          <label for="aa-r1">{{ t('activityAnalysis.idx.end') }} <b class="m">{{ num(manual[1], 1) }} km</b></label>
          <input id="aa-r1" v-model.number="manual[1]" type="range" min="0" :max="maxKm" step="0.1" @change="clampManual" />
        </div>
        <div class="aa-ctrl">
          <label for="aa-per">{{ t('activityAnalysis.idx.period') }}</label>
          <select id="aa-per" v-model.number="period">
            <option :value="180">{{ t('activityAnalysis.idx.p180') }}</option>
            <option :value="365">{{ t('activityAnalysis.idx.p365') }}</option>
            <option :value="1825">{{ t('activityAnalysis.idx.p1825') }}</option>
          </select>
          <label for="aa-met">{{ t('activityAnalysis.idx.metric') }}</label>
          <select id="aa-met" v-model="metric">
            <option value="eff">{{ t('activityAnalysis.idx.eff') }}</option>
            <option value="time">{{ t('activityAnalysis.idx.time') }}</option>
          </select>
          <label for="aa-tol">{{ t('activityAnalysis.idx.tol') }}</label>
          <select id="aa-tol" v-model.number="tol">
            <option :value="15">15 m</option><option :value="30">30 m</option><option :value="60">60 m</option><option :value="100">100 m</option>
          </select>
        </div>
        <div><button class="btn btn-outline aa-btn" :disabled="idxLoading || !sel" @click="loadIdx">{{ t('activityAnalysis.idx.apply') }}</button></div>

        <p v-if="idxLoading" class="aa-note">{{ t('activityAnalysis.idx.loading') }}</p>
        <p v-else-if="idx && idx.error" class="aa-note">{{ idx.error }}</p>
        <template v-else-if="idx">
          <div class="aa-idx">
            <div v-if="idx.index_pct !== null">
              <div class="aa-eyebrow">{{ t('activityAnalysis.idx.today_vs') }}</div>
              <div class="aa-big" :class="idx.index_pct >= 0 ? 'good' : 'bad'">{{ (idx.index_pct >= 0 ? '+' : '') + num(idx.index_pct, 1) }}%</div>
              <div class="aa-s">{{ t('activityAnalysis.idx.n_past', { n: idx.n_past }) }}</div>
            </div>
            <p v-else class="aa-note">{{ t('activityAnalysis.idx.few', { n: idx.n_past }) }}</p>
            <svg v-if="spark" viewBox="0 0 320 90" class="aa-spark" role="img" :aria-label="t('activityAnalysis.idx.title')">
              <line x1="20" x2="300" :y1="spark.zero" :y2="spark.zero" stroke="#e2e8f0" stroke-dasharray="3 3" />
              <text x="304" :y="spark.zero + 3">0</text>
              <path :d="spark.area" fill="#047857" opacity=".12" />
              <path :d="spark.line" fill="none" stroke="#047857" stroke-width="2" />
              <circle v-for="(p, i) in spark.pts" :key="i" :cx="p[0]" :cy="p[1]" :r="i === spark.pts.length - 1 ? 4.5 : 2.5" fill="#047857" />
              <text x="20" y="88">{{ spark.first }}</text><text x="300" y="88" text-anchor="end">{{ t('activityAnalysis.idx.today') }}</text>
            </svg>
          </div>
          <div class="aa-scroll">
            <table class="aa-table">
              <thead><tr>
                <th>{{ t('activityAnalysis.idx.date') }}</th><th>{{ t('activityAnalysis.idx.time_col') }}</th><th>{{ t('activityAnalysis.idx.hr') }}</th>
                <th>{{ stretchUp ? t('activityAnalysis.idx.vam') : t('activityAnalysis.idx.vert') }}</th><th>{{ t('activityAnalysis.idx.mpb') }}</th><th>{{ t('activityAnalysis.idx.index') }}</th>
              </tr></thead>
              <tbody>
                <tr class="today">
                  <td>{{ shortDate(idx.date) }} ({{ t('activityAnalysis.idx.today') }})</td><td>{{ mmss(idx.today.time_s) }}</td><td>{{ idx.today.hr ?? '-' }}</td>
                  <td>{{ idx.today.vertical_m_h ?? '-' }}</td><td>{{ num(idx.today.m_per_beat, 2) }}</td><td>{{ signed(idx.index_pct) }}</td>
                </tr>
                <tr v-for="p in pastDesc" :key="p.activity_id">
                  <td><router-link :to="{ name: 'ActivityAnalysis', params: { id: p.activity_id } }">{{ shortDate(p.date) }}</router-link></td>
                  <td>{{ mmss(p.time_s) }}</td><td>{{ p.hr ?? '-' }}</td><td>{{ p.vertical_m_h ?? '-' }}</td>
                  <td>{{ num(p.m_per_beat, 2) }}</td><td>{{ signed(p.index_pct) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="idx.pending_runs" class="aa-note">
            {{ t('activityAnalysis.idx.pending', { n: idx.pending_runs }) }}
            <button class="aa-link" :disabled="idxLoading" @click="loadIdx">{{ t('activityAnalysis.idx.more') }}</button>
          </p>
          <p class="aa-note">{{ t('activityAnalysis.idx.note', { rest: idx.settings.hr_rest }) }}</p>
        </template>
      </section>

      <div class="aa-grid2">
        <section class="aa-card">
          <h2>{{ t('activityAnalysis.climbs.title') }}</h2>
          <div v-for="(c, i) in climbs" :key="i">
            <div class="aa-tag" :class="c.type">{{ t(`activityAnalysis.climbs.${c.type}`, { km: num(c.start_km, 1) }) }}</div>
            <dl class="aa-seg">
              <dt>{{ t('activityAnalysis.climbs.length') }}</dt><dd>{{ num(c.length_m / 1000, 2) }} km / {{ c.type === 'climb' ? '+' : '-' }}{{ c.elev_m }} m</dd>
              <dt>{{ t('activityAnalysis.climbs.grade') }}</dt><dd>{{ num(c.grade_pct, 1) }}%</dd>
              <dt>{{ t('activityAnalysis.climbs.time') }}</dt><dd>{{ mmss(c.duration_s) }} / {{ pace(c.pace_s_km) }}</dd>
              <dt>{{ c.type === 'climb' ? t('activityAnalysis.climbs.vam') : t('activityAnalysis.climbs.vert') }}</dt><dd>{{ c.type === 'climb' ? c.vam_m_h : c.vertical_speed_m_h }} m/h</dd>
              <template v-if="c.hr"><dt>{{ t('activityAnalysis.climbs.hr') }}</dt><dd>{{ c.hr }} / {{ c.hr_end }}</dd></template>
            </dl>
          </div>
          <p v-if="!climbs.length" class="aa-note">{{ t('activityAnalysis.climbs.none') }}</p>
        </section>

        <section class="aa-card">
          <h2>{{ t('activityAnalysis.ai.title') }}</h2>
          <p class="aa-muted aa-p">{{ t('activityAnalysis.ai.text') }}</p>
          <div ref="promptEl" class="aa-prompt">{{ aiPrompt }}</div>
          <div class="aa-btns">
            <router-link class="btn btn-primary" :to="{ name: 'Calendar', query: { ask: aiPrompt } }">{{ t('activityAnalysis.ai.open') }}</router-link>
            <button class="btn btn-outline" @click="copyPrompt">{{ t('activityAnalysis.ai.copy') }}</button>
          </div>
          <p v-if="copyMsg" class="aa-note">{{ copyMsg }}</p>
        </section>
      </div>

      <section v-if="splits.length" class="aa-card">
        <h2>{{ t('activityAnalysis.splits.title') }}</h2>
        <div class="aa-scroll">
          <table class="aa-table">
            <thead><tr>
              <th>{{ t('activityAnalysis.splits.km') }}</th><th>{{ t('activityAnalysis.splits.pace') }}</th><th>{{ t('activityAnalysis.splits.gap') }}</th>
              <th>{{ t('activityAnalysis.splits.hr') }}</th><th>{{ t('activityAnalysis.splits.cad') }}</th><th>{{ t('activityAnalysis.splits.dplus') }}</th>
              <th>{{ t('activityAnalysis.splits.dminus') }}</th><th>{{ t('activityAnalysis.splits.grade') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="(s, i) in splits" :key="i" :class="{ slow: s.pace_s_km === slowest }">
                <td>{{ i + 1 }}</td><td>{{ pace(s.pace_s_km) }}</td><td>{{ pace(s.gap_s_km) }}</td><td>{{ s.hr ?? '-' }}</td>
                <td>{{ s.cadence_spm ?? '-' }}</td><td>{{ s.d_plus ?? '-' }}</td><td>{{ s.d_minus ?? '-' }}</td>
                <td>{{ s.grade_pct != null ? num(s.grade_pct, 1) + '%' : '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="aa-note">{{ t('activityAnalysis.splits.note') }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthGate from '../components/AuthGate.vue'
import { useAuthStore } from '../stores/auth'
import api from '../services/api'

const { t, te, locale } = useI18n()
const route = useRoute()
const authStore = useAuthStore()

const loading = ref(true)
const error = ref('')
const data = ref(null)
const d = computed(() => data.value?.detail || {})
const plan = computed(() => data.value?.plan || {})
const profile = computed(() => data.value?.profile || [])
const splits = computed(() => d.value.splits || [])
const climbs = computed(() => d.value.climbs_descents || [])

// ---- formatting
const num = (v, n = 0) => v == null ? '-' : Number(v).toLocaleString(locale.value, { minimumFractionDigits: n, maximumFractionDigits: n })
const mmss = s => s == null ? '-' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
const pace = s => s ? mmss(s) : '-'
const hms = s => { if (!s) return '-'; const h = Math.floor(s / 3600); return h ? `${h}:${mmss(s % 3600).padStart(5, '0')}` : mmss(s) }
const signed = v => v == null ? '-' : `${v >= 0 ? '+' : ''}${num(v, 1)}%`
const shortDate = iso => new Date(iso + 'T12:00').toLocaleDateString(locale.value, { day: 'numeric', month: 'short', year: '2-digit' })
const longDate = computed(() => d.value.date ? new Date(d.value.date + 'T12:00').toLocaleDateString(locale.value, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) : '')
const dayLabel = day => te(`calendarWeek.days.${day}`) ? t(`calendarWeek.days.${day}`) : day
const planName = computed(() => plan.value.plan_name || `#${plan.value.plan_id}`)

// ---- summary numbers
const avgPace = computed(() => d.value.moving_time_s && d.value.distance_km ? Math.round(d.value.moving_time_s / d.value.distance_km) : null)
const avgGap = computed(() => {
  const r = splits.value.filter(s => s.gap_s_km)
  if (!r.length) return null
  const dist = r.reduce((a, s) => a + s.distance_m, 0)
  return Math.round(r.reduce((a, s) => a + s.gap_s_km * s.distance_m, 0) / dist)
})
const hasHr = computed(() => profile.value.some(p => p[2]))
const hrAvg = computed(() => {
  const r = splits.value.filter(s => s.hr)
  if (!r.length) return null
  return Math.round(r.reduce((a, s) => a + s.hr * s.time_s, 0) / r.reduce((a, s) => a + s.time_s, 0))
})
const hrMax = computed(() => Math.max(...profile.value.map(p => p[2] || 0)) || '-')
const slowest = computed(() => Math.max(...splits.value.map(s => s.pace_s_km || 0)))
const hilly = computed(() => climbs.value.some(c => c.elev_m >= 50))

// ---- zones
const ZONE_COLORS = ['#94a3b8', '#0284c7', '#047857', '#b45309', '#b91c1c']
const zones = computed(() => Object.entries(d.value.hr_zones || {}).map(([k, z], i) => ({
  k, pct: z.pct, seconds: z.seconds, color: ZONE_COLORS[i],
  name: te(`activityAnalysis.zones.names.${z.name}`) ? t(`activityAnalysis.zones.names.${z.name}`) : z.name,
})))

// ---- plan comparison
const ratioCls = r => r == null ? '' : (r > 1.5 || r < 0.6) ? 'bad' : (r > 1.2 || r < 0.8) ? 'warn' : 'good'
const cmpRows = computed(() => {
  const p = plan.value.planned || {}, a = plan.value.actual || {}
  const rows = []
  const add = (label, pv, av, fmt) => {
    if (!pv) return
    const r = av / pv
    rows.push({ label, planned: fmt(pv), done: fmt(av), pct: `${Math.round(r * 100)}%`, cls: ratioCls(r) })
  }
  add(t('activityAnalysis.plan.distance'), p.distance_km, a.distance_km, v => `${num(v, 1)} km`)
  add(t('activityAnalysis.plan.elevation'), p.elevation_m, a.elevation_m, v => `${num(v)} m`)
  add(t('activityAnalysis.plan.duration'), p.duration_min, a.duration_min, v => `${num(v)}'`)
  for (const s of plan.value.steps || []) {
    if (!s.target_bpm) continue
    rows.push({ label: t('activityAnalysis.plan.hr_target'), planned: `Z${s.target_zone} ${s.target_bpm[0]}-${s.target_bpm[1]}`,
      done: t('activityAnalysis.plan.avg', { v: s.hr }), pct: s.target_met ? 'ok' : 'no', cls: s.target_met ? 'good' : 'bad' })
  }
  return rows
})
const hrTarget = computed(() => (plan.value.steps || []).find(s => s.target_bpm)?.target_bpm || null)
const verdict = computed(() => {
  const p = plan.value.planned || {}, a = plan.value.actual || {}
  const parts = []
  const rd = p.distance_km ? a.distance_km / p.distance_km : 1
  const re = p.elevation_m ? a.elevation_m / p.elevation_m : 1
  if (rd > 1.2) parts.push(t('activityAnalysis.plan.longer'))
  else if (rd < 0.8) parts.push(t('activityAnalysis.plan.shorter'))
  if (!plan.value.treadmill) {
    if (re > 1.5 && a.elevation_m - p.elevation_m > 50) parts.push(t('activityAnalysis.plan.more_climb'))
    else if (re < 0.6 && p.elevation_m - a.elevation_m > 50) parts.push(t('activityAnalysis.plan.less_climb'))
  }
  for (const s of plan.value.steps || []) {
    if (!s.target_bpm || s.hr == null) continue
    if (s.hr > s.target_bpm[1]) { parts.push(t('activityAnalysis.plan.hr_high')); break }
    if (s.hr < s.target_bpm[0]) { parts.push(t('activityAnalysis.plan.hr_low')); break }
  }
  if (!parts.length) return { ok: true, text: t('activityAnalysis.plan.match') }
  const s = parts.join(', ')
  return { ok: false, text: s.charAt(0).toUpperCase() + s.slice(1) + '.' }
})

// ---- profile chart (one scale per axis)
const W = 1000, H = 240, L = 40, R = 40, T = 10, B = 24
const maxD = computed(() => profile.value.at(-1)?.[0] || 1)
const maxKm = computed(() => Math.floor(maxD.value / 100) / 10)
const alts = computed(() => profile.value.map(p => p[1]).filter(v => v != null))
const aMin = computed(() => Math.floor(Math.min(...alts.value) / 20) * 20)
const aMax = computed(() => Math.max(aMin.value + 20, Math.ceil(Math.max(...alts.value) / 20) * 20))
const hrs = computed(() => profile.value.map(p => p[2]).filter(Boolean))
const hMin = computed(() => Math.floor(Math.min(...hrs.value, hrTarget.value?.[0] ?? 999) / 10) * 10)
const hMax = computed(() => Math.ceil(Math.max(...hrs.value, hrTarget.value?.[1] ?? 0) / 10) * 10)
const x = m => L + (m / maxD.value) * (W - L - R)
const ya = a => T + (1 - (a - aMin.value) / (aMax.value - aMin.value)) * (H - T - B)
const yh = h => T + (1 - (h - hMin.value) / ((hMax.value - hMin.value) || 1)) * (H - T - B)
const ticks = (lo, hi, n) => { const step = Math.max(1, Math.ceil((hi - lo) / n / 10) * 10); const out = []; for (let v = lo; v <= hi; v += step) out.push(v); return out }
const altTicks = computed(() => ticks(aMin.value, aMax.value, 4))
const hrTicks = computed(() => ticks(hMin.value, hMax.value, 4))
const kmTicks = computed(() => { const n = Math.floor(maxD.value / 1000), st = n > 30 ? 10 : n > 12 ? 5 : n > 6 ? 2 : 1; const o = []; for (let k = 0; k <= n; k += st) o.push(k); return o })
const altPath = computed(() => {
  const pts = profile.value.filter(p => p[1] != null)
  return `M${x(pts[0][0])},${H - B} ` + pts.map(p => `L${x(p[0]).toFixed(1)},${ya(p[1]).toFixed(1)}`).join(' ') + ` L${x(pts.at(-1)[0])},${H - B}Z`
})
const hrPath = computed(() => profile.value.filter(p => p[2]).map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${yh(p[2]).toFixed(1)}`).join(' '))

// ---- improvement index
const stretchKey = ref(null)
const manual = ref([0, 1])
const period = ref(365)
const metric = ref('eff')
const tol = ref(30)
const idx = ref(null)
const idxLoading = ref(false)
const sel = computed(() => {
  if (stretchKey.value === 'manual') return manual.value
  const c = climbs.value.find(c => c.start_km === stretchKey.value)
  return c ? [c.start_km, c.start_km + c.length_m / 1000] : null
})
const stretchUp = computed(() => {
  const c = climbs.value.find(c => c.start_km === stretchKey.value)
  return c ? c.type === 'climb' : (idx.value?.today?.vertical_m_h ?? 0) >= 0
})
const pastDesc = computed(() => [...(idx.value?.past || [])].reverse())
function pickClimb(c) { stretchKey.value = c.start_km; manual.value = [c.start_km, +(c.start_km + c.length_m / 1000).toFixed(1)] }
function clampManual() {
  if (manual.value[1] <= manual.value[0] + 0.2) manual.value[1] = Math.min(maxKm.value, +(manual.value[0] + 0.3).toFixed(1))
}
async function loadIdx() {
  if (!sel.value) return
  idxLoading.value = true
  try {
    const { data: r } = await api.get(`/activities/${route.params.id}/improvement`, { params: {
      start_km: sel.value[0], end_km: sel.value[1], metric: metric.value, tolerance_m: tol.value, period_days: period.value } })
    idx.value = r
  } catch (e) {
    idx.value = { error: e.response?.data?.error || e.message }
  } finally {
    idxLoading.value = false
  }
}
const spark = computed(() => {
  const r = idx.value
  if (!r || r.index_pct == null) return null
  const iv = [...r.past.map(p => p.index_pct).filter(v => v != null), r.index_pct]
  if (iv.length < 2) return null
  const lo = Math.min(...iv, 0), hi = Math.max(...iv, 0)
  const sx = i => 20 + i * (280 / (iv.length - 1)), sy = v => 10 + (1 - (v - lo) / ((hi - lo) || 1)) * 65
  const pts = iv.map((v, i) => [sx(i), sy(v)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  return { pts, line, zero: sy(0), area: `M${sx(0)},${sy(lo)} ${line.replace(/^M/, 'L')} L${sx(iv.length - 1)},${sy(lo)}Z`,
    first: r.past[0]?.date?.slice(0, 7) || '' }
})

// ---- AI handoff
const aiPrompt = computed(() => t('activityAnalysis.ai.prompt', { date: shortDate(d.value.date || '2000-01-01'), id: d.value.activity_id }))
const promptEl = ref(null)
const copyMsg = ref('')
async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(aiPrompt.value)
    copyMsg.value = t('activityAnalysis.ai.copied')
  } catch {
    window.getSelection().selectAllChildren(promptEl.value)
    copyMsg.value = t('activityAnalysis.ai.select')
  }
}

async function load() {
  loading.value = true
  error.value = ''
  idx.value = null
  try {
    const { data: r } = await api.get(`/activities/${route.params.id}/analysis`)
    data.value = r
    const big = [...(r.detail.climbs_descents || [])].filter(c => c.type === 'climb').sort((a, b) => b.elev_m - a.elev_m)[0]
    if (big) pickClimb(big)
    else stretchKey.value = 'manual'
    manual.value = sel.value ? [...sel.value] : [0, Math.min(1, maxKm.value)]
    if (big) loadIdx()
  } catch (e) {
    error.value = e.response?.status === 404 ? t('activityAnalysis.not_found') : (e.response?.data?.error || e.message)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await authStore.ensureAuthReady()
  if (authStore.isAuthenticated) load()
  else loading.value = false
})
watch(() => route.params.id, id => { if (id && authStore.isAuthenticated) load() })
</script>

<style scoped>
.aa { display: grid; gap: 16px; padding-block: 24px 48px; }
.aa h1 { font-size: 2rem; line-height: 1.1; margin: 0; text-wrap: balance; }
.aa h2 { font-size: 1.15rem; color: #475569; margin: 0; }
.aa-back { font-size: .85rem; color: #047857; text-decoration: none; font-weight: 600; }
.aa-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; min-width: 0; display: grid; gap: 12px; align-content: start; }
.aa-eyebrow { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #94a3b8; font-weight: 600; }
.aa-top { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; align-items: end; }
.aa-pills, .aa-chips, .aa-btns { display: flex; gap: 8px; flex-wrap: wrap; }
.aa-pill { font-size: .75rem; font-weight: 600; padding: 3px 10px; border-radius: 999px; border: 1px solid #e2e8f0; color: #475569; }
.aa-pill.warn { border-color: #b45309; color: #b45309; }
.aa-pill.ok { border-color: #047857; color: #047857; }
.aa-stats { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
.aa-v { font-family: var(--font-display); font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.aa-s { color: #475569; font-size: .8rem; }
.aa-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 760px) { .aa-grid2 { grid-template-columns: 1fr; } }
.aa-cmp { display: grid; grid-template-columns: auto 1fr 1fr auto; gap: 6px 14px; align-items: center; }
.aa-cmp .h { font-size: .72rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .06em; }
.m { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.r { text-align: right; }
.good { color: #047857; } .warn { color: #b45309; } .bad { color: #b91c1c; }
.aa-verdict { border-left: 3px solid #b45309; padding: 8px 12px; background: #fffbeb; border-radius: 4px; }
.aa-verdict.ok { border-color: #047857; background: #ecfdf5; }
.aa-zbar { display: flex; height: 22px; border-radius: 4px; overflow: hidden; }
.aa-zrow { display: grid; grid-template-columns: 28px 1fr 60px 52px; gap: 8px; align-items: center; font-size: .85rem; }
.aa-zb { height: 8px; border-radius: 4px; }
.aa-muted { color: #475569; }
.aa-p { margin: 0; }
.aa-note { font-size: .8rem; color: #64748b; margin: 0; }
.aa-scroll { overflow-x: auto; }
.aa-prof { width: 100%; min-width: 560px; height: auto; }
.aa-prof text, .aa-spark text { fill: #94a3b8; font-family: var(--font-mono); font-size: 10px; }
.aa-prof .t-hr { fill: #b91c1c; } .aa-prof .t-forest { fill: #047857; }
.aa-legend { display: flex; gap: 16px; font-size: .8rem; color: #475569; flex-wrap: wrap; }
.aa-legend i { display: inline-block; width: 12px; height: 3px; vertical-align: middle; margin-right: 6px; }
.aa-legend i.alt { background: #cbd5e1; height: 8px; } .aa-legend i.hr { background: #b91c1c; } .aa-legend i.seg { background: #0284c7; opacity: .35; height: 10px; }
.aa-table { border-collapse: collapse; width: 100%; font-size: .85rem; }
.aa-table th { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; color: #94a3b8; text-align: right; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; font-weight: 600; }
.aa-table td { text-align: right; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.aa-table th:first-child, .aa-table td:first-child { text-align: left; }
.aa-table tr.slow td { background: #f0f9ff; }
.aa-table tr.today td { font-weight: 600; background: #ecfdf5; }
.aa-table a { color: #047857; }
.aa-seg { display: grid; grid-template-columns: auto 1fr; gap: 4px 16px; font-size: .88rem; margin: 4px 0 0; }
.aa-seg dt { color: #475569; } .aa-seg dd { margin: 0; font-family: var(--font-mono); text-align: right; }
.aa-tag { font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
.aa-tag.climb { color: #b45309; } .aa-tag.descent { color: #0284c7; }
.aa-chip { font-size: .8rem; padding: 6px 14px; border-radius: 999px; border: 1px solid #e2e8f0; color: #475569; background: transparent; cursor: pointer; }
.aa-chip.on { border-color: #047857; color: #047857; background: #ecfdf5; }
.aa-chip:focus-visible, .aa-link:focus-visible { outline: 2px solid #0284c7; outline-offset: 2px; }
.aa-ctrl { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; align-items: center; max-width: 520px; font-size: .85rem; color: #475569; }
.aa-ctrl input { accent-color: #047857; width: 100%; }
.aa-ctrl select { border: 1px solid #e2e8f0; border-radius: 6px; padding: 5px 8px; background: #fff; }
.aa-btn { padding: 6px 18px; }
.aa-idx { display: flex; flex-wrap: wrap; gap: 24px; align-items: center; }
.aa-big { font-family: var(--font-display); font-size: 2.6rem; font-weight: 700; line-height: 1; }
.aa-spark { width: 100%; max-width: 420px; height: auto; }
.aa-prompt { font-family: var(--font-mono); font-size: .82rem; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 12px; color: #475569; }
.aa-link { background: none; border: 0; color: #047857; font-weight: 600; cursor: pointer; padding: 0 4px; text-decoration: underline; }
</style>
