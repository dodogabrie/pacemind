import { defineStore } from 'pinia'
import api from '../services/api'

// Resolve the base URL the api client is configured with so we can hit
// streaming endpoints with native fetch (axios buffers the body and would
// defeat the point of an NDJSON stream).
function streamUrl(path) {
  const base = api.defaults.baseURL || ''
  return base.replace(/\/$/, '') + path
}

export const useRoutesStore = defineStore('routes', {
  state: () => ({
    routes: [],
    currentRoute: null,
    trainingLocation: null,
    locations: [],
    loading: false,
    error: null,
  }),

  getters: {
    hasTrainingLocation(state) {
      return state.trainingLocation?.lat != null
    },
  },

  actions: {
    async downloadGpx(id, name) {
      const { data } = await api.get(`/routes/${id}/gpx`, { responseType: 'blob' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(data)
      a.download = `${(name || 'route').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'route'}.gpx`
      a.click()
      URL.revokeObjectURL(a.href)
    },

    async fetchRoutes() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/routes/')
        this.routes = data.routes || []
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      } finally {
        this.loading = false
      }
    },

    async fetchRoute(id) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get(`/routes/${id}`)
        this.currentRoute = data
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        return null
      } finally {
        this.loading = false
      }
    },

    async importFromStrava(activityId, name) {
      this.error = null
      try {
        const { data } = await api.post(`/routes/from-strava/${activityId}`, { name })
        this.routes.unshift(data)
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async generateRoute(params) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.post('/routes/generate', params)
        this.routes.unshift(data)
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      } finally {
        this.loading = false
      }
    },

    /**
     * Stream a loop generation: invokes onProgress for every {type,...} event
     * received from the backend, resolves with the saved route on 'complete',
     * rejects on 'error' or transport failure.
     */
    async generateRouteStreaming(params, onProgress) {
      this.loading = true
      this.error = null
      let finalRoute = null
      try {
        const response = await fetch(streamUrl('/routes/generate-stream'), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params),
        })
        if (!response.ok || !response.body) {
          const text = await response.text().catch(() => '')
          throw new Error(text || `HTTP ${response.status}`)
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let nl
          while ((nl = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, nl).trim()
            buffer = buffer.slice(nl + 1)
            if (!line) continue
            let event
            try { event = JSON.parse(line) } catch (e) { continue }
            if (event.type === 'complete') {
              finalRoute = event.route
              if (finalRoute) this.routes.unshift(finalRoute)
            } else if (event.type === 'error') {
              throw new Error(event.error || 'Route generation failed')
            }
            if (onProgress) onProgress(event)
          }
        }
        if (!finalRoute) throw new Error('No route returned by stream')
        return finalRoute
      } catch (err) {
        this.error = err.message
        throw err
      } finally {
        this.loading = false
      }
    },

    async fetchFrequentRoutes(limit = 10) {
      try {
        const { data } = await api.get(`/routes/frequent?limit=${limit}`)
        return data.suggestions || []
      } catch (err) {
        return []
      }
    },

    async generateFromWaypoints(waypoints, name) {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.post('/routes/from-waypoints', { waypoints, name })
        this.routes.unshift(data)
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      } finally {
        this.loading = false
      }
    },

    async deleteRoute(id) {
      this.error = null
      try {
        await api.delete(`/routes/${id}`)
        this.routes = this.routes.filter(r => r.id !== id)
      } catch (err) {
        this.error = err.response?.data?.error || err.message
      }
    },

    async fetchTrainingLocation() {
      try {
        const { data } = await api.get('/routes/training-location')
        this.trainingLocation = data
      } catch (err) {
        this.trainingLocation = null
      }
    },

    async setTrainingLocation(lat, lon, name, radiusKm) {
      this.error = null
      try {
        const { data } = await api.put('/routes/training-location', {
          lat, lon, name, radius_km: radiusKm
        })
        this.trainingLocation = data
        return data
      } catch (err) {
        this.error = err.response?.data?.error || err.message
        throw err
      }
    },

    async fetchLocations() {
      try {
        const { data } = await api.get('/routes/locations')
        this.locations = data.locations || []
      } catch (err) {
        this.locations = []
      }
    },

    // Create (no id) or update a place; weekdays taken from other places are reflected by a refetch.
    async saveLocation(loc) {
      const { id, ...body } = loc
      if (id) await api.patch(`/routes/locations/${id}`, body)
      else await api.post('/routes/locations', body)
      await this.fetchLocations()
    },

    async deleteLocation(id) {
      await api.delete(`/routes/locations/${id}`)
      await this.fetchLocations()
    },

    // Per-workout override (null = the weekday's place); the backend re-matches the route.
    async setDayLocation(planId, weekNumber, dayName, locationId) {
      const { data } = await api.put(
        `/training-plan/${planId}/weeks/${weekNumber}/days/${dayName}/location`,
        { location_id: locationId },
      )
      return data.day
    },

    async previewRoute(waypoints) {
      const { data } = await api.post('/routes/preview', { waypoints })
      return data
    },

    async searchRoutes(criteria) {
      try {
        const params = new URLSearchParams()
        if (criteria.min_distance_km) params.set('min_distance_km', criteria.min_distance_km)
        if (criteria.max_distance_km) params.set('max_distance_km', criteria.max_distance_km)
        if (criteria.min_elevation_m) params.set('min_elevation_m', criteria.min_elevation_m)
        if (criteria.max_elevation_m) params.set('max_elevation_m', criteria.max_elevation_m)
        const { data } = await api.get(`/routes/search?${params}`)
        return data.routes || []
      } catch (err) {
        return []
      }
    },

    async suggestRoutes({ workout_type, target_distance_km, target_elevation_m }) {
      try {
        const params = new URLSearchParams()
        if (workout_type) params.set('workout_type', workout_type)
        if (target_distance_km) params.set('target_distance_km', target_distance_km)
        if (target_elevation_m) params.set('target_elevation_m', target_elevation_m)
        const { data } = await api.get(`/routes/suggest?${params}`)
        return data.suggestions || []
      } catch (err) {
        return []
      }
    },

    async toggleFavorite(routeId) {
      const route = this.routes.find(r => r.id === routeId)
      if (!route) return
      const tags = route.tags || []
      const isFav = tags.includes('favorite')
      const newTags = isFav ? tags.filter(t => t !== 'favorite') : [...tags, 'favorite']
      try {
        await api.patch(`/routes/${routeId}`, { tags: newTags })
        route.tags = newTags
      } catch (err) {
        // revert silently
      }
    },
  },
})
