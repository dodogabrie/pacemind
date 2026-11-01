<template>
  <div class="space-y-8 w-full">
    <!-- Main Prediction Card -->
    <div class="hero-card">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-2xl font-bold text-white uppercase tracking-tight">{{ $t('results.title') }}</h3>
      </div>

      <div class="text-center py-4">
      <div class="text-5xl md:text-6xl font-bold mb-2 font-mono tracking-tight text-slate-900">
        {{ predictionStore.totalStopTimeSeconds > 0 ? predictionStore.adjustedTotalTimeFormatted : prediction.total_time_formatted }}
      </div>

        <!-- Moving + stops breakdown (stops = learned passive + aid stations + map annotations) -->
        <div v-if="prediction.moving_time_seconds != null" class="text-slate-500 text-xs font-mono mb-2">
          {{ $t('results.moving_plus_stops', { moving: formatTime(prediction.moving_time_seconds), stops: formatTime((prediction.stop_time_seconds || 0) + predictionStore.totalStopTimeSeconds) }) }}
        </div>
        <div v-else-if="predictionStore.totalStopTimeSeconds > 0" class="text-slate-500 text-xs font-mono mb-2">
          {{ prediction.total_time_formatted }} {{ $t('results.running_time') }} + {{ formatStopTime(predictionStore.totalStopTimeSeconds) }} {{ $t('results.stop_time') }}
        </div>

        <div class="text-slate-400 text-sm font-mono">
          {{ $t('results.confidence_interval') }}: <span class="text-emerald-300">{{ prediction.confidence_interval.lower_formatted }}</span> -
          <span class="text-emerald-300">{{ prediction.confidence_interval.upper_formatted }}</span>
        </div>

        <!-- Measured accuracy on the runner's own past runs -->
        <div v-if="prediction.metadata" class="mt-4 text-slate-500 text-xs max-w-lg mx-auto border-t border-slate-800 pt-3">
          {{ prediction.metadata.accuracy
            ? $t('results.accuracy', { n: prediction.metadata.accuracy.n, pct: prediction.metadata.accuracy.p80_pct })
            : $t('results.accuracy_unknown') }}
          <template v-if="prediction.metadata.personal_model">
            <br>{{ $t(prediction.metadata.personal_model.active ? 'results.habits_on' : 'results.habits_off') }}
          </template>
        </div>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-6 pt-6 border-t border-slate-200">
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 sm:px-4 py-3 min-w-0">
          <div class="text-xl sm:text-2xl font-bold font-mono text-emerald-600 leading-tight whitespace-nowrap truncate">{{ prediction.statistics.total_distance_km.toFixed(2) }}</div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('results.km') }}</div>
        </div>
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 sm:px-4 py-3 min-w-0">
          <div class="text-xl sm:text-2xl font-bold font-mono text-emerald-600 leading-tight whitespace-nowrap truncate">{{ Math.round(prediction.statistics.total_elevation_gain_m) }}</div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('results.m_gain') }}</div>
        </div>
        <div class="text-center rounded-xl border border-slate-200 bg-slate-50 px-3 sm:px-4 py-3 min-w-0 col-span-2 sm:col-span-1">
          <div class="text-xl sm:text-2xl font-bold font-mono text-emerald-600 leading-tight whitespace-nowrap truncate">{{ formatPace(prediction.statistics.flat_pace_min_per_km) }}</div>
          <div class="text-slate-500 text-xs uppercase tracking-wider">{{ $t('results.flat_pace') }}</div>
        </div>
      </div>
    </div>

    <!-- Map Visualization -->
    <div v-if="isMobile" class="flex justify-end">
      <button
        class="btn btn-outline text-xs min-h-[44px]"
        type="button"
        @click="showMap = !showMap"
      >
        {{ showMap ? $t('results.hide_map') : $t('results.show_map') }}
      </button>
    </div>
    <div v-if="!isMobile || showMap" class="card p-1 h-[320px] sm:h-[500px] relative overflow-hidden bg-slate-100">
      <MapView
        v-if="gpxStore.points.length"
        :points="gpxStore.points"
        :annotations="predictionStore.annotations"
        :suggested-annotations="predictionStore.suggestedAnnotations"
      />
      <div v-else class="flex items-center justify-center h-full text-slate-500">
        {{ $t('results.loading_map') }}
      </div>
    </div>

    <!-- Elevation & Pace Profile -->
    <div class="card p-4 sm:p-6">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h3 class="text-xl font-bold text-slate-900">{{ $t('results.elevation_pace_title') }}</h3>
          <p class="text-xs text-slate-500 uppercase tracking-wide mt-1">{{ $t('results.interactive_analysis') }}</p>
        </div>

        <!-- Split Level Control -->
        <div class="flex flex-col sm:flex-row sm:items-center gap-3 w-full sm:w-auto">
          <button v-if="isProfileZoomed" class="btn btn-outline text-xs py-1.5 w-full sm:w-auto" type="button" @click="resetProfileZoom">
            {{ $t('results.reset_zoom') }}
          </button>
          
          <div v-if="maxValidLevel > 1" class="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 w-full sm:w-auto">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">{{ $t('results.granularity') }}</span>
            <input
              v-model.number="localSplitLevel"
              @input="regroupSegments"
              type="range"
              min="1"
              :max="maxValidLevel"
              step="1"
              class="w-full sm:w-24 h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-emerald-600"
            />
            <span class="text-sm font-bold text-slate-700 font-mono w-4 text-center">{{ localSplitLevel }}</span>
          </div>
          <button
            v-if="prediction.prediction_id"
            @click="exportVirtualPartner"
            class="btn btn-primary text-xs w-full sm:w-auto"
          >
            <svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z"/><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z"/><path d="M16 17h4"/><path d="M4 13h4"/></svg> {{ $t('results.buttons.export_vp') }}
          </button>
        </div>
      </div>
      <div v-if="isMobile && Number.isFinite(pendingAnnotationDistance)" class="mb-4 flex items-center justify-between gap-3 rounded-lg border border-emerald-100 bg-emerald-50/80 px-3 py-2 text-xs text-emerald-900">
        <span class="font-semibold">{{ $t('results.add_annotation_at', { distance: pendingAnnotationDistance.toFixed(2) }) }}</span>
        <button class="btn btn-primary text-xs px-3 py-1.5" type="button" @click="openMobileAnnotation">
          <svg class="w-3.5 h-3.5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg> {{ $t('results.add_annotation') }}
        </button>
      </div>

      <ElevationPaceProfile
        ref="elevationProfileRef"
        v-if="gpxStore.points.length"
        :points="gpxStore.points"
        :segments="displaySegments"
        :raw-segments="rawSegments"
        :average-pace="prediction.statistics.flat_pace_min_per_km"
        :annotations="predictionStore.annotations"
        :selected-range="selectedRange"
        :tap-to-reveal="isMobile"
        :edit-label="$t('results.edit_annotation')"
        @click-chart="handleChartClick"
        @annotation-click="handleAnnotationClick"
        @range-selected="handleRangeSelected"
        @zoom-changed="handleZoomChanged"
      />
      <div v-else class="flex items-center justify-center h-[500px] text-slate-500">
        {{ $t('results.loading_profile') }}
      </div>
    </div>

    <!-- Similar Activities -->
    <div v-if="similarActivities.length > 0" class="card p-6">
      <h3 class="text-lg font-bold text-slate-900 mb-4 flex items-center gap-2">
         <span class="w-1.5 h-6 bg-sky-500 rounded-full"></span>
         {{ $t('results.similar_activities') }}
      </h3>

      <div class="grid sm:grid-cols-2 gap-4">
        <div
          v-for="activity in similarActivities"
          :key="activity.id"
          class="flex justify-between items-start rounded-xl border border-slate-100 bg-slate-50/50 p-4 hover:border-sky-200 hover:bg-sky-50 transition-colors cursor-default"
        >
          <div>
            <p class="font-bold text-slate-800 text-sm mb-1">{{ activity.name }}</p>
            <p class="text-xs text-slate-500 flex items-center gap-2">
              <span>{{ (activity.distance / 1000).toFixed(2) }} km</span>
              <span class="w-1 h-1 rounded-full bg-slate-300"></span>
              <span>{{ formatDate(activity.start_date) }}</span>
            </p>
          </div>
          <div class="text-right">
            <div class="font-bold font-mono text-slate-900">
              {{ formatTime(activity.moving_time) }}
            </div>
            <div class="text-[10px] uppercase tracking-wide text-slate-400">{{ $t('results.actual_time') }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Annotation Modal -->
    <AnnotationModal
      :show="showAnnotationModal"
      :distance-km="pendingAnnotationDistance"
      :predicted-time="pendingAnnotationPredictedTime"
      :cumulative-elevation="pendingAnnotationElevation"
      :anchor="annotationAnchor"
      :annotation="editingAnnotation"
      @close="closeAnnotationModal"
      @save="saveAnnotation"
      @delete="removeEditingAnnotation"
    />

  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useGpxStore } from '../stores/gpx'
