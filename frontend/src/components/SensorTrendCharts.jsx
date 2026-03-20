import React, { useId, useMemo, useRef, useState } from 'react'
import './SensorTrendCharts.css'

const VIBRATION_LINES = [
  { key: 'v_rms', label: 'v-rms', color: '#00d4aa', unit: '' },
  { key: 'a_peak', label: 'a-peak', color: '#57e3ff', unit: '' },
  { key: 'a_rms', label: 'a-rms', color: '#ffb86c', unit: '' },
  { key: 'temperature', label: 'temperature', color: '#ff7a7a', unit: '°C' },
  { key: 'crest', label: 'crest', color: '#c084fc', unit: '' },
]

const TEMPERATURE_LINES = [
  { key: 'temperature', label: 'temperature', color: '#ff7a7a', unit: '°C' },
]

function toFiniteNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatNumber(value, digits = 2) {
  const n = toFiniteNumber(value)
  return n === null ? '-' : n.toFixed(digits)
}

function formatTime(ts) {
  const ms = Number(ts) * 1000
  if (!Number.isFinite(ms)) return '-'
  const d = new Date(ms)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

function formatAxisNumber(value) {
  const n = toFiniteNumber(value)
  if (n === null) return '-'
  const abs = Math.abs(n)
  if (abs >= 100) return n.toFixed(0)
  if (abs >= 10) return n.toFixed(1)
  return n.toFixed(2)
}

function buildIndices(total, tickCount) {
  if (total <= 0) return []
  if (total === 1) return [0]
  const count = Math.min(Math.max(tickCount, 2), total)
  const out = []
  for (let i = 0; i < count; i += 1) {
    const idx = Math.round((i / (count - 1)) * (total - 1))
    if (!out.includes(idx)) out.push(idx)
  }
  return out
}

function SensorTrendChart({ title, subtitle, points, lines, yLabel, chartType = '' }) {
  const chartId = useId().replace(/:/g, '')
  const containerRef = useRef(null)
  const [hoverIndex, setHoverIndex] = useState(null)

  const dims = { width: 1060, height: 360, top: 20, right: 26, bottom: 58, left: 72 }
  const plotWidth = dims.width - dims.left - dims.right
  const plotHeight = dims.height - dims.top - dims.bottom

  const validValues = useMemo(
    () => points.flatMap((p) => lines.map((line) => toFiniteNumber(p?.[line.key])).filter((v) => v !== null)),
    [points, lines]
  )

  const scale = useMemo(() => {
    if (!validValues.length) return null
    const rawMin = Math.min(...validValues)
    const rawMax = Math.max(...validValues)
    const range = rawMax - rawMin
    const pad = range > 0 ? range * 0.1 : Math.max(Math.abs(rawMax) * 0.15, 1)
    const min = rawMin - pad
    const max = rawMax + pad
    return { min, max, range: max - min || 1 }
  }, [validValues])

  const xAtIndex = (idx) => {
    if (points.length <= 1) return dims.left
    return dims.left + (idx / (points.length - 1)) * plotWidth
  }

  const yAtValue = (value) => dims.top + ((scale.max - value) / scale.range) * plotHeight

  const yTicks = useMemo(() => {
    if (!scale) return []
    return Array.from({ length: 5 }, (_, i) => scale.min + ((scale.max - scale.min) * i) / 4)
  }, [scale])

  const xTickIndices = useMemo(() => buildIndices(points.length, 5), [points.length])

  const paths = useMemo(() => {
    if (!scale || !points.length) return []
    return lines.map((line) => {
      let d = ''
      let drawing = false
      points.forEach((point, idx) => {
        const v = toFiniteNumber(point?.[line.key])
        if (v === null) {
          drawing = false
          return
        }
        const x = xAtIndex(idx)
        const y = yAtValue(v)
        d += `${drawing ? ' L' : ' M'} ${x.toFixed(2)} ${y.toFixed(2)}`
        drawing = true
      })
      return { ...line, d: d.trim() }
    })
  }, [scale, points, lines])

  const hoverPoint = hoverIndex == null ? null : points[hoverIndex]
  const hoverX = hoverIndex == null ? null : xAtIndex(hoverIndex)
  const latestPoint = points.length ? points[points.length - 1] : null
  const tooltipLeft = useMemo(() => {
    if (hoverX == null) return 50
    const pct = ((hoverX - dims.left) / Math.max(plotWidth, 1)) * 100
    return Math.max(10, Math.min(90, pct))
  }, [hoverX, dims.left, plotWidth])

  const handleMouseMove = (event) => {
    if (!containerRef.current || points.length === 0) return
    const rect = containerRef.current.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(rect.width, 1)))
    const idx = Math.round(ratio * (points.length - 1))
    setHoverIndex(idx)
  }

  return (
    <article className={`sensor-trend-card ${chartType ? `sensor-trend-card-${chartType}` : ''}`}>
      <div className="sensor-trend-card-head">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <div className="sensor-trend-legend">
          {lines.map((line) => (
            <span key={line.key}>
              <i style={{ backgroundColor: line.color }} aria-hidden />
              {line.label}
            </span>
          ))}
        </div>
      </div>
      {latestPoint && (
        <div className="sensor-trend-latest-strip">
          <span className="sensor-trend-latest-time">{formatTime(latestPoint.ts)}</span>
          <div className="sensor-trend-latest-values">
            {lines.map((line) => (
              <span key={`latest-${line.key}`}>
                <i style={{ backgroundColor: line.color }} aria-hidden />
                {line.label} {formatNumber(latestPoint[line.key], 2)}{line.unit}
              </span>
            ))}
          </div>
        </div>
      )}

      {!scale || points.length === 0 ? (
        <div className="sensor-trend-card-empty">그래프 데이터 수집 중</div>
      ) : (
        <div
          className="sensor-trend-chart-wrap"
          ref={containerRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
        >
          <svg viewBox={`0 0 ${dims.width} ${dims.height}`} className="sensor-trend-chart-svg" preserveAspectRatio="xMidYMid meet" aria-label={title}>
            <defs>
              {lines.map((line) => (
                <linearGradient key={line.key} id={`${chartId}-${line.key}-grad`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={line.color} stopOpacity="0.22" />
                  <stop offset="100%" stopColor={line.color} stopOpacity="0.02" />
                </linearGradient>
              ))}
            </defs>

            <rect x={dims.left} y={dims.top} width={plotWidth} height={plotHeight} className="sensor-grid-bg" />

            {yTicks.map((tick) => {
              const y = yAtValue(tick)
              return (
                <g key={`y-${tick}`}>
                  <line x1={dims.left} y1={y} x2={dims.width - dims.right} y2={y} className="sensor-grid-line" />
                  <text x={dims.left - 14} y={y + 4} textAnchor="end" className="sensor-axis-value">{formatAxisNumber(tick)}</text>
                </g>
              )
            })}

            {xTickIndices.map((idx) => {
              const x = xAtIndex(idx)
              return (
                <g key={`x-${idx}`}>
                  <line x1={x} y1={dims.top} x2={x} y2={dims.height - dims.bottom} className="sensor-grid-line-x" />
                  <text x={x} y={dims.height - dims.bottom + 18} textAnchor="middle" className="sensor-axis-value">
                    {formatTime(points[idx]?.ts)}
                  </text>
                </g>
              )
            })}

            <line x1={dims.left} y1={dims.height - dims.bottom} x2={dims.width - dims.right} y2={dims.height - dims.bottom} className="sensor-axis-line" />
            <line x1={dims.left} y1={dims.top} x2={dims.left} y2={dims.height - dims.bottom} className="sensor-axis-line" />

            {paths.map((line) => (
              line.d ? (
                <path key={`${line.key}-line`} d={line.d} className="sensor-line" stroke={line.color} />
              ) : null
            ))}

            {hoverX !== null && (
              <line x1={hoverX} y1={dims.top} x2={hoverX} y2={dims.height - dims.bottom} className="sensor-hover-line" />
            )}

            {hoverIndex != null && lines.map((line) => {
              const v = toFiniteNumber(hoverPoint?.[line.key])
              if (v === null) return null
              return (
                <circle
                  key={`${line.key}-dot`}
                  cx={xAtIndex(hoverIndex)}
                  cy={yAtValue(v)}
                  r="4.3"
                  className="sensor-hover-dot"
                  fill={line.color}
                />
              )
            })}

            <text x={(dims.left + dims.width - dims.right) / 2} y={dims.height - 12} textAnchor="middle" className="sensor-axis-label">
              Time (KST)
            </text>
            <text
              x={22}
              y={dims.top + plotHeight / 2}
              textAnchor="middle"
              transform={`rotate(-90 22 ${dims.top + plotHeight / 2})`}
              className="sensor-axis-label"
            >
              {yLabel}
            </text>
          </svg>

          {hoverPoint && (
            <div
              className="sensor-tooltip"
              style={{ left: `${tooltipLeft}%` }}
            >
              <div className="sensor-tooltip-time">{formatTime(hoverPoint.ts)}</div>
              {lines.map((line) => (
                <div key={`tip-${line.key}`} className="sensor-tooltip-row">
                  <span className="sensor-tooltip-key">
                    <i style={{ backgroundColor: line.color }} aria-hidden />
                    {line.label}
                  </span>
                  <strong>
                    {formatNumber(hoverPoint[line.key], 2)}
                    {line.unit}
                  </strong>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  )
}

function SensorTrendCharts({ vibrationTrend, temperatureTrend }) {
  return (
    <section className="sensor-trends-section">
      <SensorTrendChart
        title="VVB001 Multi-Metric Trend"
        subtitle="v-rms, a-peak, a-rms, temperature, crest"
        points={vibrationTrend}
        lines={VIBRATION_LINES}
        yLabel="Vibration"
        chartType="vibration"
      />
      <SensorTrendChart
        title="TP3237 Temperature Trend"
        subtitle="single channel temperature"
        points={temperatureTrend}
        lines={TEMPERATURE_LINES}
        yLabel="Temperature (°C)"
        chartType="temperature"
      />
    </section>
  )
}

export default SensorTrendCharts
