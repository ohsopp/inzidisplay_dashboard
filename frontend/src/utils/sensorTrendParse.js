export const SENSOR_TREND_MAX_POINTS = 240

export function toFiniteNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function parseVibrationTrendPoint(value) {
  if (!value || typeof value !== 'object') return null
  const point = {
    v_rms: toFiniteNumber(value.v_rms),
    a_peak: toFiniteNumber(value.a_peak),
    a_rms: toFiniteNumber(value.a_rms),
    temperature: toFiniteNumber(value.temperature),
    crest: toFiniteNumber(value.crest),
  }
  const hasAny = Object.values(point).some((v) => v !== null)
  return hasAny ? point : null
}

export function parseTemperatureTrendPoint(value) {
  if (value && typeof value === 'object') {
    const inner = value && typeof value.payload === 'object' ? value.payload : value
    const n = toFiniteNumber(inner.data ?? inner.value ?? inner.temperature ?? inner.vibration)
    return n === null ? null : { temperature: n }
  }
  const n = toFiniteNumber(value)
  return n === null ? null : { temperature: n }
}