import { usePredictionStore } from '../stores/prediction'
import { useI18n } from 'vue-i18n'
import { useIsMobile } from '../composables/useIsMobile'
import { formatPace, formatStopTime, formatTime, classifyTerrain } from '../utils/formatters'
import MapView from './MapView.vue'
import ElevationPaceProfile from './ElevationPaceProfile.vue'
import AnnotationModal from './AnnotationModal.vue'
import api from '../services/api'

const gpxStore = useGpxStore()
const predictionStore = usePredictionStore()
const { locale, t } = useI18n()

const props = defineProps({
  prediction: {
    type: Object,
    required: true
  },
  similarActivities: {
    type: Array,
    default: () => []
  },
  selectedActivity: {
    type: Object,
    default: null
  }
})

const emit = defineEmits([])

const localSplitLevel = ref(predictionStore.splitLevel)
const displaySegments = ref([])
const rawSegments = ref([])
const elevationProfileRef = ref(null)
const isProfileZoomed = ref(false)
const showAnnotationModal = ref(false)
const pendingAnnotationDistance = ref(null)
const pendingAnnotationPredictedTime = ref(null)
const pendingAnnotationElevation = computed(() => {
  return getCumulativeElevation(pendingAnnotationDistance.value)
})
const annotationAnchor = ref(null)
const selectedRange = ref(null)
const selectedRangeTime = ref(null)
const cachedSegmentsByLevel = ref({}) // Cache for all 5 levels
const maxValidLevel = ref(5) // Highest level that doesn't exceed MAX_SEGMENTS
const { isMobile } = useIsMobile()
const segmentTimeline = ref([])
const segmentEnds = ref([])
const editingAnnotation = ref(null)
const prevBodyOverflow = ref('')
const prevBodyPaddingRight = ref('')
const showMap = ref(true)

