<template>
  <div class="space-y-8 sm:space-y-12">
    <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 pb-4 sm:pb-6 border-b border-slate-200">
      <h1 class="text-3xl font-bold text-slate-900 uppercase tracking-tight">{{ $t('demo.title') }}</h1>
      <span class="text-xs text-slate-400 font-mono">{{ $t('demo.badge') }}</span>
    </div>

    <div v-if="!prediction" class="grid lg:grid-cols-2 gap-8 lg:gap-12 items-stretch">
      <div class="relative">
        <div class="absolute -inset-4 bg-gradient-to-tr from-emerald-100 to-sky-100 rounded-[2rem] opacity-70 blur-2xl"></div>
        <div class="relative bg-white rounded-2xl shadow-xl border border-slate-100 p-5 sm:p-8 md:p-10 space-y-5 sm:space-y-6">
          <h3 class="text-2xl font-bold text-slate-800 uppercase tracking-wide">{{ $t('demo.try_card.title') }}</h3>
          <p class="text-slate-600 text-sm leading-relaxed">{{ $t('demo.try_card.description') }}</p>

          <div class="space-y-3 pt-2">
            <div class="flex items-center justify-between gap-3 p-4 rounded-xl border border-emerald-200 bg-emerald-50/50">
              <div>
                <div class="text-sm font-bold text-emerald-900">UTMB Pyramides</div>
                <div class="text-xs text-emerald-700/80">{{ $t('demo.course_meta') }}</div>
              </div>
              <span class="text-xs uppercase tracking-wide text-emerald-700 font-mono">{{ $t('demo.selected') }}</span>
            </div>
          </div>

          <button
            @click="runDemo"
            :disabled="loading"
            class="w-full btn btn-primary py-3 disabled:opacity-50"
          >
            <span v-if="loading">{{ $t('demo.try_card.predicting') }}</span>
            <span v-else>{{ $t('demo.try_card.button') }}</span>
          </button>

          <p v-if="error" class="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">{{ error }}</p>
        </div>
      </div>

      <div class="relative order-1 lg:order-2 bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-2xl p-5 sm:p-8 space-y-4">
        <h3 class="text-lg font-bold text-slate-900">{{ $t('demo.what_you_get.title') }}</h3>
        <ul class="space-y-3 text-sm text-slate-700">
          <li class="flex gap-3"><span class="text-emerald-600">●</span>{{ $t('demo.what_you_get.item_total_time') }}</li>
          <li class="flex gap-3"><span class="text-emerald-600">●</span>{{ $t('demo.what_you_get.item_ci') }}</li>
          <li class="flex gap-3"><span class="text-emerald-600">●</span>{{ $t('demo.what_you_get.item_segments') }}</li>
          <li class="flex gap-3"><span class="text-emerald-600">●</span>{{ $t('demo.what_you_get.item_map') }}</li>
        </ul>
        <div class="border-t border-slate-200 pt-4 mt-4">
          <p class="text-xs text-slate-500 leading-relaxed">{{ $t('demo.what_you_get.disclaimer') }}</p>
        </div>
      </div>
    </div>

    <div v-else class="space-y-8">
      <div class="grid md:grid-cols-3 gap-4">
        <div class="bg-white border border-slate-200 rounded-xl p-4 sm:p-6">
          <div class="text-xs uppercase tracking-wide text-slate-500 font-mono">{{ $t('demo.results.total_time') }}</div>
          <div class="text-3xl font-bold text-emerald-700 font-mono mt-1">{{ prediction.total_time_formatted }}</div>
        </div>
        <div class="bg-white border border-slate-200 rounded-xl p-4 sm:p-6">
          <div class="text-xs uppercase tracking-wide text-slate-500 font-mono">{{ $t('demo.results.ci') }}</div>
          <div class="text-lg font-mono text-slate-700 mt-1">
            {{ prediction.confidence_interval?.lower_formatted }} – {{ prediction.confidence_interval?.upper_formatted }}
          </div>
        </div>
        <div class="bg-white border border-slate-200 rounded-xl p-4 sm:p-6">
          <div class="text-xs uppercase tracking-wide text-slate-500 font-mono">{{ $t('demo.results.tier') }}</div>
          <div class="text-lg text-slate-700 mt-1">{{ prediction.metadata?.method }}</div>
          <div class="text-xs text-slate-500 mt-1">{{ prediction.metadata?.description }}</div>
        </div>
      </div>

      <div class="bg-emerald-50 border border-emerald-200 rounded-2xl p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div class="text-sm font-bold text-emerald-900">{{ $t('demo.cta_banner.title') }}</div>
          <div class="text-xs text-emerald-800/80 mt-1">{{ $t('demo.cta_banner.description') }}</div>
        </div>
        <router-link to="/predict" class="btn btn-primary px-6 py-3 whitespace-nowrap">
          {{ $t('demo.cta_banner.button') }}
        </router-link>
      </div>

      <div class="bg-white border border-slate-200 rounded-2xl p-4 overflow-hidden">
        <h3 class="text-sm font-bold text-slate-800 uppercase tracking-wide px-2 mb-2">{{ $t('demo.results.map') }}</h3>
        <div class="h-[300px] sm:h-[420px] rounded-xl overflow-hidden">
          <MapView v-if="route?.points?.length" :points="route.points" />
        </div>
      </div>

      <div class="bg-white border border-slate-200 rounded-2xl p-4">
        <h3 class="text-sm font-bold text-slate-800 uppercase tracking-wide px-2 mb-2">{{ $t('demo.results.elevation') }}</h3>
        <ElevationProfile v-if="route?.points?.length" :points="route.points" :compact="false" />
      </div>

      <button @click="reset" class="py-2 text-sm text-slate-500 hover:text-slate-800">{{ $t('demo.results.run_again') }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'
import { useI18n } from 'vue-i18n'
import MapView from '../components/MapView.vue'
import ElevationProfile from '../components/ElevationProfile.vue'

const { t } = useI18n()
const loading = ref(false)
const error = ref(null)
const prediction = ref(null)
const route = ref(null)

const runDemo = async () => {
  loading.value = true
  error.value = null
  try {
    const { data } = await axios.post('/api/demo/predict', { route_id: 'utmb_pyramides' })
    prediction.value = data.prediction
    route.value = data.route
  } catch (e) {
    error.value = e?.response?.data?.message || e?.response?.data?.error || t('demo.failed')
  } finally {
    loading.value = false
  }
}

const reset = () => {
  prediction.value = null
  route.value = null
  error.value = null
}
</script>
