<template>
  <div class="card stack">
    <!-- Header: title + date picker + accuracy badge -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <h3 class="text-lg font-semibold text-slate-900">{{ $t('weather.title') }}</h3>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
        <label class="text-xs text-slate-500 uppercase tracking-wider">{{ $t('weather.date_label') }}</label>
        <input
          type="date"
          v-model="selectedDate"
          :min="today"
          :max="maxDate"
          class="min-w-0 min-h-[44px] sm:min-h-0 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
        />
        <span
          v-if="weatherData"
          :class="accuracyBadgeClass"
          class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap"
          :title="weatherData.accuracy.description"
        >
          {{ weatherData.accuracy.label }}
        </span>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-8">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-slate-900"></div>
      <span class="ml-3 text-sm text-slate-500">{{ $t('weather.loading') }}</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="text-sm text-slate-500 py-4 text-center">
      {{ $t('weather.error') }}
    </div>

    <!-- Weather data -->
    <div v-else-if="weatherData" class="space-y-5">
      <!-- Conditions description -->
      <p class="text-sm text-slate-600">{{ weatherData.conditions_description }}</p>

      <!-- Main conditions grid -->
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <div class="text-xl font-bold font-mono text-slate-900">{{ weatherData.forecast.temperature_c }}&deg;</div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('weather.temperature') }}</div>
          <div class="text-slate-400 text-[10px] mt-0.5">{{ $t('weather.feels_like') }} {{ weatherData.forecast.apparent_temperature_c }}&deg;</div>
        </div>
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <div class="text-xl font-bold font-mono text-slate-900">{{ weatherData.forecast.wind_speed_ms }}<span class="text-sm font-normal"> m/s</span></div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('weather.wind') }}</div>
        </div>
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <div class="text-xl font-bold font-mono text-slate-900">{{ weatherData.forecast.humidity_pct }}<span class="text-sm font-normal">%</span></div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('weather.humidity') }}</div>
        </div>
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <div class="text-xl font-bold font-mono text-slate-900">{{ weatherData.forecast.precipitation_mm }}<span class="text-sm font-normal"> mm</span></div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('weather.precipitation') }}</div>
        </div>
        <div class="text-center rounded-xl border border-slate-200 px-3 py-3 col-span-2 sm:col-span-1" :class="impactBgClass">
          <div class="text-xl font-bold font-mono" :class="impactTextClass">{{ impactDisplay }}</div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('weather.performance_impact') }}</div>
        </div>
      </div>

      <!-- Sunrise / Sunset bar -->
      <div v-if="weatherData.forecast.sunrise" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div class="flex items-center justify-between text-sm">
          <div class="flex items-center gap-2">
            <Icon name="sun" class="text-amber-500" />
            <div>
              <div class="font-mono font-semibold text-slate-900">{{ weatherData.forecast.sunrise }}</div>
              <div class="text-xs text-slate-400">{{ $t('weather.sunrise') }}</div>
            </div>
          </div>

          <!-- Daylight bar -->
          <div class="flex-1 mx-4 hidden sm:block">
            <div class="h-2 rounded-full bg-slate-200 overflow-hidden">
              <div
                class="h-full rounded-full bg-gradient-to-r from-amber-300 via-yellow-200 to-orange-300"
                :style="{ width: daylightBarWidth }"
              ></div>
            </div>
            <div class="text-center text-xs text-slate-500 mt-1">
              {{ weatherData.forecast.daylight_hours }} {{ $t('weather.hours') }}
            </div>
          </div>

          <div class="flex items-center gap-2">
            <div class="text-right">
              <div class="font-mono font-semibold text-slate-900">{{ weatherData.forecast.sunset }}</div>
              <div class="text-xs text-slate-400">{{ $t('weather.sunset') }}</div>
            </div>
            <Icon name="moon" class="text-orange-500" />
          </div>
        </div>
        <!-- Mobile daylight display -->
        <div class="sm:hidden text-center text-xs text-slate-500 mt-2">
          {{ weatherData.forecast.daylight_hours }} {{ $t('weather.hours') }} {{ $t('weather.daylight') }}
        </div>
      </div>

      <!-- Recent Weather section (premium) -->
      <div v-if="weatherData.recent_weather" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-sm font-semibold text-slate-700">
            {{ $t('weather.recent_title') }}
            <span v-if="weatherData.recent_weather.includes_forecast" class="text-xs font-normal text-blue-500 ml-1">{{ $t('weather.incl_forecast') }}</span>
          </h4>
          <span class="text-xs font-mono text-slate-500">
            {{ $t('weather.total') }}: {{ weatherData.recent_weather.total_precipitation_mm }} mm
          </span>
        </div>

        <!-- Precipitation bars -->
        <div class="flex items-end gap-2 h-12 mb-2">
          <div
            v-for="day in weatherData.recent_weather.days"
            :key="day.date"
            class="flex-1 flex flex-col items-center"
          >
            <div
              class="w-full rounded-t-sm"
              :class="[precipBarColor(day.precipitation_mm), day.is_forecast ? 'opacity-60 border border-dashed border-blue-400' : '']"
              :style="{ height: precipBarHeight(day.precipitation_mm) }"
            ></div>
          </div>
        </div>
        <div class="flex gap-2 mb-3">
          <div
            v-for="day in weatherData.recent_weather.days"
            :key="'label-' + day.date"
            class="flex-1 text-center"
          >
            <div class="text-[10px] text-slate-400 font-mono">{{ formatDayLabel(day.date) }}</div>
            <div class="text-[10px] text-slate-500">{{ day.precipitation_mm }}mm</div>
          </div>
        </div>

        <!-- Terrain impact warning -->
        <div
          class="text-sm px-3 py-2 rounded-lg"
          :class="terrainImpactClass"
        >
          {{ weatherData.recent_weather.terrain_impact }}
        </div>
      </div>

      <!-- Equipment Checklist -->
      <div v-if="equipment.length > 0" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <h4 class="text-sm font-semibold text-slate-700 mb-3">{{ $t('weather.equipment_title') }}</h4>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div
            v-for="item in equipment"
            :key="item.category"
            class="flex items-start gap-2 text-sm"
          >
            <Icon :name="item.icon" class="!w-4 !h-4 mt-0.5 text-slate-500" />
            <div>
              <span class="font-medium text-slate-700">{{ item.label }}:</span>
              <span class="text-slate-600 ml-1">{{ item.recommendation }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import Icon from './Icon.vue'
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../services/api'

const props = defineProps({
  gpxId: {
    type: Number,
    required: true,
  },
})

const { t } = useI18n()

const weatherData = ref(null)
const loading = ref(false)
const error = ref(false)

// Date bounds
const today = computed(() => {
  const d = new Date()
  return d.toISOString().split('T')[0]
})

const maxDate = computed(() => {
  const d = new Date()
  d.setDate(d.getDate() + 16)
  return d.toISOString().split('T')[0]
})

const selectedDate = ref(today.value)

// Fetch weather data
const fetchWeather = async () => {
  if (!props.gpxId) return

  loading.value = true
  error.value = false

  try {
    const response = await api.get('/weather/forecast', {
      params: {
        gpx_id: props.gpxId,
        date: selectedDate.value,
      },
    })
    weatherData.value = response.data
  } catch (e) {
    error.value = true
    weatherData.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchWeather)
watch(selectedDate, fetchWeather)

// Accuracy badge styling
const accuracyBadgeClass = computed(() => {
  if (!weatherData.value) return ''
  const level = weatherData.value.accuracy.level
  return {
    high: 'bg-emerald-100 text-emerald-800',
    moderate: 'bg-amber-100 text-amber-800',
    low: 'bg-red-100 text-red-800',
  }[level] || 'bg-slate-100 text-slate-800'
})

// Performance impact display
const impactDisplay = computed(() => {
  if (!weatherData.value) return ''
  const factor = weatherData.value.forecast.weather_factor
  const pct = ((factor - 1.0) * 100).toFixed(0)
  return pct > 0 ? `+${pct}%` : t('weather.no_impact')
})

const impactTextClass = computed(() => {
  if (!weatherData.value) return 'text-slate-900'
  const pct = (weatherData.value.forecast.weather_factor - 1.0) * 100
  if (pct > 10) return 'text-red-600'
  if (pct > 5) return 'text-amber-600'
  if (pct > 2) return 'text-amber-500'
  return 'text-emerald-600'
})

const impactBgClass = computed(() => {
  if (!weatherData.value) return 'bg-slate-50'
  const pct = (weatherData.value.forecast.weather_factor - 1.0) * 100
  if (pct > 10) return 'bg-red-50'
  if (pct > 5) return 'bg-amber-50'
  if (pct > 2) return 'bg-amber-50'
  return 'bg-emerald-50'
})

// Daylight bar width (normalized: 8h=50%, 16h=100%)
const daylightBarWidth = computed(() => {
  if (!weatherData.value?.forecast?.daylight_hours) return '0%'
  const hours = weatherData.value.forecast.daylight_hours
  const pct = Math.min(100, Math.max(0, (hours / 16) * 100))
  return `${pct}%`
})

// Recent weather helpers
const precipBarHeight = (mm) => {
  if (mm <= 0) return '2px'
  const maxH = 40  // max px height
  const scaled = Math.min(maxH, Math.sqrt(mm) * 10)
  return `${Math.max(2, scaled)}px`
}

const precipBarColor = (mm) => {
  if (mm >= 10) return 'bg-blue-500'
  if (mm >= 2) return 'bg-blue-400'
  if (mm > 0) return 'bg-blue-200'
  return 'bg-slate-200'
}

const formatDayLabel = (dateStr) => {
  try {
    const d = new Date(dateStr + 'T00:00:00')
    return d.toLocaleDateString(undefined, { weekday: 'short' })
  } catch {
    return dateStr.slice(-2)
  }
}

const terrainImpactClass = computed(() => {
  if (!weatherData.value?.recent_weather) return 'bg-slate-100 text-slate-600'
  const total = weatherData.value.recent_weather.total_precipitation_mm
  if (total >= 25) return 'bg-amber-100 text-amber-800'
  if (total >= 10) return 'bg-amber-50 text-amber-700'
  if (total >= 2) return 'bg-blue-50 text-blue-700'
  return 'bg-emerald-50 text-emerald-700'
})

// Equipment checklist - computed from weather data
const equipment = computed(() => {
  if (!weatherData.value) return []
  const forecast = weatherData.value.forecast
  const recent = weatherData.value.recent_weather
  const temp = forecast.temperature_c
  const wind = forecast.wind_speed_ms
  const precip = forecast.precipitation_mm
  const humidity = forecast.humidity_pct
  const recentPrecip = recent?.total_precipitation_mm || 0

  const items = []

  // Shoes
  if (recentPrecip >= 15 || precip >= 5) {
    items.push({ category: 'shoes', icon: 'footprints', label: t('weather.equip.shoes'), recommendation: t('weather.equip.shoes_waterproof') })
  } else if (recentPrecip >= 5) {
    items.push({ category: 'shoes', icon: 'footprints', label: t('weather.equip.shoes'), recommendation: t('weather.equip.shoes_grip') })
  } else {
    items.push({ category: 'shoes', icon: 'footprints', label: t('weather.equip.shoes'), recommendation: t('weather.equip.shoes_trail') })
  }

  // Clothing layers
  if (temp < 0) {
    items.push({ category: 'clothing', icon: 'shirt', label: t('weather.equip.clothing'), recommendation: t('weather.equip.clothing_thermal') })
  } else if (temp < 10) {
    items.push({ category: 'clothing', icon: 'shirt', label: t('weather.equip.clothing'), recommendation: t('weather.equip.clothing_layers') })
  } else if (temp < 18) {
    items.push({ category: 'clothing', icon: 'shirt', label: t('weather.equip.clothing'), recommendation: t('weather.equip.clothing_light') })
  } else {
    items.push({ category: 'clothing', icon: 'shirt', label: t('weather.equip.clothing'), recommendation: t('weather.equip.clothing_minimal') })
  }

  // Rain gear
  if (precip >= 5) {
    items.push({ category: 'rain', icon: 'umbrella', label: t('weather.equip.rain'), recommendation: t('weather.equip.rain_waterproof') })
  } else if (precip >= 0.5) {
    items.push({ category: 'rain', icon: 'umbrella', label: t('weather.equip.rain'), recommendation: t('weather.equip.rain_packable') })
  }

  // Headlamp (if daylight is limited)
  if (forecast.daylight_hours && forecast.daylight_hours < 10) {
    items.push({ category: 'headlamp', icon: 'flashlight', label: t('weather.equip.headlamp'), recommendation: t('weather.equip.headlamp_recommended') })
  }

  // Hydration
  const baseFluid = temp > 25 ? 750 : temp > 10 ? 500 : 400
  const fluidRate = humidity > 70 ? baseFluid + 100 : baseFluid
  items.push({ category: 'hydration', icon: 'droplet', label: t('weather.equip.hydration'), recommendation: t('weather.equip.hydration_rate', { rate: fluidRate }) })

  // Sun protection
  if (forecast.weathercode !== null && forecast.weathercode <= 2 && temp > 15) {
    items.push({ category: 'sun', icon: 'glasses', label: t('weather.equip.sun'), recommendation: t('weather.equip.sun_protect') })
  }

  // Wind protection
  if (wind > 8) {
    items.push({ category: 'wind', icon: 'wind', label: t('weather.equip.wind'), recommendation: t('weather.equip.wind_jacket') })
  }

  return items
})
</script>