// Calculate cumulative D+ and D- at a given distance
const getCumulativeElevation = (distanceKm) => {
  if (!gpxStore.points || gpxStore.points.length < 2 || !Number.isFinite(distanceKm)) {
    return { dPlus: 0, dMinus: 0 }
  }

  const targetM = distanceKm * 1000
  const points = []

  for (let i = 1; i < gpxStore.points.length; i++) {
    const prev = gpxStore.points[i - 1]
    const curr = gpxStore.points[i]

    if (curr.distance >= targetM) {
      const segmentDistance = curr.distance - prev.distance
      const ratio = segmentDistance > 0 ? (targetM - prev.distance) / segmentDistance : 0
      const clampedRatio = Math.max(0, Math.min(1, ratio))
      const interpolatedElevation = prev.elevation + (curr.elevation - prev.elevation) * clampedRatio
      points.push(prev)
      points.push({ ...curr, distance: targetM, elevation: interpolatedElevation })
      break
    }

    points.push(prev)
  }

  if (points.length < 2) {
    return { dPlus: 0, dMinus: 0 }
  }

  const elevations = points.map((p) => p.elevation)
  const windowSize = Math.min(5, elevations.length)
  const halfWindow = Math.floor(windowSize / 2)
  const smoothed = elevations.map((_, idx) => {
    let sum = 0
    let count = 0
    const start = Math.max(0, idx - halfWindow)
    const end = Math.min(elevations.length - 1, idx + halfWindow)
    for (let i = start; i <= end; i++) {
      sum += elevations[i]
      count += 1
    }
    return count > 0 ? sum / count : elevations[idx]
  })

  const threshold = 1.0
  let dPlus = 0
  let dMinus = 0
  for (let i = 1; i < smoothed.length; i++) {
    const delta = smoothed[i] - smoothed[i - 1]
    if (delta > threshold) {
      dPlus += delta
    } else if (delta < -threshold) {
      dMinus += Math.abs(delta)
    }
  }

  return {
    dPlus: Math.round(dPlus),
    dMinus: Math.round(dMinus)
  }
}

