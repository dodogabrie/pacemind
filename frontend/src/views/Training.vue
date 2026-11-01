<template>
  <div class="stack">
    <AuthGate v-if="authStore.authChecked && !authStore.isAuthenticated" />
    <template v-else>
    <div>
      <h1 class="section-title">{{ $t('trainingCenter.title') }}</h1>
      <p class="section-subtitle">{{ $t('trainingCenter.subtitle') }}</p>
    </div>

    <!-- Connected accounts (settings live here until there's a Settings view) -->
    <ConnectionsPanel />

    <!-- Races: detected candidates to confirm, marked races, prompt if none recent -->
    <RacesCard />

    <!-- Tier Status Card -->
    <div class="card stack">
      <div class="flex flex-wrap justify-between items-center gap-3 mb-4">
        <h2 class="text-2xl font-bold">{{ $t('trainingCenter.status_title') }}</h2>
        <button
          v-if="tierStatus && tierStatus.activity_count >= 5"
          @click="retrainModel"
          :disabled="retraining"
          class="btn btn-dark disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg :class="{ 'animate-spin': retraining }" class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
          {{ retraining ? $t('trainingCenter.retraining') : $t('trainingCenter.retrain') }}
        </button>
      </div>

      <div v-if="tierStatus" class="space-y-6">
        <!-- Current Tier Badge -->
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-600">{{ $t('trainingCenter.current_tier') }}</span>
            <h3 class="text-xl font-bold text-slate-900">{{ formatTier(tierStatus.current_tier) }}</h3>
            <p class="text-sm text-slate-600 mt-1">{{ tierStatus.accuracy ? $t('results.accuracy', { n: tierStatus.accuracy.n, pct: tierStatus.accuracy.p80_pct }) : $t('results.accuracy_unknown') }}</p>
          </div>
          <div class="text-right">
            <span class="text-sm text-slate-600">{{ $t('trainingCenter.activities_downloaded') }}</span>
            <p class="text-3xl font-bold">{{ tierStatus.activity_count }}</p>
          </div>
        </div>

        <p v-if="tierStatus.personal_model" class="text-sm text-slate-600">{{ personalText(tierStatus.personal_model) }}</p>

        <!-- Progress Bar -->
        <div v-if="tierStatus.next_tier" class="space-y-2">
          <div class="flex justify-between text-sm text-slate-600">
            <span>{{ $t('trainingCenter.progress_to', { tier: formatTier(tierStatus.next_tier) }) }}</span>
            <span>{{ $t('trainingCenter.more_needed', { n: tierStatus.activities_needed_for_next_tier }) }}</span>
          </div>
          <div class="w-full bg-slate-200 rounded-full h-4">
            <div
              class="h-4 rounded-full transition-all duration-500"
              style="background: linear-gradient(120deg, #bef264 0%, #4ade80 45%, #38bdf8 100%);"
              :style="{ width: tierStatus.progress_to_next_tier_pct + '%' }"
            ></div>
          </div>
        </div>

        <!-- Tier Benefits -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-4 mt-6">
          <div class="border rounded-xl p-3 sm:p-4" :class="tierStatus.activity_count >= 0 ? 'border-lime-300 bg-lime-50' : 'border-slate-300'">
            <div class="flex items-center gap-3 sm:block sm:text-center">
              <div class="shrink-0 sm:mb-2 flex sm:justify-center"><svg class="w-6 h-6" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18h8"/><path d="M3 22h18"/><path d="M14 22a7 7 0 1 0 0-14h-1"/><path d="M9 14h2"/><path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/><path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/></svg></div>
              <div>
                <h4 class="font-bold text-sm">{{ $t('trainingCenter.tier1.name') }}</h4>
                <p class="text-xs text-slate-600 mt-1">{{ $t('trainingCenter.tier_min', { n: 0 }) }}</p>
                <p class="text-xs mt-1 sm:mt-2">{{ $t('trainingCenter.tier1.desc') }}</p>
              </div>
            </div>
          </div>
          <div class="border rounded-xl p-3 sm:p-4" :class="tierStatus.activity_count >= 5 ? 'border-lime-300 bg-lime-50' : 'border-slate-300'">
            <div class="flex items-center gap-3 sm:block sm:text-center">
              <div class="shrink-0 sm:mb-2 flex sm:justify-center"><svg class="w-6 h-6" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg></div>
              <div>
                <h4 class="font-bold text-sm">{{ $t('trainingCenter.tier2.name') }}</h4>
                <p class="text-xs text-slate-600 mt-1">{{ $t('trainingCenter.tier_min', { n: 5 }) }}</p>
                <p class="text-xs mt-1 sm:mt-2">{{ $t('trainingCenter.tier2.desc') }}</p>
              </div>
            </div>
          </div>
          <div class="border rounded-xl p-3 sm:p-4" :class="tierStatus.personal_model?.active ? 'border-lime-300 bg-lime-50' : 'border-slate-300'">
            <div class="flex items-center gap-3 sm:block sm:text-center">
              <div class="shrink-0 sm:mb-2 flex sm:justify-center"><svg class="w-6 h-6" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg></div>
              <div>
                <h4 class="font-bold text-sm">{{ $t('trainingCenter.tier3.name') }}</h4>
                <p class="text-xs text-slate-600 mt-1">{{ $t('trainingCenter.tier_min', { n: 30 }) }}</p>
                <p class="text-xs mt-1 sm:mt-2">{{ $t('trainingCenter.tier3.desc') }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="text-center py-8">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-900 mx-auto"></div>
        <p class="text-slate-600 mt-4">{{ $t('trainingCenter.loading_tier') }}</p>
      </div>
    </div>

    <!-- Training Activities Management -->
    <div class="card stack">
      <h2 class="text-2xl font-bold mb-4">{{ $t('trainingCenter.activities_title') }}</h2>

      <div v-if="loadingTrainingActivities" class="text-center py-8">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-900 mx-auto"></div>
        <p class="text-slate-600 mt-4">{{ $t('trainingCenter.loading_activities') }}</p>
      </div>

      <div v-else-if="trainingActivities.length === 0" class="text-center py-8">
        <p class="text-slate-600">{{ $t('trainingCenter.no_activities') }}</p>
      </div>

      <div v-else class="space-y-4">
        <!-- Summary Stats -->
        <div class="grid grid-cols-3 gap-2 sm:gap-4 mb-4">
          <div class="rounded-xl border border-emerald-200 bg-emerald-50 p-3 sm:p-4">
            <div class="text-xs sm:text-sm text-slate-600">{{ $t('trainingCenter.included_in_training') }}</div>
            <div class="text-2xl sm:text-3xl font-bold text-emerald-700">{{ trainingActivityStats.included_count }}</div>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 p-3 sm:p-4">
            <div class="text-xs sm:text-sm text-slate-600">{{ $t('trainingCenter.excluded') }}</div>
            <div class="text-2xl sm:text-3xl font-bold text-slate-700">{{ trainingActivityStats.excluded_count }}</div>
          </div>
          <div class="rounded-xl border border-sky-200 bg-sky-50 p-3 sm:p-4">
            <div class="text-xs sm:text-sm text-slate-600">{{ $t('trainingCenter.total_downloaded') }}</div>
            <div class="text-2xl sm:text-3xl font-bold text-slate-900">{{ trainingActivityStats.total }}</div>
          </div>
        </div>

        <!-- Activities List -->
        <div class="max-h-96 overflow-y-auto border rounded-lg">
          <table class="w-full">
            <thead class="bg-slate-50 sticky top-0">
              <tr>
                <th class="px-2 sm:px-4 py-2 text-left">{{ $t('trainingCenter.col.date') }}</th>
                <th class="hidden sm:table-cell px-4 py-2 text-left">{{ $t('trainingCenter.col.type') }}</th>
                <th class="px-2 sm:px-4 py-2 text-right">{{ $t('trainingCenter.col.distance') }}</th>
                <th class="hidden sm:table-cell px-4 py-2 text-right">D+</th>
                <th class="hidden sm:table-cell px-4 py-2 text-right">{{ $t('trainingCenter.col.segments') }}</th>
                <th class="hidden sm:table-cell px-4 py-2 text-center">{{ $t('trainingCenter.col.weight') }}</th>
                <th class="px-2 sm:px-4 py-2 text-center">{{ $t('trainingCenter.col.training') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="activity in trainingActivities"
                :key="activity.id"
                class="border-b hover:bg-slate-50"
                :class="activity.excluded_from_training ? 'bg-slate-100 opacity-60' : 'bg-white'"
              >
                <td class="px-2 sm:px-4 py-2 text-xs sm:text-sm">{{ formatDate(activity.activity_date) }}</td>
                <td class="hidden sm:table-cell px-4 py-2 text-sm">{{ activity.activity_type }}</td>
                <td class="px-2 sm:px-4 py-2 text-right text-sm sm:text-base whitespace-nowrap">
                  {{ activity.distance_km.toFixed(1) }} km
                  <div class="sm:hidden text-xs text-slate-500">{{ Math.round(activity.elevation_gain_m) }} m D+</div>
                </td>
                <td class="hidden sm:table-cell px-4 py-2 text-right">{{ Math.round(activity.elevation_gain_m) }} m</td>
                <td class="hidden sm:table-cell px-4 py-2 text-right text-slate-600">{{ activity.segment_count }}</td>
                <td class="hidden sm:table-cell px-4 py-2 text-center text-sm text-slate-600">{{ activity.recency_weight.toFixed(2) }}</td>
                <td class="px-2 sm:px-4 py-2 text-center">
                  <button
                    @click="toggleTrainingStatus(activity)"
                    class="btn btn-outline !px-3 sm:!px-6 !text-xs sm:!text-sm min-h-[44px]"
                    :class="activity.excluded_from_training
                      ? 'bg-slate-200 text-slate-700 hover:bg-slate-300'
                      : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'"
                  >
                    {{ activity.excluded_from_training ? $t('trainingCenter.excluded') : $t('trainingCenter.included') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Activity Download Card -->
    <div class="card stack">
      <h2 class="text-2xl font-bold mb-4">{{ $t('trainingCenter.download_title') }}</h2>

      <div v-if="!stravaActivities.length" class="space-y-6">
        <div class="text-center py-4">
          <p class="font-semibold text-slate-800">{{ $t('auth.empty.title') }}</p>
          <p class="text-slate-600 mt-1">{{ $t('auth.empty.text') }}</p>
        </div>
        <ActivityImport />
      </div>

      <div v-else class="space-y-4">
        <!-- Quick Actions -->
        <div class="flex gap-3 mb-4 items-center flex-wrap">
          <button
            @click="selectBestRuns(5)"
            class="btn btn-primary"
          >
            <svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z"/><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z"/><path d="M16 17h4"/><path d="M4 13h4"/></svg> {{ $t('trainingCenter.select_best', { n: 5 }) }}
          </button>
          <button
            @click="selectBestRuns(15)"
            class="btn btn-primary"
          >
            <svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z"/><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z"/><path d="M16 17h4"/><path d="M4 13h4"/></svg> {{ $t('trainingCenter.select_best', { n: 15 }) }}
          </button>
          <button
            @click="selectBestRuns(20)"
            class="btn btn-primary"
          >
            <svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z"/><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z"/><path d="M16 17h4"/><path d="M4 13h4"/></svg> {{ $t('trainingCenter.select_best', { n: 20 }) }}
          </button>
          <div class="text-sm text-slate-600">
            {{ $t('trainingCenter.long_preferred') }}
          </div>
          <button
            @click="selectedIds = []"
            class="btn btn-outline"
          >
            {{ $t('trainingCenter.clear') }}
          </button>
          <div class="flex-1"></div>
          <button
            @click="refreshActivities"
            :disabled="loadingActivities"
            class="btn btn-outline disabled:opacity-50"
          >
            <svg :class="{ 'animate-spin': loadingActivities }" class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
            {{ loadingActivities ? $t('trainingCenter.refreshing') : $t('trainingCenter.refresh') }}
          </button>
        </div>

        <!-- Activity List -->
        <div class="max-h-96 overflow-y-auto border rounded-lg">
          <table class="w-full">
            <thead class="bg-slate-50 sticky top-0">
              <tr>
                <th class="pl-3 pr-1 sm:px-4 py-2 text-left">
                  <input type="checkbox" class="w-5 h-5 align-middle" @change="toggleAll" :checked="selectedIds.length === sortedActivities.length">
                </th>
                <th class="px-2 sm:px-4 py-2 text-left cursor-pointer hover:bg-slate-100" @click="toggleSort('name')">
                  {{ $t('trainingCenter.col.activity') }} {{ getSortIcon('name') }}
                </th>
                <th class="hidden sm:table-cell px-4 py-2 text-left cursor-pointer hover:bg-slate-100" @click="toggleSort('type')">
                  {{ $t('trainingCenter.col.type') }} {{ getSortIcon('type') }}
                </th>
                <th class="hidden sm:table-cell px-4 py-2 text-left cursor-pointer hover:bg-slate-100" @click="toggleSort('date')">
                  {{ $t('trainingCenter.col.date') }} {{ getSortIcon('date') }}
                </th>
                <th class="hidden sm:table-cell px-4 py-2 text-right cursor-pointer hover:bg-slate-100" @click="toggleSort('distance')">
                  {{ $t('trainingCenter.col.distance') }} {{ getSortIcon('distance') }}
                </th>
                <th class="hidden sm:table-cell px-4 py-2 text-right cursor-pointer hover:bg-slate-100" @click="toggleSort('elevation')">
                  D+ {{ getSortIcon('elevation') }}
                </th>
                <th class="px-2 sm:px-4 py-2 text-right cursor-pointer hover:bg-slate-100 font-semibold whitespace-nowrap" @click="toggleSort('combo_score')" :title="$t('trainingCenter.score_hint')">
                  {{ $t('trainingCenter.col.score') }} {{ getSortIcon('combo_score') }}
                </th>
                <th class="hidden sm:table-cell px-4 py-2 text-center">{{ $t('trainingCenter.col.status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="activity in sortedActivities"
                :key="activity.strava_id"
                class="border-b hover:bg-slate-50"
                :class="getActivityRowClass(activity)"
              >
                <td class="pl-3 pr-1 sm:px-4 py-2">
                  <input
                    type="checkbox"
                    class="w-5 h-5 align-middle"
                    :value="activity.strava_id"
                    v-model="selectedIds"
                  >
                </td>
                <td class="px-2 sm:px-4 py-2">
                  {{ activity.name }}
                  <!-- Mobile: the hidden columns collapse into one meta line -->
                  <div class="sm:hidden text-xs text-slate-600 mt-0.5">
                    {{ formatDate(activity.start_date) }} · {{ (activity.distance / 1000).toFixed(1) }} km · {{ Math.round(activity.total_elevation_gain || 0) }} m
                    <svg v-if="activity.has_streams" class="inline-block w-4 h-4 align-[-0.125em] text-emerald-600" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                  </div>
                </td>
                <td class="hidden sm:table-cell px-4 py-2">
                  <span :class="getActivityTypeClass(activity)">
                    {{ getActivityTypeLabel(activity) }}
                  </span>
                </td>
                <td class="hidden sm:table-cell px-4 py-2 text-sm text-slate-600">{{ formatDate(activity.start_date) }}</td>
                <td class="hidden sm:table-cell px-4 py-2 text-right whitespace-nowrap">{{ (activity.distance / 1000).toFixed(1) }} km</td>
                <td class="hidden sm:table-cell px-4 py-2 text-right text-slate-700 whitespace-nowrap">{{ Math.round(activity.total_elevation_gain || 0) }} m</td>
                <td class="px-2 sm:px-4 py-2 text-right font-semibold text-slate-900">{{ activity.combo_score.toFixed(1) }}</td>
                <td class="hidden sm:table-cell px-4 py-2 text-center">
                  <span v-if="activity.has_streams" class="text-emerald-600 text-sm inline-flex items-center gap-1"><svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> {{ $t('trainingCenter.downloaded') }}</span>
                  <span v-else class="text-slate-400 text-sm">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Results -->
        <!-- TODO(dead-ui #12 — see GH issues): `downloadResults` is never defined in
             <script setup>, so this whole panel is unreachable and the user gets no
             success/skipped/failed feedback after a bulk download. Looks like a ref
             dropped in a refactor: declare `const downloadResults = ref(null)` and
             populate it from the bulk-download response, or delete this block. -->
        <div v-if="downloadResults" class="mt-4 space-y-2">
          <div v-if="downloadResults.success.length" class="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
            <p class="font-medium text-emerald-800 flex items-center gap-1.5"><svg class="w-4 h-4 shrink-0" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> {{ $t('trainingCenter.dl_success', { n: downloadResults.success.length }) }}</p>
          </div>
          <div v-if="downloadResults.skipped.length" class="rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p class="font-medium text-amber-800 flex items-center gap-1.5"><svg class="w-4 h-4 shrink-0" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg> {{ $t('trainingCenter.dl_skipped', { n: downloadResults.skipped.length }) }}</p>
          </div>
          <div v-if="downloadResults.failed.length" class="rounded-xl border border-rose-200 bg-rose-50 p-3">
            <p class="font-medium text-rose-800 flex items-center gap-1.5"><svg class="w-4 h-4 shrink-0" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg> {{ $t('trainingCenter.dl_failed', { n: downloadResults.failed.length }) }}</p>
          </div>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api'
import { useAuthStore } from '../stores/auth'
import AuthGate from '../components/AuthGate.vue'
import ConnectionsPanel from '../components/ConnectionsPanel.vue'
import ActivityImport from '../components/ActivityImport.vue'
import RacesCard from '../components/RacesCard.vue'
import { useToastStore } from '../stores/toast'
import { useI18n } from 'vue-i18n'

const { t, te, locale } = useI18n()

const tierStatus = ref(null)
const toast = useToastStore()
const authStore = useAuthStore()
const stravaActivities = ref([])
const trainingActivities = ref([])
const loadingTrainingActivities = ref(false)
const trainingActivityStats = ref({ total: 0, included_count: 0, excluded_count: 0 })
const selectedIds = ref([])
const loadingActivities = ref(false)
const sortColumn = ref('combo_score')
const sortDirection = ref('desc')
const retraining = ref(false)

// Computed: sorted activities
const sortedActivities = computed(() => {
  if (!stravaActivities.value.length) return []

  // Add combo score to each activity
  const withScores = stravaActivities.value.map(a => ({
    ...a,
    combo_score: (a.distance / 1000) + ((a.total_elevation_gain || 0) / 100)
  }))

  // Sort based on current column
  return withScores.sort((a, b) => {
    let aVal, bVal

    switch (sortColumn.value) {
      case 'name':
        aVal = a.name || ''
        bVal = b.name || ''
        break
      case 'type':
        aVal = a.type || a.sport_type || ''
        bVal = b.type || b.sport_type || ''
        break
      case 'date':
        aVal = new Date(a.start_date).getTime()
        bVal = new Date(b.start_date).getTime()
        break
      case 'distance':
        aVal = a.distance
        bVal = b.distance
        break
      case 'elevation':
        aVal = a.total_elevation_gain || 0
        bVal = b.total_elevation_gain || 0
        break
      case 'combo_score':
      default:
        aVal = a.combo_score
        bVal = b.combo_score
    }

    if (sortDirection.value === 'asc') {
      return aVal > bVal ? 1 : aVal < bVal ? -1 : 0
    } else {
      return aVal < bVal ? 1 : aVal > bVal ? -1 : 0
    }
  })
})

onMounted(async () => {
  await authStore.ensureAuthReady()
  if (!authStore.isAuthenticated) return
  await Promise.all([
    fetchTierStatus(),
    fetchStravaActivities(),
    fetchTrainingActivities()
  ])
})

const fetchTierStatus = async () => {
  try {
    const response = await api.get('/hybrid/tier-status')
    tierStatus.value = response.data
  } catch (error) {
    console.error('Failed to fetch tier status:', error)
  }
}

const fetchStravaActivities = async (forceRefresh = false) => {
  try {
    loadingActivities.value = true
    const params = forceRefresh ? { force_refresh: 'true' } : {}
    const response = await api.get('/strava/activities', { params })
    stravaActivities.value = response.data.activities || []
  } catch (error) {
    console.error('Failed to fetch activities:', error)
  } finally {
    loadingActivities.value = false
  }
}

const refreshActivities = async () => {
  await fetchStravaActivities(true)
}

const fetchTrainingActivities = async () => {
  try {
    loadingTrainingActivities.value = true
    const response = await api.get('/hybrid/training-activities')
    trainingActivities.value = response.data.activities || []
    trainingActivityStats.value = {
      total: response.data.total,
      included_count: response.data.included_count,
      excluded_count: response.data.excluded_count
    }
  } catch (error) {
    console.error('Failed to fetch training activities:', error)
  } finally {
    loadingTrainingActivities.value = false
  }
}

const toggleTrainingStatus = async (activity) => {
  try {
    const response = await api.post(`/hybrid/training-activities/${activity.id}/toggle`)
    activity.excluded_from_training = response.data.excluded_from_training

    // Update stats
    if (response.data.excluded_from_training) {
      trainingActivityStats.value.included_count--
      trainingActivityStats.value.excluded_count++
    } else {
      trainingActivityStats.value.included_count++
      trainingActivityStats.value.excluded_count--
    }
  } catch (error) {
    console.error('Failed to toggle training status:', error)
    alert(t('trainingCenter.toggle_failed', { msg: error.response?.data?.error || error.message }))
  }
}

const retrainModel = async () => {
  try {
    retraining.value = true
    await api.post('/hybrid/train-ml-model')
    toast.push({ message: t('trainingCenter.retrain_started') })
  } catch (error) {
    console.error('Failed to start recalibration:', error)
    toast.push({ message: t('trainingCenter.retrain_failed', { msg: error.response?.data?.error || error.message }), type: 'error' })
  } finally {
    retraining.value = false
  }
}

// Plain-language "which model and why" for the personal-habits gate.
const personalText = (pm) => {
  const pct = (x) => (x == null ? '?' : x.toLocaleString(locale.value, { maximumFractionDigits: 1 }))
  return t(`trainingCenter.personal.${pm.active ? 'active' : pm.reason}`, { n: pm.n_eval, t2: pct(pm.mape_t2), t3: pct(pm.mape_t3) })
}

const toggleSort = (column) => {
  if (sortColumn.value === column) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = column
    sortDirection.value = 'desc'
  }
}

const getSortIcon = (column) => {
  if (sortColumn.value !== column) return '⇅'
  return sortDirection.value === 'asc' ? '↑' : '↓'
}

const formatTier = (tier) => {
  const key = `trainingCenter.tier_names.${tier}`
  return te(key) ? t(key) : tier
}

const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString(locale.value, { month: 'short', day: 'numeric', year: 'numeric' })
}

const getActivityTypeLabel = (activity) => {
  const type = activity.type || activity.sport_type || 'Unknown'
  return type.replace('Run', '').trim() || 'Run'
}

const getActivityTypeClass = (activity) => {
  const type = (activity.type || activity.sport_type || '').toLowerCase()
  if (type.includes('trail')) {
    return 'px-2 py-1 bg-green-100 text-green-800 rounded text-xs font-semibold'
  } else if (type.includes('run')) {
    return 'px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-semibold'
  } else {
    return 'px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs'
  }
}

const getActivityRowClass = (activity) => {
  const type = (activity.type || activity.sport_type || '').toLowerCase()
  if (type.includes('trail')) {
    return 'bg-green-50'
  } else if (type.includes('run')) {
    return 'bg-blue-50'
  }
  return ''
}

const selectBestRuns = (count) => {
  // Filter for Run/TrailRun activities only
  const runs = sortedActivities.value.filter(a => {
    const type = a.type || a.sport_type || ''
    return type.toLowerCase().includes('run')
  })

  // Sort by priority:
  // 1. Trail runs first (better terrain variety)
  // 2. Higher combo score (distance + elevation)
  const sortedRuns = runs.sort((a, b) => {
    const aType = (a.type || a.sport_type || '').toLowerCase()
    const bType = (b.type || b.sport_type || '').toLowerCase()

    const aIsTrail = aType.includes('trail')
    const bIsTrail = bType.includes('trail')

    // Trail runs first
    if (aIsTrail && !bIsTrail) return -1
    if (!aIsTrail && bIsTrail) return 1

    // Then by combo score (higher first)
    return b.combo_score - a.combo_score
  })

  selectedIds.value = sortedRuns
    .slice(0, count)
    .map(a => a.strava_id)

  const trailCount = sortedRuns.slice(0, count).filter(a => (a.type || '').toLowerCase().includes('trail')).length
  console.log(`Selected ${selectedIds.value.length} best runs (${trailCount} trails, avg score: ${(sortedRuns.slice(0, count).reduce((sum, a) => sum + a.combo_score, 0) / count).toFixed(1)})`)
}

const toggleAll = (event) => {
  if (event.target.checked) {
    selectedIds.value = sortedActivities.value.map(a => a.strava_id)
  } else {
    selectedIds.value = []
  }
}
</script>
