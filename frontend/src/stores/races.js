import { defineStore } from 'pinia'
import api from '../services/api'

const DEFAULT_FILTERS = {
  q: '',
  start_date: '',
  end_date: '',
  country: '',
  min_distance_km: '',
  max_distance_km: '',
  min_elev_m: '',
  max_elev_m: '',
  surface: '',
  race_type: '',
  near_me: false,
  near_lat: null,
  near_lon: null,
  max_travel_km: '',
  target_distance_km: '',
  sort: 'date',
}

export const useRacesStore = defineStore('races', {
  state: () => ({
    races: [],
    currentRace: null,
    preferences: null,
    filters: { ...DEFAULT_FILTERS },
    loading: false,
    error: null,
    addingToPlan: false,
    discovering: false,
    discoverEmpty: false,
  }),

  getters: {
    hasNearMe(state) {
      return Boolean(state.preferences?.training_base_lat && state.preferences?.training_base_lon)
    },
  },

  actions: {
    resetFilters() {
      this.filters = { ...DEFAULT_FILTERS }
    },

    setFilter(key, value) {
      this.filters = { ...this.filters, [key]: value }
    },

    _buildParams() {
      const f = this.filters
      const params = {}
      const copyKeys = [
        'q', 'start_date', 'end_date', 'country',
        'min_distance_km', 'max_distance_km', 'min_elev_m', 'max_elev_m',
        'surface', 'race_type', 'sort',
        'target_distance_km',
      ]
      for (const k of copyKeys) {
        const v = f[k]
        if (v !== '' && v !== null && v !== undefined) params[k] = v
      }
      if (f.near_me && f.near_lat != null && f.near_lon != null) {
        params.near_lat = f.near_lat
        params.near_lon = f.near_lon
        if (f.max_travel_km !== '' && f.max_travel_km != null) {
          params.max_travel_km = f.max_travel_km
        }
      }
      return params
    },

    async fetchPreferences() {
      try {
        const { data } = await api.get('/races/me/preferences')
        this.preferences = data
        if (data.training_base_lat != null && data.training_base_lon != null) {
          this.filters.near_lat = data.training_base_lat
          this.filters.near_lon = data.training_base_lon
        }
        if (data.training_travel_radius_km != null && this.filters.max_travel_km === '') {
          this.filters.max_travel_km = data.training_travel_radius_km
        }
      } catch (err) {
        // 401 is fine — anonymous browsing is allowed.
        this.preferences = null
      }
    },

    async fetchRaces() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/races', { params: this._buildParams() })
        this.races = data.races || []
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      } finally {
        this.loading = false
      }
    },

    async fetchRace(id) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get(`/races/${id}`)
        this.currentRace = data.race
        return data.race
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      } finally {
        this.loading = false
      }
    },

    // Search the web for a race missing from the calendar; the backend saves
    // it (one race per course) and we show just what was found.
    async discover(q) {
      this.discovering = true
      this.discoverEmpty = false
      this.error = null
      try {
        const { data } = await api.post('/races/discover', { q }, { timeout: 120000 })
        this.races = data.races || []
        this.discoverEmpty = this.races.length === 0
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      } finally {
        this.discovering = false
      }
    },

    async addToPlan(raceId, priority, weeks = null) {
      this.addingToPlan = true
      this.error = null
      try {
        const body = { priority }
        if (weeks) body.weeks = weeks
        const { data } = await api.post(`/races/${raceId}/plan`, body)
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      } finally {
        this.addingToPlan = false
      }
    },
  },
})