// Group segments by gradient changes
const getSplitGrade = (segment) => {
  if (typeof segment._smoothed_grade === 'number') return segment._smoothed_grade
  return segment.grade
}

const smoothSegmentGrades = (segments, windowMeters) => {
  if (!segments || segments.length === 0) return []

  const halfWindow = windowMeters / 2
  const centers = segments.map(seg => seg.distance_m + seg.length_m / 2)

  return segments.map((seg, index) => {
    const center = centers[index]
    const windowStart = center - halfWindow
    const windowEnd = center + halfWindow

    let weightedSum = 0
    let weightTotal = 0

    for (let i = 0; i < segments.length; i++) {
      const segCenter = centers[i]
      if (segCenter < windowStart || segCenter > windowEnd) continue

      const weight = segments[i].length_m || 0
      weightedSum += (segments[i].grade * weight)
      weightTotal += weight
    }

    const smoothedGrade = weightTotal > 0 ? weightedSum / weightTotal : seg.grade

    return {
      ...seg,
      _smoothed_grade: smoothedGrade
    }
  })
}

const groupSegmentsByGradient = (segments, gradientThreshold, maxSegmentLength, signChangeMinGrade) => {
  if (!segments || segments.length === 0) return []

  // Step 1: Split by terrain type (uphill/flat/downhill) - these are mandatory splits
  const FLAT_THRESHOLD = 2.0 // grades between -2% and +2% are considered flat

  const getTerrainType = (grade) => {
    const g = grade * 100
    if (g > FLAT_THRESHOLD) return 'up'
    if (g < -FLAT_THRESHOLD) return 'down'
    return 'flat'
  }

  // First pass: split by terrain type changes
  const terrainSections = []
  let currentSection = [segments[0]]
  let currentTerrain = getTerrainType(getSplitGrade(segments[0]))

  for (let i = 1; i < segments.length; i++) {
    const curr = segments[i]
    const currTerrain = getTerrainType(getSplitGrade(curr))

    if (currTerrain !== currentTerrain) {
      terrainSections.push({ segments: currentSection, terrain: currentTerrain })
      currentSection = [curr]
      currentTerrain = currTerrain
    } else {
      currentSection.push(curr)
    }
  }
  if (currentSection.length > 0) {
    terrainSections.push({ segments: currentSection, terrain: currentTerrain })
  }

  // Step 2: Within each terrain section, apply max length and grade threshold
  const grouped = []

  for (const section of terrainSections) {
    const sectionSegments = section.segments
    if (sectionSegments.length === 0) continue

    let currentGroup = [sectionSegments[0]]
    let currentStart = sectionSegments[0].distance_m

    for (let i = 1; i < sectionSegments.length; i++) {
      const prev = sectionSegments[i - 1]
      const curr = sectionSegments[i]

      const prevGrade = getSplitGrade(prev) * 100
      const currGrade = getSplitGrade(curr) * 100
      const gradeChange = Math.abs(currGrade - prevGrade)
      const currentLength = curr.distance_m - currentStart

      // Within same terrain type, only split by grade change or max length
      let effectiveThreshold = gradientThreshold

      // Be less sensitive within uphills (they naturally vary more)
      if (section.terrain === 'up') {
        effectiveThreshold = gradientThreshold * 1.5
      }
      // Be moderately sensitive within downhills
      else if (section.terrain === 'down') {
        effectiveThreshold = gradientThreshold * 1.2
      }

      if (gradeChange > effectiveThreshold || currentLength > maxSegmentLength) {
        grouped.push(currentGroup)
        currentGroup = [curr]
        currentStart = curr.distance_m
      } else {
        currentGroup.push(curr)
      }
    }

    if (currentGroup.length > 0) {
      grouped.push(currentGroup)
    }
  }

  return grouped
}

