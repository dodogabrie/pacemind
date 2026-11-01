import { defineStore } from 'pinia'
import api from '../services/api'

export const useTrainingPlanStore = defineStore('trainingPlan', {
  state: () => ({
    plans: [],
    currentPlan: null,
    compliance: null,
    dashboard: null,
    season: null,
    raceReport: null,
    paceZones: null,
    calendarDays: [],
    calendarRaces: [],
    calendarActivities: [],
    calendarWindow: null,
    loading: false,
    error: null,
  }),

  getters: {
    activePlans(state) {
      return state.plans.filter(p => p.status === 'active')
    },
    activePlan(state) {
      // Backward compat: returns the next upcoming race
      const active = state.plans.filter(p => p.status === 'active')
      if (active.length === 0) return null
      // Sort by race_date ascending, return first
      return active.sort((a, b) => {
        if (!a.race_date) return 1
        if (!b.race_date) return -1
        return new Date(a.race_date) - new Date(b.race_date)
      })[0]
    },
    nextRace() {
      return this.activePlan
    },
    raceCountdown(state) {
      if (!state.dashboard?.plan?.race_date) return null
      const raceDate = new Date(state.dashboard.plan.race_date)
      const now = new Date()
      const diff = Math.ceil((raceDate - now) / (1000 * 60 * 60 * 24))
      return Math.max(0, diff)
    },
  },

  actions: {
    async fetchPlans() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/training-plan/')
        this.plans = data.plans || []
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      } finally {
        this.loading = false
      }
    },

    async fetchPlan(id) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get(`/training-plan/${id}`)
        this.currentPlan = data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      } finally {
        this.loading = false
      }
    },

    async updatePlan(id, updates) {
      this.error = null
      try {
        const { data } = await api.put(`/training-plan/${id}`, updates)
        this.currentPlan = data
        // Update in list too
        const idx = this.plans.findIndex(p => p.id === id)
        if (idx !== -1) {
          this.plans[idx] = { ...this.plans[idx], ...updates }
        }
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      }
    },

    async updateWorkoutDay(planId, weekNumber, dayName, updates) {
      this.error = null
      try {
        const { data } = await api.patch(
          `/training-plan/${planId}/weeks/${weekNumber}/days/${dayName}`,
          updates
        )
        if (this.currentPlan?.weeks) {
          const week = this.currentPlan.weeks.find(w => w.week_number === weekNumber)
          if (week) {
            const dayIdx = week.days.findIndex(d => d.day === dayName)
            if (dayIdx !== -1) {
              Object.assign(week.days[dayIdx], data.day)
            }
            if (data.week_totals) {
              week.total_km = data.week_totals.total_km
              week.total_elevation_m = data.week_totals.total_elevation_m
            }
          }
        }
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async fetchCompliance(planId) {
      try {
        const { data } = await api.get(`/training-plan/${planId}/compliance`)
        this.compliance = data
      } catch (err) {
        this.compliance = null
      }
    },

    async fetchRaceDashboard(planId) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get(`/training-plan/${planId}/dashboard`)
        this.dashboard = data
        this.currentPlan = data.plan
        this.compliance = data.compliance
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        this.dashboard = null
      } finally {
        this.loading = false
      }
    },

    async fetchSeason() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/training-plan/season')
        this.season = data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        this.season = null
      } finally {
        this.loading = false
      }
    },

    async completePlan(planId, stravaActivityId) {
      this.error = null
      try {
        const { data } = await api.post(`/training-plan/${planId}/complete`, {
          strava_activity_id: stravaActivityId,
        })
        this.raceReport = data
        // Update plan status in list
        const idx = this.plans.findIndex(p => p.id === planId)
        if (idx !== -1) {
          this.plans[idx].status = 'completed'
        }
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async fetchRaceReport(planId) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get(`/training-plan/${planId}/race-report`)
        this.raceReport = data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        this.raceReport = null
      } finally {
        this.loading = false
      }
    },

    async fetchPaceZones(opts = {}) {
      // opts previews a method (+ unsaved race result) without persisting:
      // { method, race_distance_m, race_time_s }
      try {
        const params = {}
        if (opts.method) params.method = opts.method
        if (opts.race_distance_m != null) params.race_distance_m = opts.race_distance_m
        if (opts.race_time_s != null) params.race_time_s = opts.race_time_s
        const { data } = await api.get('/training-plan/pace-zones', { params })
        this.paceZones = data
        return data
      } catch (err) {
        this.paceZones = null
      }
    },

    async savePaceZoneMethod(payload) {
      // payload: { method, race_distance_m?, race_time_s? }
      this.error = null
      try {
        const { data } = await api.put('/training-plan/pace-zone-method', payload)
        await this.fetchPaceZones()
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async updatePaceZones(zones) {
      this.error = null
      try {
        const { data } = await api.put('/training-plan/pace-zones', { zones })
        // Refresh after update
        await this.fetchPaceZones()
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async fetchCalendar(fromDate, toDate) {
      this.loading = true
      this.error = null
      try {
        const params = {}
        if (fromDate) params.from = fromDate
        if (toDate) params.to = toDate
        const { data } = await api.get('/training-plan/calendar', { params })
        this.calendarDays = data.days || []
        this.calendarRaces = data.races || []
        this.calendarActivities = data.activities || []
        this.calendarWindow = data.window || null
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        return null
      } finally {
        this.loading = false
      }
    },

    async addCalendarWorkout(date, payload) {
      this.error = null
      try {
        const { data } = await api.post('/training-plan/calendar/days', { date, ...payload })
        // Patch the in-memory calendar list. Replace any existing entry for
        // (date, plan_id), otherwise append and re-sort.
        const idx = this.calendarDays.findIndex(d => d.date === data.date && d.plan_id === data.plan_id)
        const entry = {
          date: data.date,
          plan_id: data.plan_id,
          plan_name: data.plan_name,
          race_id: data.race_id,
          week_number: data.week_number,
          day: data.day,
          ...data.day_obj,
        }
        if (idx !== -1) {
          this.calendarDays[idx] = entry
        } else {
          this.calendarDays.push(entry)
          this.calendarDays.sort((a, b) => a.date.localeCompare(b.date))
        }
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async moveCalendarWorkout(fromDate, toDate) {
      this.error = null
      try {
        const { data } = await api.post('/training-plan/calendar/move', { from_date: fromDate, to_date: toDate })
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async deletePlan(id) {
      this.error = null
      try {
        await api.delete(`/training-plan/${id}`)
        this.plans = this.plans.filter(p => p.id !== id)
        if (this.currentPlan?.id === id) {
          this.currentPlan = null
          this.compliance = null
        }
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      }
    },
  },
})
