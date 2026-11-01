/**
 * Shared formatting utilities used across components and views.
 */

/**
 * Format a decimal pace (min/km) as "Xm YYs/km".
 * @param {number} paceDecimal - Pace in decimal minutes per km (e.g. 5.5)
 * @returns {string} Formatted pace string
 */
export function formatPace(paceDecimal) {
  if (paceDecimal == null) return '—'
  const minutes = Math.floor(paceDecimal)
  const seconds = Math.round((paceDecimal - minutes) * 60)
  return `${minutes}m${seconds.toString().padStart(2, '0')}s/km`
}

/**
 * Format a decimal pace as "M:SS" (compact, no unit suffix).
 * Used in tables and charts where the /km unit is shown in headers.
 * @param {number} pace - Pace in decimal minutes per km
 * @returns {string}
 */
export function formatPaceCompact(pace) {
  if (pace == null) return '—'
  const baseMinutes = Math.floor(pace)
  const rawSeconds = Math.round((pace - baseMinutes) * 60)
  // Handle rounding edge case: 4.999... → rawSeconds=60
  const carry = rawSeconds === 60 ? 1 : 0
  const m = baseMinutes + carry
  const s = rawSeconds === 60 ? 0 : rawSeconds
  return `${m}:${String(s).padStart(2, '0')}`
}

/**
 * Format seconds as "H:MM:SS".
 * @param {number} seconds - Total seconds
 * @returns {string}
 */
export function formatTime(seconds) {
  if (!seconds && seconds !== 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

/**
 * Format seconds as compact stop-time string (e.g. "3m20s", "45s", "5m").
 * @param {number} totalSeconds
 * @returns {string}
 */
export function formatStopTime(totalSeconds) {
  if (totalSeconds < 60) return `${totalSeconds}s`
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  if (s === 0) return `${m}m`
  return `${m}m${s.toString().padStart(2, '0')}s`
}

/**
 * Classify terrain type from average grade (as a fraction).
 * @param {number} avgGrade - e.g. 0.08 = 8%
 * @returns {string}
 */
export function classifyTerrain(avgGrade) {
  if (avgGrade > 0.08) return 'Steep Climb'
  if (avgGrade > 0.03) return 'Climb'
  if (avgGrade > -0.03) return 'Flat'
  if (avgGrade > -0.08) return 'Descent'
  return 'Steep Descent'
}