// Format grouped segments for display
const formatGroupedSegments = (segmentGroups) => {
  const mlSegments = []
  let cumulativeTime = 0

  segmentGroups.forEach((group, index) => {
    const groupTime = group.reduce((sum, s) => sum + s.time_s, 0)
    const groupDist = group.reduce((sum, s) => sum + s.length_m, 0)
    const avgGrade = group.reduce((sum, s) => sum + s.grade, 0) / group.length
    const avgPace = groupTime / (groupDist / 1000) / 60

    cumulativeTime += groupTime
    const startKm = group[0].distance_m / 1000
    const endKm = (group[group.length - 1].distance_m + group[group.length - 1].length_m) / 1000

    const hours = Math.floor(cumulativeTime / 3600)
    const mins = Math.floor((cumulativeTime % 3600) / 60)
    const secs = Math.floor(cumulativeTime % 60)

    const terrain = classifyTerrain(avgGrade)

    mlSegments.push({
      split_number: index + 1,
      segment_km: Math.floor(endKm),
      start_km: parseFloat(startKm.toFixed(2)),
      end_km: parseFloat(endKm.toFixed(2)),
      avg_grade_percent: parseFloat((avgGrade * 100).toFixed(1)),
      avg_pace_min_per_km: parseFloat(avgPace.toFixed(2)),
      time_formatted: `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`,
      terrain: terrain,
      distance_m: parseFloat(groupDist.toFixed(1))
    })
  })

  return mlSegments
}

// Thresholds configuration
// Note: signChange is no longer used (terrain splits are now mandatory)
// maxLength only applies within a continuous terrain section
const thresholds = {
  1: { gradient: 20.0, signChange: 20.0, maxLength: 30000, smoothWindow: 800 }, // Very coarse
  2: { gradient: 12.0, signChange: 12.0, maxLength: 20000, smoothWindow: 500 },  // Coarse
  3: { gradient: 8.0, signChange: 6.0, maxLength: 15000, smoothWindow: 300 },    // Medium
  4: { gradient: 5.0, signChange: 3.0, maxLength: 8000, smoothWindow: 200 },     // Fine
  5: { gradient: 2.0, signChange: 1.0, maxLength: 4000, smoothWindow: 150 }      // Very fine
}

const MAX_SEGMENTS = 200

// Compute segments for a specific level
const computeSegmentsForLevel = (rawSegmentsData, level) => {
  const config = thresholds[level] || thresholds[3]
  const smoothedSegments = smoothSegmentGrades(rawSegmentsData, config.smoothWindow)
  const segmentGroups = groupSegmentsByGradient(
    smoothedSegments,
    config.gradient,
    config.maxLength,
    config.signChange
  )
  return formatGroupedSegments(segmentGroups)
}

// Precompute all levels and cache them
const precomputeAllLevels = () => {
  const rawSegmentsData = props.prediction.raw_segments
  if (!rawSegmentsData || rawSegmentsData.length === 0) {
    displaySegments.value = props.prediction.segments
    rawSegments.value = []
    return
  }

  rawSegments.value = rawSegmentsData

  // Compute all 5 levels and track max valid level
  let highestValid = 1
  for (let level = 1; level <= 5; level++) {
    const segments = computeSegmentsForLevel(rawSegmentsData, level)
    cachedSegmentsByLevel.value[level] = segments
    if (segments.length <= MAX_SEGMENTS) {
      highestValid = level
    }
  }

  maxValidLevel.value = highestValid

  // Clamp initial level to max valid
  if (localSplitLevel.value > maxValidLevel.value) {
    localSplitLevel.value = maxValidLevel.value
  }

  // Set initial display
  regroupSegments()
}

// Regroup segments based on split level (now just switches cached versions)
const regroupSegments = () => {
  const rawSegmentsData = props.prediction.raw_segments
  if (!rawSegmentsData || rawSegmentsData.length === 0) {
    displaySegments.value = props.prediction.segments
    return
  }

  // Simply use cached segments for current level (already validated to be <= MAX_SEGMENTS)
  const cached = cachedSegmentsByLevel.value[localSplitLevel.value]
  if (cached) {
    displaySegments.value = cached
  } else {
    // Fallback to level 1
    displaySegments.value = cachedSegmentsByLevel.value[1] || []
  }
}

const resetProfileZoom = () => {
  elevationProfileRef.value?.resetZoom()
  elevationProfileRef.value?.clearClickMarker()
  isProfileZoomed.value = false
}

