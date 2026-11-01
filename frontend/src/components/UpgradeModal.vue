<template>
  <div v-if="store.showUpgradeModal" class="fixed inset-0 z-[60] flex items-end sm:items-center justify-center sm:p-4" role="dialog" aria-modal="true" @keydown.esc="store.closeUpgradeModal">
    <!-- Backdrop -->
    <div class="absolute inset-0 bg-black/50" @click="store.closeUpgradeModal"></div>

    <!-- Modal -->
    <div class="relative bg-white rounded-t-2xl sm:rounded-2xl shadow-xl max-w-lg w-full max-h-[92dvh] sm:max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:p-6">
      <button
        @click="store.closeUpgradeModal"
        class="absolute top-2 right-2 inline-flex items-center justify-center w-11 h-11 text-gray-400 hover:text-gray-600"
        :aria-label="$t('common.buttons.close')"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      <h2 class="text-xl font-bold text-gray-900 mb-2 pr-10 leading-tight">{{ headline }}</h2>
      <p class="text-sm sm:text-base text-gray-600 mb-5 sm:mb-6">{{ subline }}</p>

      <!-- Plans -->
      <div class="space-y-3 mb-6">
        <!-- Premium Monthly -->
        <div
          class="border-2 rounded-xl p-3 sm:p-4 cursor-pointer transition-colors"
          :class="selectedPlan === 'premium_monthly' ? 'border-emerald-600 bg-emerald-50' : 'border-gray-200 hover:border-emerald-300'"
          @click="selectedPlan = 'premium_monthly'"
        >
          <div class="flex justify-between items-center gap-3">
            <div>
              <div class="font-semibold text-gray-900">{{ $t('pricing.upgrade.monthly_name') }}</div>
              <div class="text-sm text-gray-600">{{ $t('pricing.upgrade.monthly_desc') }}</div>
            </div>
            <div class="shrink-0 text-lg font-bold text-gray-900">$9{{ $t('pricing.suffix.month') }}</div>
          </div>
        </div>

        <!-- Premium Yearly -->
        <div
          class="border-2 rounded-xl p-3 sm:p-4 cursor-pointer transition-colors"
          :class="selectedPlan === 'premium_yearly' ? 'border-emerald-600 bg-emerald-50' : 'border-gray-200 hover:border-emerald-300'"
          @click="selectedPlan = 'premium_yearly'"
        >
          <div class="flex justify-between items-center gap-3">
            <div>
              <div class="font-semibold text-gray-900">
                {{ $t('pricing.upgrade.yearly_name') }}
                <span class="ml-2 text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded-full">{{ $t('pricing.upgrade.save') }}</span>
              </div>
              <div class="text-sm text-gray-600">{{ $t('pricing.upgrade.yearly_desc') }}</div>
            </div>
            <div class="shrink-0 text-lg font-bold text-gray-900">$79{{ $t('pricing.suffix.year') }}</div>
          </div>
        </div>

        <!-- Race Day Pass -->
        <div
          class="border-2 rounded-xl p-3 sm:p-4 cursor-pointer transition-colors"
          :class="selectedPlan === 'race_day_pass' ? 'border-emerald-600 bg-emerald-50' : 'border-gray-200 hover:border-emerald-300'"
          @click="selectedPlan = 'race_day_pass'"
        >
          <div class="flex justify-between items-center gap-3">
            <div>
              <div class="font-semibold text-gray-900">{{ $t('pricing.plans.race_pass.name') }}</div>
              <div class="text-sm text-gray-600">{{ $t('pricing.upgrade.pass_desc') }}</div>
            </div>
            <div class="shrink-0 text-lg font-bold text-gray-900">$4</div>
          </div>
        </div>
      </div>

      <!-- Features list -->
      <div class="border-t border-gray-200 pt-4 mb-5 sm:mb-6">
        <div class="text-sm font-medium text-gray-700 mb-2">{{ $t('pricing.upgrade.includes') }}</div>
        <ul class="text-sm text-gray-600 space-y-1">
          <li class="flex items-start gap-2">
            <svg class="w-4 h-4 mt-0.5 text-emerald-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
            {{ $t('pricing.upgrade.feat_ai') }}
          </li>
          <li class="flex items-start gap-2">
            <svg class="w-4 h-4 mt-0.5 text-emerald-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
            {{ $t('pricing.upgrade.feat_terrain') }}
          </li>
          <li class="flex items-start gap-2">
            <svg class="w-4 h-4 mt-0.5 text-emerald-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
            {{ $t('pricing.upgrade.feat_weather') }}
          </li>
          <li class="flex items-start gap-2">
            <svg class="w-4 h-4 mt-0.5 text-emerald-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
            {{ $t('pricing.upgrade.feat_brief') }}
          </li>
          <li class="flex items-start gap-2">
            <svg class="w-4 h-4 mt-0.5 text-emerald-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
            {{ $t('pricing.upgrade.feat_ml') }}
          </li>
        </ul>
      </div>

      <!-- CTA -->
      <button
        @click="handleUpgrade"
        :disabled="store.loading"
        class="w-full bg-emerald-700 text-white py-3 px-4 rounded-full font-semibold uppercase tracking-wide text-sm hover:bg-emerald-800 transition-colors disabled:opacity-50"
      >
        <span v-if="store.loading">{{ $t('pricing.upgrade.processing') }}</span>
        <span v-else>{{ $t('pricing.upgrade.checkout') }}</span>
      </button>

      <!-- Trust row -->
      <div class="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 mt-4 text-xs text-gray-500">
        <span class="flex items-center gap-1">
          <svg class="w-3.5 h-3.5 text-emerald-500" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
          {{ $t('pricing.upgrade.cancel_anytime') }}
        </span>
        <span class="flex items-center gap-1">
          <svg class="w-3.5 h-3.5 text-emerald-500" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
          {{ $t('pricing.upgrade.money_back') }}
        </span>
        <router-link
          :to="{ name: 'Pricing' }"
          @click="store.closeUpgradeModal"
          class="py-1 text-emerald-700 hover:underline"
        >{{ $t('pricing.upgrade.see_pricing') }}</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSubscriptionStore } from '../stores/subscription'

const store = useSubscriptionStore()
const selectedPlan = ref('premium_monthly')
const { t, te } = useI18n()

// Feature-specific copy lives in pricing.upgrade.features.<feature>.
const featureKey = (field) => {
  const key = `pricing.upgrade.features.${store.upgradeFeature}.${field}`
  return store.upgradeFeature && te(key) ? key : `pricing.upgrade.default.${field}`
}
const headline = computed(() => t(featureKey('headline')))
const subline = computed(() => t(featureKey('subline')))

async function handleUpgrade() {
  try {
    await store.createCheckout(selectedPlan.value)
  } catch (error) {
    console.error('Checkout failed:', error)
  }
}
</script>
