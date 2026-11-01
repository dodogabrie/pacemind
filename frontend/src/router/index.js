import { createRouter, createWebHistory, RouterView } from 'vue-router'
import { h } from 'vue'
import i18n from '../i18n'
import { applyRouteMeta } from '../utils/seo'
import Home from '../views/Home.vue'
import Predict from '../views/Predict.vue'
import Prediction from '../views/Prediction.vue'
import Training from '../views/Training.vue'
import About from '../views/About.vue'
import Privacy from '../views/Privacy.vue'
import HowItWorks from '../views/HowItWorks.vue'
import Pricing from '../views/Pricing.vue'
import Demo from '../views/Demo.vue'
import AuthSuccess from '../views/AuthSuccess.vue'
import AuthError from '../views/AuthError.vue'

const routes = [
  {
    path: '/:lang(en|it)?',
    component: { render: () => h(RouterView) },
    children: [
      {
        path: '',
        name: 'Home',
        component: Home,
        meta: {
          title: 'PaceMind — AI pacing coach for trail & ultra racing',
          description: 'Predict your race finish time and pacing strategy on any GPX course. Physics + Strava + AI coaching to help you finish stronger.'
        }
      },
      {
        path: 'pricing',
        name: 'Pricing',
        component: Pricing,
        meta: {
          title: 'Pricing — PaceMind',
          description: 'Free tier, Premium subscription, or one-time Race Day Pass. Cancel anytime.'
        }
      },
      {
        path: 'demo',
        name: 'Demo',
        component: Demo,
        meta: {
          title: 'Try PaceMind on the UTMB course — no login',
          description: 'See PaceMind predict the UTMB Pyramides race time on a sample GPX, no Strava login required.'
        }
      },
      {
        path: 'predict',
        name: 'Predict',
        component: Predict,
        meta: {
          title: 'Create a race plan — PaceMind',
          description: 'Upload a GPX route and get an AI-powered pacing plan calibrated to your Strava history.'
        }
      },
      {
        path: 'analysis/:gpxId',
        name: 'Analysis',
        redirect: to => {
          const lang = to.params.lang || 'en'
          // If lang is implicit (empty), we might want to redirect to /prediction or /en/prediction
          // Let's keep it simple: keep the current lang context or default to nothing if it was nothing
          const prefix = to.params.lang ? `/${to.params.lang}` : ''
          return `${prefix}/prediction/${to.params.gpxId}`
        }
      },
      {
        path: 'prediction/:gpxId',
        name: 'Prediction',
        component: Prediction,
        props: true
      },
      {
        path: 'training',
        name: 'Training',
        component: Training
      },
      {
        path: 'calendar',
        name: 'Calendar',
        component: () => import('../views/Calendar.vue')
      },
      {
        path: 'activity/:id',
        name: 'ActivityAnalysis',
        component: () => import('../views/ActivityAnalysis.vue')
      },
      {
        path: 'training-plan',
        redirect: { name: 'Calendar' }
      },
      {
        path: 'race/:planId',
        name: 'RaceDashboard',
        component: () => import('../views/Calendar.vue'),
        props: (route) => ({ openRaceDrawer: route.params.planId })
      },
      {
        path: 'race/:planId/report',
        name: 'RaceReport',
        component: () => import('../views/RaceReport.vue'),
        props: true
      },
      {
        path: 'season',
        name: 'SeasonOverview',
        component: () => import('../views/SeasonOverview.vue')
      },
      {
        path: 'routes',
        name: 'Routes',
        component: () => import('../views/Routes.vue'),
        meta: { fullScreen: true }
      },
      {
        path: 'races',
        name: 'Races',
        component: () => import('../views/Races.vue'),
        meta: {
          title: 'Race calendar — PaceMind',
          description: 'Browse upcoming road and trail races, filter by distance, elevation, and travel range, and add them to your training plan as A/B/C races.'
        }
      },
      {
        path: 'chi-sono',
        name: 'AboutIt',
        component: About
      },
      {
        path: 'who-i-am',
        name: 'AboutEn',
        component: About
      },
      {
        path: 'privacy',
        name: 'Privacy',
        component: Privacy
      },
      {
        path: 'how-it-works',
        name: 'HowItWorksEn',
        component: HowItWorks,
        meta: {
          title: 'How PaceMind works — physics + ML + AI coaching',
          description: 'Learn how PaceMind combines the Minetti energy-cost model, your Strava history, and Claude-powered AI to predict race pacing.'
        }
      },
      {
        path: 'come-funziona',
        name: 'HowItWorksIt',
        component: HowItWorks,
        meta: {
          title: 'Come funziona PaceMind — fisica + ML + AI coaching',
          description: 'Scopri come PaceMind combina il modello energetico Minetti, il tuo storico Strava e un AI coach per prevedere il passo di gara.'
        }
      },
      {
        path: 'auth-success',
        name: 'AuthSuccess',
        component: AuthSuccess
      },
      {
        path: 'auth-error',
        name: 'AuthError',
        component: AuthError
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

const supportedLangs = ['en', 'it']
const getStoredLang = () => {
  if (typeof localStorage === 'undefined') return null
  return localStorage.getItem('preferred_lang')
}

const setStoredLang = (lang) => {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem('preferred_lang', lang)
}

const getBrowserLang = () => {
  if (typeof navigator === 'undefined') return null
  const navLang = navigator.language || (navigator.languages && navigator.languages[0])
  if (!navLang) return null
  const short = navLang.toLowerCase().split('-')[0]
  return supportedLangs.includes(short) ? short : null
}

router.beforeEach((to, from, next) => {
  const lang = to.params.lang
  let resolvedLang
  if (lang && supportedLangs.includes(lang)) {
    i18n.global.locale.value = lang
    setStoredLang(lang)
    resolvedLang = lang
  } else {
    const stored = getStoredLang()
    const fallback = (stored && supportedLangs.includes(stored)) ? stored : (getBrowserLang() || 'en')
    i18n.global.locale.value = fallback
    setStoredLang(fallback)
    resolvedLang = fallback
  }
  applyRouteMeta(to, resolvedLang)
  next()
})

export default router