const handleZoomChanged = (isZoomed) => {
  isProfileZoomed.value = isZoomed
  elevationProfileRef.value?.clearClickMarker()
}

const formatSecondsToHms = (totalTime) => {
  const h = Math.floor(totalTime / 3600)
  const m = Math.floor((totalTime % 3600) / 60)
  const s = Math.floor(totalTime % 60)
  return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

const buildSegmentTimeline = (segments) => {
  const fallbackPace = props.prediction?.statistics?.flat_pace_min_per_km
  const ordered = [...(segments || [])].sort((a, b) => {
    const aStart = a.start_km ?? 0
    const bStart = b.start_km ?? 0
    return aStart - bStart
  })
  const timeline = []
  let cumTime = 0

  ordered.forEach(seg => {
    const startKm = seg.start_km ?? 0
    const endKm = seg.end_km ?? seg.segment_km ?? 0
    if (!Number.isFinite(startKm) || !Number.isFinite(endKm) || endKm <= startKm) {
      return
    }
    const pace = Number.isFinite(seg.avg_pace_min_per_km)
      ? seg.avg_pace_min_per_km
      : (Number.isFinite(fallbackPace) ? fallbackPace : null)
    if (!Number.isFinite(pace)) return

    const segTime = pace * (endKm - startKm) * 60
    const entry = {
      startKm,
      endKm,
      pace,
      cumTimeStart: cumTime,
      cumTimeEnd: cumTime + segTime
    }
    cumTime = entry.cumTimeEnd
    timeline.push(entry)
  })

  segmentTimeline.value = timeline
  segmentEnds.value = timeline.map(seg => seg.endKm)
}

const handleChartClick = ({ distanceKm, screenX, screenY }) => {
  editingAnnotation.value = null
  pendingAnnotationDistance.value = distanceKm
  pendingAnnotationPredictedTime.value = calculateTimeToDistance(distanceKm)
  annotationAnchor.value = Number.isFinite(screenX) && Number.isFinite(screenY)
    ? { x: screenX, y: screenY }
    : null
  if (isMobile.value) {
    return
  }
  elevationProfileRef.value?.hideTooltip()
  showAnnotationModal.value = true
}

const openMobileAnnotation = () => {
  if (!Number.isFinite(pendingAnnotationDistance.value)) return
  elevationProfileRef.value?.hideTooltip()
  showAnnotationModal.value = true
}

const handleAnnotationClick = ({ annotation, screenX, screenY }) => {
  if (!annotation) return
  editingAnnotation.value = annotation
  pendingAnnotationDistance.value = annotation.distance_km
  pendingAnnotationPredictedTime.value = calculateTimeToDistance(annotation.distance_km)
  annotationAnchor.value = Number.isFinite(screenX) && Number.isFinite(screenY)
    ? { x: screenX, y: screenY }
    : null
  elevationProfileRef.value?.hideTooltip()
  showAnnotationModal.value = true
}

const closeAnnotationModal = () => {
  showAnnotationModal.value = false
  elevationProfileRef.value?.clearClickMarker()
  editingAnnotation.value = null
}

const calculateTimeToDistance = (targetKm) => {
  if (!Number.isFinite(targetKm) || segmentTimeline.value.length === 0) {
    return formatSecondsToHms(0)
  }

  let low = 0
  let high = segmentEnds.value.length - 1
  let idx = segmentEnds.value.length - 1

  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    if (targetKm <= segmentEnds.value[mid]) {
      idx = mid
      high = mid - 1
    } else {
      low = mid + 1
    }
  }

  const seg = segmentTimeline.value[idx]
  if (!seg) return formatSecondsToHms(0)
  if (targetKm <= seg.startKm) {
    return formatSecondsToHms(seg.cumTimeStart)
  }

  const partialDist = Math.max(0, targetKm - seg.startKm)
  const totalTime = seg.cumTimeStart + (seg.pace * partialDist * 60)
  return formatSecondsToHms(totalTime)
}

const handleRangeSelected = (range) => {
  selectedRange.value = range
  if (range) {
    selectedRangeTime.value = calculateRangeTime(range.start_km, range.end_km)
  } else {
    selectedRangeTime.value = null
  }
}

