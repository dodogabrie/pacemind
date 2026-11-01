<template>
  <div v-if="show" class="fixed inset-0 z-[9999] pointer-events-none">
    <div
      class="card w-full max-w-[320px] pointer-events-auto max-h-[90vh] overflow-y-auto shadow-2xl shadow-slate-900/10 border border-slate-200"
      :style="modalStyle"
    >
      <div class="flex items-center justify-between mb-3">
        <div>
          <h3 class="text-base font-bold text-slate-900">{{ isEditing ? $t('annotations.edit_title') : $t('annotations.add_title') }}</h3>
          <p class="text-[10px] text-slate-500 uppercase tracking-[0.2em]">{{ $t('annotations.subtitle') }}</p>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="isEditing"
            @click="$emit('delete')"
            class="btn btn-ghost text-base leading-none text-rose-600 hover:text-rose-700"
            :title="$t('common.buttons.delete')" :aria-label="$t('common.buttons.delete')"
          >
            <svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>
          </button>
          <button @click="$emit('close')" class="btn btn-ghost text-xl leading-none" :aria-label="$t('common.buttons.close')">&times;</button>
        </div>
      </div>

      <div class="mb-3">
        <label class="block text-[10px] font-semibold uppercase tracking-[0.2em] mb-1 text-slate-500">{{ $t('annotations.location') }}</label>
        <div class="flex items-baseline gap-3">
          <p class="text-slate-900 font-mono font-bold text-base">{{ displayDistance().toFixed(2) }} km</p>
          <span class="text-xs text-slate-500 font-mono">
            <span class="text-emerald-600">+{{ cumulativeElevation?.dPlus || 0 }}m</span>
            <span class="mx-1">/</span>
            <span class="text-rose-500">-{{ cumulativeElevation?.dMinus || 0 }}m</span>
          </span>
        </div>
      </div>

      <div v-if="predictedTime" class="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
        <label class="block text-[10px] font-semibold uppercase tracking-[0.2em] mb-1 text-emerald-700">
          {{ $t('annotations.eta') }}
        </label>
        <p class="text-emerald-900 font-mono font-bold text-base">{{ formatPredictedTime(predictedTime) }}</p>
      </div>

      <div class="mb-3">
        <label class="block text-[10px] font-semibold uppercase tracking-[0.2em] mb-2 text-slate-500">{{ $t('annotations.type') }}</label>
        <div class="flex flex-wrap gap-2">
          <label class="flex items-center gap-2 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 cursor-pointer transition-colors">
            <input type="radio" v-model="annotationType" value="aid_station" class="accent-emerald-600">
            <span>{{ $t('annotations.types.aid_station') }}</span>
          </label>
          <label class="flex items-center gap-2 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 cursor-pointer transition-colors">
            <input type="radio" v-model="annotationType" value="water" class="accent-blue-500">
            <span>{{ $t('annotations.types.water') }}</span>
          </label>
          <label class="flex items-center gap-2 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 cursor-pointer transition-colors">
            <input type="radio" v-model="annotationType" value="checkpoint" class="accent-amber-500">
            <span>{{ $t('annotations.types.checkpoint') }}</span>
          </label>
          <label class="flex items-center gap-2 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 cursor-pointer transition-colors">
            <input type="radio" v-model="annotationType" value="caution" class="accent-red-500">
            <span>{{ $t('annotations.types.caution') }}</span>
          </label>
          <label class="flex items-center gap-2 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 cursor-pointer transition-colors">
            <input type="radio" v-model="annotationType" value="generic" class="accent-purple-500">
            <span>{{ $t('annotations.types.generic') }}</span>
          </label>
        </div>
      </div>

      <button
        type="button"
        class="w-full btn btn-outline text-xs py-1.5 mb-3"
        @click="expanded = !expanded"
      >
        {{ expanded ? $t('annotations.hide_details') : $t('annotations.add_details') }}
      </button>

      <div v-if="expanded" class="mb-3 space-y-3">
        <div>
          <label class="block text-[10px] font-semibold uppercase tracking-[0.2em] mb-2 text-slate-500">{{ $t('annotations.label') }}</label>
          <input
            v-model="label"
            type="text"
            class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors text-sm"
            :placeholder="$t('annotations.label_placeholder')"
          >
          <p class="text-[10px] text-slate-500 mt-1">{{ $t('annotations.label_hint') }}</p>
        </div>
        <div>
          <label class="block text-[10px] font-semibold uppercase tracking-[0.2em] mb-2 text-slate-500">{{ $t('annotations.stop_time') }}</label>
          <div class="flex items-center gap-2">
            <input
              v-model.number="stopTimeSeconds"
              type="number"
              min="0"
              step="10"
              class="w-24 rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors text-sm font-mono"
            >
            <span class="text-sm text-slate-500">{{ $t('annotations.seconds') }}</span>
          </div>
          <p class="text-[10px] text-slate-500 mt-1">{{ $t('annotations.stop_hint') }}</p>
        </div>
      </div>

      <div class="flex gap-2 justify-end mt-4">
        <button @click="$emit('close')" class="btn btn-outline">
          {{ $t('common.buttons.cancel') }}
        </button>
        <button @click="save" class="btn btn-primary">
          {{ isEditing ? $t('common.buttons.save') : $t('annotations.add_title') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  show: Boolean,
  distanceKm: Number,
  predictedTime: String,
  cumulativeElevation: {
    type: Object,
    default: () => ({ dPlus: 0, dMinus: 0 })
  },
  anchor: {
    type: Object,
    default: null
  },
  annotation: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close', 'save', 'delete'])

const annotationType = ref('aid_station')
const label = ref('')
const stopTimeSeconds = ref(30)
const expanded = ref(false)
const isEditing = computed(() => !!props.annotation?.id)
const displayDistance = () => (Number.isFinite(props.distanceKm) ? props.distanceKm : 0)
const formatPredictedTime = (timeStr) => {
  if (!timeStr) return ''
  const parts = timeStr.split(':')
  if (parts.length >= 2) {
    return `${parts[0]}:${parts[1]}`
  }
  return timeStr
}

const TYPE_ABBREV = {
  aid_station: 'AS',
  water: 'W',
  checkpoint: 'CP',
  caution: '!',
  generic: 'G',
}

const TYPE_DEFAULT_STOP = {
  aid_station: 60,
  water: 30,
  checkpoint: 0,
  caution: 0,
  generic: 0,
}

const getDefaultLabel = (type) => {
  const time = formatPredictedTime(props.predictedTime)
  const abbrev = TYPE_ABBREV[type] || 'G'
  if (!time) return abbrev
  return `${time} - ${abbrev}`
}

const modalStyle = computed(() => {
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1024
  const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 768
  const padding = 16
  const modalWidth = 360
  const modalHeight = 400
  const gap = 32 // Gap between click point and modal

  // Phones: no room beside the anchor (modalWidth alone is ~the viewport), so centre it.
  if (viewportWidth < 640) {
    return {
      position: 'fixed',
      left: '50%',
      top: '50%',
      width: `calc(100vw - ${padding * 2}px)`,
      transform: 'translate(-50%, -50%)'
    }
  }

  if (!props.anchor || !Number.isFinite(props.anchor.x) || !Number.isFinite(props.anchor.y)) {
    return {
      position: 'fixed',
      right: `${padding}px`,
      top: '50%',
      transform: 'translateY(-50%)'
    }
  }

  const anchorX = props.anchor.x
  const anchorY = props.anchor.y
  const clickedOnRightSide = anchorX > viewportWidth / 2

  // Position modal next to click point, on opposite side to not cover marker
  const style = {
    position: 'fixed',
    top: '50%',
    transform: 'translateY(-50%)'
  }

  if (clickedOnRightSide) {
    // Click on right -> modal to the left of click point
    const left = Math.max(padding, anchorX - modalWidth - gap)
    style.left = `${left}px`
  } else {
    // Click on left -> modal to the right of click point
    const left = Math.min(viewportWidth - modalWidth - padding, anchorX + gap)
    style.left = `${left}px`
  }

  return style
})

watch(() => props.show, (show) => {
  if (show) {
    expanded.value = false
    if (isEditing.value) {
      annotationType.value = props.annotation.type || 'aid_station'
      label.value = props.annotation.label || ''
      stopTimeSeconds.value = props.annotation.stop_time_seconds ?? 30
    } else {
      annotationType.value = 'aid_station'
      label.value = getDefaultLabel('aid_station')
      stopTimeSeconds.value = TYPE_DEFAULT_STOP['aid_station']
    }
  }
})

watch(annotationType, (newType) => {
  if (isEditing.value) return
  label.value = getDefaultLabel(newType)
  stopTimeSeconds.value = TYPE_DEFAULT_STOP[newType] ?? 0
})

const save = () => {
  if (!label.value.trim()) {
    alert(t('annotations.label_required'))
    return
  }

  const annotation = {
    type: annotationType.value,
    distance_km: props.distanceKm,
    label: label.value.trim(),
    stop_time_seconds: Math.max(0, stopTimeSeconds.value || 0)
  }

  emit('save', annotation)
  emit('close')
}
</script>
