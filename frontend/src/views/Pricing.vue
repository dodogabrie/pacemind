<template>
  <div class="min-h-screen bg-slate-50">
    <!-- HERO -->
    <section class="pt-4 pb-10 sm:py-20 bg-gradient-to-b from-white to-slate-50">
      <div class="layout max-sm:px-0 text-center max-w-3xl mx-auto">
        <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-emerald-700 text-[11px] sm:text-xs font-bold uppercase tracking-widest mb-5">
          <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
          {{ $t('pricing.badge') }}
        </div>
        <h1 class="text-4xl sm:text-5xl font-bold text-slate-900 tracking-tight">
          {{ $t('pricing.title') }}
        </h1>
        <p class="text-base sm:text-lg text-slate-600 mt-4 leading-relaxed">
          {{ $t('pricing.subtitle') }}
        </p>
        <div class="inline-flex items-center gap-2 mt-6 text-sm text-slate-500">
          <span>{{ $t('pricing.billing.monthly') }}</span>
          <button
            type="button"
            @click="billingCycle = billingCycle === 'monthly' ? 'yearly' : 'monthly'"
            class="relative w-12 h-6 rounded-full bg-slate-200 transition-colors before:absolute before:-inset-2.5 before:content-['']"
            :class="{ 'bg-emerald-500': billingCycle === 'yearly' }"
            :aria-pressed="billingCycle === 'yearly'"
          >
            <span
              class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              :class="{ 'translate-x-6': billingCycle === 'yearly' }"
            ></span>
          </button>
          <span>{{ $t('pricing.billing.yearly') }} <span class="text-emerald-600 font-semibold">{{ $t('pricing.billing.save') }}</span></span>
        </div>
      </div>
    </section>

    <!-- TIERS -->
    <section class="pb-12 sm:pb-16">
      <div class="layout max-sm:px-0 grid md:grid-cols-3 gap-6 max-w-6xl mx-auto">
        <!-- FREE -->
        <article class="bg-white rounded-2xl border border-slate-200 p-6 sm:p-8 flex flex-col">
          <h2 class="text-xl font-bold text-slate-900">{{ $t('pricing.plans.free.name') }}</h2>
          <p class="text-sm text-slate-500 mt-1">{{ $t('pricing.plans.free.tagline') }}</p>
          <div class="mt-4 mb-4 sm:mt-6 sm:mb-6">
            <span class="text-4xl font-bold text-slate-900">$0</span>
            <span class="text-slate-500 ml-1">{{ $t('pricing.suffix.month') }}</span>
          </div>
          <ul class="space-y-2.5 text-sm text-slate-700 flex-1">
            <li v-for="(f, i) in $tm('pricing.plans.free.features')" :key="i" class="flex gap-2">
              <svg class="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              <span>{{ f }}</span>
            </li>
          </ul>
          <router-link :to="{ name: 'Predict', params: { lang: $route.params.lang } }" class="btn btn-outline mt-6 w-full justify-center">
            {{ $t('pricing.plans.free.cta') }}
          </router-link>
        </article>

        <!-- PREMIUM -->
        <article class="bg-white rounded-2xl border-2 border-emerald-500 p-6 sm:p-8 flex flex-col relative shadow-xl shadow-emerald-500/10">
          <div class="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-emerald-500 text-white text-[11px] font-bold uppercase tracking-widest">
            {{ $t('pricing.plans.premium.badge') }}
          </div>
          <h2 class="text-xl font-bold text-slate-900">{{ $t('pricing.plans.premium.name') }}</h2>
          <p class="text-sm text-slate-500 mt-1">{{ $t('pricing.plans.premium.tagline') }}</p>
          <div class="mt-4 sm:mt-6 mb-2">
            <span class="text-4xl font-bold text-slate-900">${{ billingCycle === 'yearly' ? '6.58' : '9' }}</span>
            <span class="text-slate-500 ml-1">{{ $t('pricing.suffix.month') }}</span>
          </div>
          <p v-if="billingCycle === 'yearly'" class="text-xs text-emerald-600 font-semibold mb-4">
            {{ $t('pricing.plans.premium.yearly_note') }}
          </p>
          <p v-else class="text-xs text-slate-400 mb-4">{{ $t('pricing.plans.premium.monthly_note') }}</p>
          <ul class="space-y-2.5 text-sm text-slate-700 flex-1">
            <li v-for="(f, i) in $tm('pricing.plans.premium.features')" :key="i" class="flex gap-2">
              <svg class="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              <span>{{ f }}</span>
            </li>
          </ul>
          <button @click="checkout(billingCycle === 'yearly' ? 'premium_yearly' : 'premium_monthly')" class="btn btn-primary mt-6 w-full justify-center">
            {{ $t('pricing.plans.premium.cta') }}
          </button>
        </article>

        <!-- RACE DAY PASS -->
        <article class="bg-white rounded-2xl border border-slate-200 p-6 sm:p-8 flex flex-col">
          <h2 class="text-xl font-bold text-slate-900">{{ $t('pricing.plans.race_pass.name') }}</h2>
          <p class="text-sm text-slate-500 mt-1">{{ $t('pricing.plans.race_pass.tagline') }}</p>
          <div class="mt-4 mb-4 sm:mt-6 sm:mb-6">
            <span class="text-4xl font-bold text-slate-900">$4</span>
            <span class="text-slate-500 ml-1">{{ $t('pricing.suffix.week_pass') }}</span>
          </div>
          <ul class="space-y-2.5 text-sm text-slate-700 flex-1">
            <li v-for="(f, i) in $tm('pricing.plans.race_pass.features')" :key="i" class="flex gap-2">
              <svg class="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              <span>{{ f }}</span>
            </li>
          </ul>
          <button @click="checkout('race_day_pass')" class="btn btn-outline mt-6 w-full justify-center">
            {{ $t('pricing.plans.race_pass.cta') }}
          </button>
        </article>
      </div>

      <!-- COACH/TEAM WAITLIST -->
      <div class="layout max-sm:px-0 max-w-4xl mx-auto mt-8 sm:mt-12">
        <div class="rounded-2xl border border-sky-200 bg-gradient-to-r from-sky-50 to-emerald-50 p-6 sm:p-8 flex flex-col sm:flex-row sm:items-center gap-6">
          <div class="flex-1">
            <div class="inline-flex items-center gap-2 px-2 py-0.5 rounded-full bg-sky-600 text-white text-[10px] font-bold uppercase tracking-widest mb-2">
              {{ $t('pricing.coach.badge') }}
            </div>
            <h3 class="text-xl font-bold text-slate-900">{{ $t('pricing.coach.title') }}</h3>
            <p class="text-sm text-slate-600 mt-2 max-w-xl">{{ $t('pricing.coach.description') }}</p>
          </div>
          <form @submit.prevent="joinWaitlist" class="flex flex-col sm:flex-row gap-2 w-full sm:w-auto">
            <input
              v-model="waitlistEmail"
              type="email"
              required
              :placeholder="$t('pricing.coach.email_placeholder')"
              class="px-3 py-2.5 rounded-lg border border-slate-300 bg-white text-base sm:text-sm w-full sm:w-56"
            />
            <button type="submit" class="btn btn-primary text-sm px-4 py-3 sm:py-2.5 whitespace-nowrap">
              <svg v-if="waitlistJoined" class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              {{ waitlistJoined ? $t('pricing.coach.joined') : $t('pricing.coach.cta') }}
            </button>
          </form>
        </div>
      </div>
    </section>

    <!-- FAQ -->
    <section class="py-12 sm:py-16 bg-white border-t border-slate-100">
      <div class="layout max-sm:px-0 max-w-3xl mx-auto">
        <h2 class="text-[1.75rem] sm:text-3xl font-bold text-slate-900 text-center mb-6 sm:mb-10">{{ $t('pricing.faq.title') }}</h2>
        <div class="space-y-3 sm:space-y-4">
          <details
            v-for="(item, i) in $tm('pricing.faq.items')"
            :key="i"
            class="group rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 sm:p-5"
          >
            <summary class="font-semibold text-slate-900 cursor-pointer list-none flex items-center justify-between gap-3 min-h-11 [&::-webkit-details-marker]:hidden">
              {{ item.q }}
              <span class="shrink-0 text-lg text-slate-400 group-open:rotate-45 transition-transform">+</span>
            </summary>
            <p class="text-sm text-slate-600 mt-3 leading-relaxed">{{ item.a }}</p>
          </details>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useSubscriptionStore } from '../stores/subscription'

const billingCycle = ref('monthly')
const waitlistEmail = ref('')
const waitlistJoined = ref(false)
const subscription = useSubscriptionStore()

async function checkout(plan) {
  try {
    await subscription.createCheckout(plan)
  } catch (e) {
    console.error('Checkout failed', e)
  }
}

async function joinWaitlist() {
  if (!waitlistEmail.value) return
  try {
    await fetch('/api/billing/waitlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: waitlistEmail.value, plan: 'coach_team' }),
    })
  } catch (_) {
    // fail quietly - still show success to user
  }
  waitlistJoined.value = true
  waitlistEmail.value = ''
}
</script>