const calculateRangeTime = (startKm, endKm) => {
  if (segmentTimeline.value.length === 0) {
    return formatSecondsToHms(0)
  }

  let totalTime = 0
  let low = 0
  let high = segmentEnds.value.length - 1
  let idx = segmentEnds.value.length - 1

  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    if (startKm <= segmentEnds.value[mid]) {
      idx = mid
      high = mid - 1
    } else {
      low = mid + 1
    }
  }

  for (let i = idx; i < segmentTimeline.value.length; i++) {
    const seg = segmentTimeline.value[i]
    if (seg.startKm >= endKm) break

    if (seg.endKm > startKm && seg.startKm < endKm) {
      const overlapStart = Math.max(seg.startKm, startKm)
      const overlapEnd = Math.min(seg.endKm, endKm)
      const overlapDist = overlapEnd - overlapStart
      if (overlapDist > 0) {
        totalTime += seg.pace * overlapDist * 60
      }
    }
  }

  return formatSecondsToHms(totalTime)
}

const saveAnnotation = (annotation) => {
  const targetDist = pendingAnnotationDistance.value * 1000
  let closest = null
  let minDiff = Infinity

  for (const point of gpxStore.points) {
    const diff = Math.abs(point.distance - targetDist)
    if (diff < minDiff) {
      minDiff = diff
      closest = point
    }
  }

  if (!closest) return

  if (editingAnnotation.value) {
    predictionStore.updateAnnotation(editingAnnotation.value.id, {
      ...annotation,
      distance_km: editingAnnotation.value.distance_km,
      lat: editingAnnotation.value.lat,
      lon: editingAnnotation.value.lon
    })
  } else {
    predictionStore.addAnnotation({
      ...annotation,
      lat: closest.lat,
      lon: closest.lon
    })
  }
}

const removeEditingAnnotation = () => {
  if (!editingAnnotation.value) return
  predictionStore.removeAnnotation(editingAnnotation.value.id)
  closeAnnotationModal()
}

const saveAnnotationsToServer = async () => {
  if (!props.prediction.prediction_id) return
  try {
    await predictionStore.saveAnnotations(props.prediction.prediction_id)
    alert(t('results.annotations_saved'))
  } catch (error) {
    alert(t('results.annotations_save_failed'))
  }
}

onMounted(() => {
  precomputeAllLevels()

  if (props.prediction.prediction_id) {
    predictionStore.loadAnnotations(props.prediction.prediction_id)
  }
})

watch(displaySegments, (segments) => {
  buildSegmentTimeline(segments)
}, { immediate: true })

watch(showAnnotationModal, (isOpen) => {
  if (typeof document === 'undefined') return
  if (isOpen) {
    prevBodyOverflow.value = document.body.style.overflow
    prevBodyPaddingRight.value = document.body.style.paddingRight
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth
    document.body.style.overflow = 'hidden'
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`
    }
  } else {
    document.body.style.overflow = prevBodyOverflow.value || ''
    document.body.style.paddingRight = prevBodyPaddingRight.value || ''
  }
})

const getGradeColor = (grade) => {
  if (grade > 5) return 'text-red-600 font-semibold'
  if (grade > 2) return 'text-orange-600'
  if (grade < -5) return 'text-green-600 font-semibold'
  if (grade < -2) return 'text-green-500'
  return 'text-gray-700'
}


const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString(locale.value, { month: 'short', day: 'numeric', year: 'numeric' })
}

const exportVirtualPartner = async () => {
  if (!props.prediction.prediction_id) return
  
  try {
    if (predictionStore.annotationsDirty) {
      await predictionStore.saveAnnotations(props.prediction.prediction_id)
    }

    const response = await api.get(`/prediction/${props.prediction.prediction_id}/export`, {
      responseType: 'blob'
    })
    
    const blob = new Blob([response.data], { type: 'application/gpx+xml' })
    const downloadUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = downloadUrl
    const filename = `virtual_partner_${props.prediction.prediction_id}.gpx`
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    
  } catch (error) {
    console.error('Failed to export GPX:', error)
    alert(t('results.export_failed'))
  }
}

const formatTier = (tier) => {
  return t(`prediction.tiers.${tier}`) || tier
}

</script>
