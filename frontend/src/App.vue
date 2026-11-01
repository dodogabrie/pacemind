<template>
  <div id="app" class="min-h-screen flex flex-col bg-slate-50">
    <!-- Navigation -->
    <nav class="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200 pt-[env(safe-area-inset-top)]">
      <div class="layout flex h-16 items-center justify-between">
        <!-- Logo -->
        <router-link :to="homeRoute" class="flex items-center gap-2 group min-w-0">
          <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-700 text-white shadow-md group-hover:bg-emerald-800 transition-colors">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="w-5 h-5">
               <path stroke-linecap="round" stroke-linejoin="round" d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
               <path stroke-linecap="round" stroke-linejoin="round" d="M12 18a3.75 3.75 0 00.495-7.467 5.99 5.99 0 00-1.925 3.546 5.974 5.974 0 01-2.133-1.001A3.75 3.75 0 0012 18z" />
            </svg>
          </div>
          <div class="flex flex-col">
            <span class="text-lg font-bold uppercase tracking-tight text-slate-900 leading-none">PaceMind</span>
            <span class="text-[10px] font-bold text-emerald-600 uppercase tracking-widest">Trail Intelligence</span>
          </div>
        </router-link>

        <!-- Navigation Links (Removed) -->
        <div class="hidden md:flex items-center gap-6 text-sm font-medium text-slate-600 uppercase tracking-wide">
          <router-link :to="planRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.plan') }}
          </router-link>
          <router-link :to="trainingPlanRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.calendar') }}
          </router-link>
          <router-link :to="routesRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.routes') }}
          </router-link>
          <router-link :to="racesRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.races') }}
          </router-link>
          <router-link v-if="raceRoute" :to="raceRoute" class="hover:text-emerald-700 transition-colors font-bold">
            {{ raceLabel }}
          </router-link>
          <router-link :to="howItWorksRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.methodology') }}
          </router-link>
          <router-link :to="pricingRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.pricing') }}
          </router-link>
          <router-link :to="aboutRoute" class="hover:text-emerald-700 transition-colors">
            {{ $t('nav.about') }}
          </router-link>
        </div>

        <!-- Right Side Actions -->
        <div class="flex items-center gap-2 sm:gap-4 shrink-0">
          <template v-if="authStore.isAuthenticated">
            <NotificationBell />
            <div class="hidden sm:flex flex-col items-end mr-2">
              <span class="text-[10px] text-slate-400 uppercase tracking-wider">{{ $t('app.athlete') }}</span>
              <span class="text-xs font-bold text-slate-700">{{ authStore.displayName }}</span>
            </div>
            <button @click="logout" class="inline-flex items-center justify-center w-10 h-10 -mx-1 text-slate-400 hover:text-rose-600 transition-colors" :aria-label="$t('common.buttons.logout')" :title="$t('common.buttons.logout')">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
              </svg>
            </button>
          </template>
          <template v-else>
            <button @click="authStore.openSignIn()" class="btn btn-primary text-xs py-2 px-4 min-h-10">
              {{ $t('common.buttons.sign_in') }}
            </button>
          </template>
          <button
            class="md:hidden inline-flex items-center justify-center w-11 h-11 rounded-md border border-slate-200 text-slate-600 hover:text-emerald-700 hover:border-emerald-200 transition-colors"
            @click="mobileMenuOpen = !mobileMenuOpen"
            :aria-expanded="mobileMenuOpen ? 'true' : 'false'"
            aria-controls="mobile-menu"
            :aria-label="$t('nav.toggle_menu')"
          >
            <span class="sr-only">{{ $t('nav.toggle_menu') }}</span>
            <svg v-if="mobileMenuOpen" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span v-else class="flex flex-col gap-[3px]" aria-hidden="true">
              <span class="block w-5 h-[2px] bg-current rounded"></span>
              <span class="block w-5 h-[2px] bg-current rounded"></span>
              <span class="block w-5 h-[2px] bg-current rounded"></span>
            </span>
          </button>
        </div>
      </div>
      <div
        v-if="mobileMenuOpen"
        id="mobile-menu"
        class="md:hidden border-t border-slate-200 bg-white/95 backdrop-blur-md max-h-[calc(100dvh-4rem-env(safe-area-inset-top))] overflow-y-auto overscroll-contain"
        @keydown.esc="mobileMenuOpen = false"
      >
        <div class="layout py-2 flex flex-col divide-y divide-slate-100 text-sm font-semibold text-slate-700 uppercase tracking-wide">
          <router-link :to="planRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.plan') }}
          </router-link>
          <router-link :to="trainingPlanRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.calendar') }}
          </router-link>
          <router-link :to="routesRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.routes') }}
          </router-link>
          <router-link :to="racesRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.races') }}
          </router-link>
          <router-link v-if="raceRoute" :to="raceRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors font-bold" @click="mobileMenuOpen = false">
            {{ raceLabel }}
          </router-link>
          <router-link :to="howItWorksRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.methodology') }}
          </router-link>
          <router-link :to="pricingRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.pricing') }}
          </router-link>
          <router-link :to="aboutRoute" class="flex items-center min-h-12 hover:text-emerald-700 transition-colors" @click="mobileMenuOpen = false">
            {{ $t('nav.about') }}
          </router-link>
        </div>
      </div>
    </nav>

    <!-- Global Sync Progress Bar -->
    <div v-if="syncStore.isSyncing" class="w-full bg-slate-100">
      <div
        class="h-[3px] transition-all duration-700 ease-out"
        style="background: linear-gradient(120deg, #34d399 0%, #22d3ee 100%);"
        :style="{ width: `${syncStore.progressPercent}%` }"
      ></div>
      <div v-if="syncStore.message" class="text-[11px] text-slate-500 text-center py-0.5 truncate px-4">
        {{ syncStore.message }}
      </div>
    </div>

    <!-- Main Content -->
    <main
      class="flex-grow w-full"
      :class="{
        'layout': !isFullScreen,
        'py-8 md:py-12': !isHome && !isFullScreen,
        'pb-8 md:pb-12': isHome,
        'relative overflow-hidden': isFullScreen,
      }"
    >
      <div v-if="!isHome && !isFullScreen" class="mb-4">
        <router-link :to="homeRoute" class="link text-sm">{{ $t('nav.back_home') }}</router-link>
      </div>
      <router-view />
    </main>

    <!-- Footer -->
    <footer v-if="!isFullScreen" class="border-t border-slate-200 bg-white pt-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] sm:py-8 mt-auto">
      <div class="layout flex flex-col md:flex-row justify-between items-center gap-4 text-xs text-slate-500">
        <div>{{ $t('app.copyright') }}</div>
        <div class="flex gap-6">
          <router-link :to="howItWorksRoute" class="py-2 hover:text-emerald-700 transition-colors">
            {{ $t('app.methodology') }}
          </router-link>
          <router-link :to="privacyRoute" class="py-2 hover:text-emerald-700 transition-colors">
            {{ $t('app.privacy') }}
          </router-link>
        </div>
      </div>
    </footer>

    <!-- Global sign-in dialog (nav button + the session-expired toast open it) -->
    <div
      v-if="authStore.signInModalOpen"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))]"
      role="dialog"
      aria-modal="true"
      :aria-label="$t('auth.signin.dialog_label')"
      @click.self="authStore.closeSignIn()"
      @keydown.esc="authStore.closeSignIn()"
    >
      <div ref="signInDialog" tabindex="-1" class="relative w-full max-w-md max-h-full overflow-y-auto overscroll-contain rounded-2xl bg-white shadow-xl outline-none">
        <button
          type="button"
          class="absolute right-1 top-1 inline-flex items-center justify-center w-11 h-11 text-slate-400 hover:text-slate-700"
          :aria-label="$t('common.buttons.close')"
          @click="authStore.closeSignIn()"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
        <AuthGate />
      </div>
    </div>

    <!-- Global upgrade modal -->
    <UpgradeModal />

    <!-- Global transient messages (session expiry, etc.) -->
    <ToastHost />
  </div>
