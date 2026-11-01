<template>
  <div class="stack w-full">
    <AuthGate v-if="authStore.authChecked && !authStore.isAuthenticated" />
    <template v-else>
    <AchievementNotification />

    <section class="card stack">
      <div>
        <h1 class="section-title">{{ $t('prediction.title') }}</h1>
        <p class="section-subtitle">
        {{ $t('prediction.subtitle') }}
        <strong>{{ gpxStore.currentGpx?.original_filename }}</strong>
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-4">
        <span class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{{ $t('prediction.effort') }}</span>
        <div class="segmented">
          <button
            @click="setEffort('race')"
            :class="[
              'segment-btn',
              predictionStore.effort === 'race' ? 'segment-active' : ''
            ]"
          >
            {{ $t('prediction.efforts.race') }}
          </button>
          <button
            @click="setEffort('training')"
            :class="[
              'segment-btn',
              predictionStore.effort === 'training' ? 'segment-active' : ''
            ]"
          >
            {{ $t('prediction.efforts.training') }}
          </button>
          <button
            @click="setEffort('recovery')"
            :class="[
              'segment-btn',
              predictionStore.effort === 'recovery' ? 'segment-active' : ''
            ]"
          >
            {{ $t('prediction.efforts.recovery') }}
          </button>
        </div>
        <span class="text-xs text-slate-500">
          {{ getEffortDescription(predictionStore.effort) }}
        </span>
        <span v-if="intensity && !predictionStore.targetHr" class="text-xs text-emerald-700">
          {{ $t('prediction.effort_hr', intensity) }}
        </span>
      </div>

      <!-- Target HR: the user tries a bpm, we re-predict and say how realistic it is for them. -->
      <div v-if="intensity" class="flex flex-col gap-3">
        <div class="flex items-center justify-between gap-3">
          <label for="target-hr" class="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
            <Icon name="heart-pulse" class="!w-4 !h-4 text-rose-500" />
            {{ $t('prediction.target_hr.label') }}
          </label>
          <span class="text-right">
            <span class="block font-mono text-lg font-semibold text-slate-900">{{ hrDraft }} bpm</span>
            <span v-if="predictionStore.prediction?.total_time_formatted" class="block font-mono text-sm text-emerald-700">
              {{ predictionStore.loading ? '…' : (predictionStore.totalStopTimeSeconds > 0 ? predictionStore.adjustedTotalTimeFormatted : predictionStore.prediction.total_time_formatted) }}
            </span>
          </span>
        </div>
        <input
          id="target-hr"
          v-model.number="hrDraft"
          type="range"
          :min="hrMin"
          :max="intensity.hr_max"
          step="1"
          class="w-full h-11 accent-emerald-700"
          @change="predictionStore.targetHr = hrDraft"
        />
        <div v-if="verdict" :class="['rounded-xl border p-3 flex gap-3 text-sm', VERDICT_STYLE[verdict.level].box]">
          <Icon :name="VERDICT_STYLE[verdict.level].icon" :class="['mt-0.5', VERDICT_STYLE[verdict.level].icon_color]" />
          <div class="flex flex-col gap-1">
            <p class="font-semibold">{{ $t(`prediction.target_hr.verdict.${verdict.level}.title`) }}</p>
            <p>{{ $t(`prediction.target_hr.verdict.${verdict.level}.text`, { hr: intensity.target_hr, race_hr: verdict.race_hr }) }}</p>
            <p v-if="verdict.best" class="text-xs opacity-80">
              {{ $t('prediction.target_hr.best', { hr: verdict.best.hr, hours: verdict.best.hours, name: verdict.best.name }) }}
            </p>
          </div>
        </div>
        <button v-if="predictionStore.targetHr" type="button" class="btn btn-ghost self-start min-h-[44px]" @click="setEffort(predictionStore.effort)">
          {{ $t('prediction.target_hr.reset') }}
        </button>
      </div>
      <!-- TODO(pred-review #34 — see GH issues): pre-race questionnaire (target effort, poles, night hours, heat acclimatisation, taper), each answer mapped to one bounded, validated parameter. -->

      <!-- TODO(pred-review #35 — see GH issues): full aid-station model (per-waypoint minutes, drop bags, sleep for 100-milers). -->
      <div class="flex flex-col gap-2">
        <span class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{{ $t('prediction.aid_stops.title') }}</span>
        <label class="flex flex-col gap-1 text-sm text-slate-700">
          {{ $t('prediction.aid_stops.count') }}
          <input v-model.number="predictionStore.aidStops.count" type="number" inputmode="numeric" min="0" max="60" step="1" class="input w-full min-h-[44px]" />
        </label>
        <label class="flex flex-col gap-1 text-sm text-slate-700">
          {{ $t('prediction.aid_stops.minutes_each') }}
          <input v-model.number="predictionStore.aidStops.minutes_each" type="number" inputmode="numeric" min="0" max="120" step="1" class="input w-full min-h-[44px]" />
        </label>
        <span class="text-xs text-slate-500">{{ $t('prediction.aid_stops.hint') }}</span>
      </div>
    </section>

    <AgentChat :gpx-id="gpxId" :prediction-id="predictionStore.prediction?.prediction_id" prominent />

    <div v-if="predictionStore.error" class="alert alert-error">
      <p>{{ predictionStore.error }}</p>
      <button
        @click="retryPrediction"
        class="btn btn-ghost mt-2"
      >
        {{ $t('prediction.retry') }}
      </button>
    </div>

    <div>
      <div v-if="predictionStore.loading" class="card text-center py-12">
        <div class="animate-spin rounded-full h-16 w-16 border-b-2 border-slate-900 mx-auto mb-4"></div>
        <p class="text-lg font-semibold">{{ $t('prediction.loading.title') }}</p>
        <p class="text-sm text-slate-600 mb-4">{{ $t('prediction.loading.subtitle') }}</p>

        <div class="mt-6 max-w-md mx-auto card card-soft">
          <div class="space-y-2 text-sm text-left">
            <div class="flex items-center gap-2">
              <div class="w-2 h-2 bg-lime-400 rounded-full animate-pulse"></div>
              <span class="text-slate-700">{{ $t('prediction.loading.step1') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="w-2 h-2 bg-lime-400 rounded-full animate-pulse" style="animation-delay: 0.2s"></div>
              <span class="text-slate-700">{{ $t('prediction.loading.step2') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="w-2 h-2 bg-lime-400 rounded-full animate-pulse" style="animation-delay: 0.4s"></div>
              <span class="text-slate-700">{{ $t('prediction.loading.step3') }}</span>
            </div>
          </div>
          <div class="mt-4 text-xs text-slate-500 text-center">
            {{ $t('prediction.loading.wait') }}
          </div>
        </div>
      </div>

      <div v-else-if="predictionStore.prediction">
        <PredictionResults
          :prediction="predictionStore.prediction"
          :similar-activities="predictionStore.similarActivities"
          :selected-activity="predictionStore.selectedActivity"
        />
      </div>

      <div v-else class="card text-center py-12 text-slate-600">
        <p>{{ $t('prediction.empty') }}</p>
      </div>
    </div>

    <WeatherWidget :gpx-id="gpxId" />

    <router-link :to="{ name: 'Home', params: { lang: $route.params.lang } }" class="link">
      {{ $t('prediction.back_home') }}
    </router-link>
    </template>
  </div>
</template>

<script setup>
import Icon from '../components/Icon.vue'
import { onMounted, computed, watch, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useGpxStore } from '../stores/gpx'
import { usePredictionStore } from '../stores/prediction'
import { useAuthStore } from '../stores/auth'
import PredictionResults from '../components/PredictionResults.vue'
import AchievementNotification from '../components/AchievementNotification.vue'
import AgentChat from '../components/AgentChat.vue'
import WeatherWidget from '../components/WeatherWidget.vue'
import AuthGate from '../components/AuthGate.vue'

const route = useRoute()
const gpxStore = useGpxStore()
const predictionStore = usePredictionStore()
const authStore = useAuthStore()
const { t } = useI18n()

const gpxId = computed(() => parseInt(route.params.gpxId))
let aidPrefilledFor = null
let aidTimer = null

const getEffortDescription = (effort) => {
  return t(`prediction.effort_descriptions.${effort}`)
}

const runPrediction = async () => {
  if (predictionStore.loading) return

  // Load GPX data if not already loaded
  if (!gpxStore.currentGpx || gpxStore.currentGpx.id !== gpxId.value) {
    await gpxStore.fetchGpxData(gpxId.value)
  }
  if (aidPrefilledFor !== gpxId.value) {
    aidPrefilledFor = gpxId.value
    predictionStore.aidStops = { count: Math.min(60, gpxStore.gpxData?.waypoints?.length || 0), minutes_each: 0 }
  }

  if (!authStore.isAuthenticated) {
    await authStore.checkAuthStatus()
  }

  if (!authStore.isAuthenticated) {
    predictionStore.error = t('auth.signin.required')
    return
  }

  await predictionStore.predictRouteTime(gpxId.value, true)
}

const retryPrediction = async () => {
  predictionStore.error = null
  await runPrediction()
}

onMounted(async () => {
  predictionStore.targetHr = null // a target belongs to one race, not to the next GPX
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  await runPrediction()
})

const intensity = computed(() => predictionStore.prediction?.metadata?.intensity || null)
const verdict = computed(() => intensity.value?.verdict || null)
const hrMin = computed(() => intensity.value ? Math.round(intensity.value.hr_rest + 0.4 * (intensity.value.hr_max - intensity.value.hr_rest)) : 100)
const hrDraft = ref(null)
watch(intensity, (i) => { if (i?.target_hr) hrDraft.value = i.target_hr }, { immediate: true })

const VERDICT_STYLE = {
  easy: { box: 'border-sky-200 bg-sky-50 text-sky-900', icon: 'circle-check', icon_color: 'text-sky-600' },
  sustainable: { box: 'border-emerald-200 bg-emerald-50 text-emerald-900', icon: 'circle-check', icon_color: 'text-emerald-600' },
  hard: { box: 'border-amber-200 bg-amber-50 text-amber-900', icon: 'flame', icon_color: 'text-amber-600' },
  too_hard: { box: 'border-rose-200 bg-rose-50 text-rose-900', icon: 'triangle-alert', icon_color: 'text-rose-600' },
}

// Picking an effort drops a custom target HR (and re-predicts even if the effort is unchanged).
const setEffort = (e) => {
  const hadTarget = !!predictionStore.targetHr
  predictionStore.targetHr = null
  if (predictionStore.effort !== e) predictionStore.effort = e // the effort watcher re-predicts
  else if (hadTarget && predictionStore.prediction && !predictionStore.loading) runPrediction()
}

watch(() => predictionStore.targetHr, async (hr) => {
  if (hr && predictionStore.prediction && !predictionStore.loading) await runPrediction()
})

watch(() => predictionStore.effort, async () => {
  if (predictionStore.prediction && !predictionStore.loading) {
    await runPrediction()
  }
})

watch(() => [predictionStore.aidStops.count, predictionStore.aidStops.minutes_each], () => {
  clearTimeout(aidTimer)
  aidTimer = setTimeout(() => {
    if (predictionStore.prediction && !predictionStore.loading) runPrediction()
  }, 600)
})
</script>
