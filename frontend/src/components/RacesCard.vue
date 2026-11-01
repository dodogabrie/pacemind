<template>
  <section class="card stack" aria-labelledby="races-title">
    <div>
      <h2 id="races-title" class="text-2xl font-bold flex items-center gap-2">
        <Icon name="trophy" class="!w-6 !h-6" /> {{ t('trainingCenter.races.title') }}
      </h2>
      <p class="section-subtitle mt-1">{{ t('trainingCenter.races.subtitle') }}</p>
    </div>

    <p v-if="loading" class="text-slate-600">{{ t('trainingCenter.races.loading') }}</p>

    <template v-else-if="data">
      <!-- No race in the last 12 months: ask for one. -->
      <div v-if="!data.has_recent_race" class="rounded-xl border border-sky-200 bg-sky-50 text-sky-900 p-4 space-y-2">
        <p class="font-semibold">{{ t('trainingCenter.races.no_recent_title') }}</p>
        <p class="text-sm">{{ t('trainingCenter.races.no_recent_text') }}</p>
        <button type="button" class="btn btn-outline bg-white min-h-[44px]" @click="showUpload = !showUpload">
          <Icon name="upload" class="!w-4 !h-4" /> {{ t('trainingCenter.races.upload') }}
        </button>
      </div>

      <div v-if="data.candidates.length" class="stack">
        <h3 class="font-bold">{{ t('trainingCenter.races.candidates_title') }}</h3>
        <ul class="divide-y divide-slate-200 border-y border-slate-200">
          <li v-for="c in data.candidates" :key="c.id" class="py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0">
              <p v-if="planned(c)" class="text-sm font-semibold text-emerald-700">
                {{ t('trainingCenter.races.planned_question', { race: planned(c).detail }) }}
              </p>
              <p class="font-semibold text-slate-900 truncate">{{ c.name }}</p>
              <p class="text-xs text-slate-600">{{ meta(c) }}</p>
              <p class="text-xs text-slate-500 mt-0.5">{{ c.reasons.map(reasonText).join(' · ') }}</p>
            </div>
            <div class="flex gap-2 shrink-0">
              <button type="button" class="btn btn-primary min-h-[44px] flex-1 sm:flex-none" :disabled="busy === c.id" @click="decide(c, true)">
                <Icon name="check" class="!w-4 !h-4" /> {{ t('trainingCenter.races.yes') }}
              </button>
              <button type="button" class="btn btn-outline min-h-[44px] flex-1 sm:flex-none" :disabled="busy === c.id" @click="decide(c, false)">
                <Icon name="x" class="!w-4 !h-4" /> {{ t('trainingCenter.races.no') }}
              </button>
            </div>
          </li>
        </ul>
      </div>

      <div v-if="data.marked.length" class="stack">
        <h3 class="font-bold">{{ t('trainingCenter.races.marked_title') }}</h3>
        <ul class="divide-y divide-slate-200 border-y border-slate-200">
          <li v-for="m in data.marked" :key="m.id" class="py-3 flex items-center justify-between gap-3">
            <div class="min-w-0">
              <p class="font-semibold text-slate-900 truncate flex items-center gap-1.5">
                <Icon name="flag" class="!w-4 !h-4 text-emerald-600" /> {{ m.name }}
              </p>
              <p class="text-xs text-slate-600">{{ meta(m) }} · {{ t(`trainingCenter.races.source.${m.race_source}`) }}</p>
            </div>
            <button type="button" class="btn btn-outline !px-3 min-h-[44px] shrink-0" :disabled="busy === m.id"
                    :aria-label="t('trainingCenter.races.unmark')" :title="t('trainingCenter.races.unmark')" @click="decide(m, false)">
              <Icon name="x" class="!w-4 !h-4" />
            </button>
          </li>
        </ul>
      </div>

      <p v-if="!data.candidates.length && !data.marked.length" class="text-sm text-slate-600">
        {{ t('trainingCenter.races.empty') }}
      </p>
    </template>
  </section>
  <ActivityImport v-if="showUpload" />
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../services/api'
import { useToastStore } from '../stores/toast'
import Icon from './Icon.vue'
import ActivityImport from './ActivityImport.vue'

const { t, locale } = useI18n()
const toast = useToastStore()
const data = ref(null)
const loading = ref(true)
const busy = ref(null)
const showUpload = ref(false)

const load = async () => {
  try {
    data.value = (await api.get('/activities/races')).data
  } catch (e) {
    console.error('Failed to load races:', e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

const planned = (c) => c.reasons.find(r => r.code === 'planned')

const meta = (a) => {
  const day = new Date(a.date).toLocaleDateString(locale.value, { day: 'numeric', month: 'short', year: 'numeric' })
  return `${day} · ${a.distance_km} km · ${a.elevation_gain_m} m D+`
}

const reasonText = (r) => t(`trainingCenter.races.reason.${r.code}`, { detail: r.detail })

const decide = async (a, isRace) => {
  busy.value = a.id
  try {
    await api.post(`/activities/${a.id}/race`, { is_race: isRace })
    data.value.candidates = data.value.candidates.filter(c => c.id !== a.id)
    data.value.marked = data.value.marked.filter(m => m.id !== a.id)
    if (isRace) {
      data.value.marked.unshift({ ...a, is_race: true, race_source: 'user' })
      data.value.marked.sort((x, y) => y.date.localeCompare(x.date))
    }
    const yearAgo = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10)
    data.value.has_recent_race = data.value.marked.some(m => m.date >= yearAgo)
    toast.push({ message: t(isRace ? 'trainingCenter.races.saved_race' : 'trainingCenter.races.saved_not_race') })
  } catch (e) {
    console.error('Failed to save race flag:', e)
    toast.push({ message: t('trainingCenter.races.save_failed'), type: 'error' })
  } finally {
    busy.value = null
  }
}
</script>