</template>

<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth'
import { useSubscriptionStore } from './stores/subscription'
import { useSyncStore } from './stores/sync'
import { useTrainingPlanStore } from './stores/trainingPlan'
import AuthGate from './components/AuthGate.vue'
import UpgradeModal from './components/UpgradeModal.vue'
import NotificationBell from './components/NotificationBell.vue'
import ToastHost from './components/ToastHost.vue'

const authStore = useAuthStore()
const subscriptionStore = useSubscriptionStore()
const syncStore = useSyncStore()
const trainingPlanStore = useTrainingPlanStore()
const route = useRoute()
const { locale, t } = useI18n()
const mobileMenuOpen = ref(false)
const signInDialog = ref(null)

// Move focus into the dialog so keyboard/screen-reader users land on it and
// Escape (bound on the wrapper) is heard.
watch(() => authStore.signInModalOpen, async (open) => {
  if (!open) return
  await nextTick()
  signInDialog.value?.focus()
})

const homeRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return useLang ? { name: 'Home', params: { lang: langParam } } : { name: 'Home' }
})

const isHome = computed(() => route.name === 'Home')
const isFullScreen = computed(() => route.meta?.fullScreen === true)

const planRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'Predict',
    params: useLang ? { lang: langParam } : {}
  }
})

const trainingPlanRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'Calendar',
    params: useLang ? { lang: langParam } : {}
  }
})

const routesRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'Routes',
    params: useLang ? { lang: langParam } : {}
  }
})

const racesRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'Races',
    params: useLang ? { lang: langParam } : {}
  }
})

const raceRoute = computed(() => {
  if (!authStore.isAuthenticated) return null
  const activePlans = trainingPlanStore.activePlans
  if (activePlans.length === 0) return null
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  if (activePlans.length >= 2) {
    return {
      name: 'SeasonOverview',
      params: useLang ? { lang: langParam } : {}
    }
  }
  return {
    name: 'RaceDashboard',
    params: { ...(useLang ? { lang: langParam } : {}), planId: activePlans[0].id }
  }
})

const raceLabel = computed(() => {
  const activePlans = trainingPlanStore.activePlans
  return activePlans.length >= 2 ? t('nav.my_season') : t('nav.my_race')
})

const aboutRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  const isItalian = locale.value === 'it'
  return {
    name: isItalian ? 'AboutIt' : 'AboutEn',
    params: useLang ? { lang: langParam } : {}
  }
})

const privacyRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'Privacy',
    params: useLang ? { lang: langParam } : {}
  }
})

const pricingRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  return {
    name: 'Pricing',
    params: useLang ? { lang: langParam } : {}
  }
})

const howItWorksRoute = computed(() => {
  const langParam = route.params.lang
  const useLang = typeof langParam === 'string' && langParam.length > 0
  const isItalian = locale.value === 'it'
  return {
    name: isItalian ? 'HowItWorksIt' : 'HowItWorksEn',
    params: useLang ? { lang: langParam } : {}
  }
})

onMounted(async () => {
  // Shared with the views, which each await the same probe before fetching.
  await authStore.ensureAuthReady()
  if (authStore.isAuthenticated) {
    await subscriptionStore.fetchStatus()
    syncStore.startPolling()
    trainingPlanStore.fetchPlans()
  }
})

// Close the mobile menu on any navigation (covers back/forward, not just link taps)
// and stop the page scrolling behind it while open.
watch(() => route.fullPath, () => { mobileMenuOpen.value = false })
watch(mobileMenuOpen, (open) => { document.body.style.overflow = open ? 'hidden' : '' })

const logout = () => {
  authStore.logout()
}
</script>
