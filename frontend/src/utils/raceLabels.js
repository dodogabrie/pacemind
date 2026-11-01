/**
 * Localised labels for a race's free-form category fields (`race_type`,
 * `surface`).
 *
 * These columns hold values produced by scrapers, so an unrecognised value is
 * always possible. Interpolating straight into `t()` renders the raw key
 * ("races.type.ws50KM") to the user when a translation is missing — which is
 * exactly what GH #78 was. Ingestion now normalises the known-bad vocabulary;
 * this is the last line of defence so a future unknown value degrades to
 * something readable instead of leaking a key.
 */
export function makeRaceLabel(t, te) {
  return (field, value) => {
    if (!value) return ''
    const key = `races.${field}.${value}`
    return te(key) ? t(key) : String(value)
  }
}
