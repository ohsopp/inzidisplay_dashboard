import { useEffect, useRef } from 'react'
import { buildEventsUrl } from '../utils/api'
import {
  parseVibrationTrendPoint,
  parseTemperatureTrendPoint,
  SENSOR_TREND_MAX_POINTS,
} from '../utils/sensorTrendParse'

/**
 * MC/MQTT SSE: mc_data, mc_connected, sensor_data, mqtt_* 이벤트 구독 및 자동 재연결.
 */
export default function useDashboardEventSource({
  setServerConnected,
  setMcValues,
  setMcConnected,
  setMcError,
  setSensorTrend,
  setMqttConnected,
  setMqttError,
}) {
  const eventSourceRef = useRef(null)
  const reconnectTimerRef = useRef(null)

  useEffect(() => {
    let isUnmounted = false
    const closeEventSource = () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }

    const connectEventSource = () => {
      if (isUnmounted) return
      const es = new EventSource(buildEventsUrl())
      eventSourceRef.current = es

      es.onopen = () => {
        setServerConnected(true)
      }

      es.onerror = () => {
        setServerConnected(false)
        es.close()
        if (isUnmounted) return
        reconnectTimerRef.current = setTimeout(connectEventSource, 1500)
      }

      es.addEventListener('mc_data', (e) => {
        const data = JSON.parse(e.data || '{}')
        if (data.parsed && typeof data.parsed === 'object') {
          setMcValues((prev) => {
            const next = { ...prev }
            for (const [key, value] of Object.entries(data.parsed)) {
              if (value === '-' || value === null || value === undefined) continue
              next[key] = value
            }
            return next
          })
        }
      })

      es.addEventListener('mc_connected', () => {
        setMcConnected(true)
        setMcError('')
      })

      es.addEventListener('mc_disconnected', () => {
        setMcConnected(false)
      })

      es.addEventListener('mc_error', (e) => {
        const data = JSON.parse(e.data || '{}')
        setMcError(data.message || 'MC 프로토콜 오류')
      })

      es.addEventListener('sensor_data', (e) => {
        const data = JSON.parse(e.data || '{}')
        const topic = data.topic
        if (topic) {
          const ts = Number(data.ts) || Date.now() / 1000
          if (topic === 'VVB001') {
            const trendPoint = parseVibrationTrendPoint(data.value)
            if (trendPoint) {
              setSensorTrend((prev) => ({
                ...prev,
                VVB001: [...prev.VVB001, { ts, ...trendPoint }].slice(-SENSOR_TREND_MAX_POINTS),
              }))
            }
          } else if (topic === 'TP3237') {
            const trendPoint = parseTemperatureTrendPoint(data.value)
            if (trendPoint) {
              setSensorTrend((prev) => ({
                ...prev,
                TP3237: [...prev.TP3237, { ts, ...trendPoint }].slice(-SENSOR_TREND_MAX_POINTS),
              }))
            }
          }
          setMqttConnected(true)
        }
      })

      es.addEventListener('sensor_data_snapshot', (e) => {
        const data = JSON.parse(e.data || '{}')
        if (data && typeof data === 'object') {
          setSensorTrend((prev) => {
            const updated = { ...prev }
            for (const [topic, payload] of Object.entries(data)) {
              const ts = Number(payload?.ts) || Date.now() / 1000
              if (topic === 'VVB001') {
                const trendPoint = parseVibrationTrendPoint(payload?.value)
                if (!trendPoint) continue
                updated.VVB001 = [...updated.VVB001, { ts, ...trendPoint }].slice(-SENSOR_TREND_MAX_POINTS)
              } else if (topic === 'TP3237') {
                const trendPoint = parseTemperatureTrendPoint(payload?.value)
                if (!trendPoint) continue
                updated.TP3237 = [...updated.TP3237, { ts, ...trendPoint }].slice(-SENSOR_TREND_MAX_POINTS)
              }
            }
            return updated
          })
          if (Object.keys(data).length > 0) {
            setMqttConnected(true)
          }
        }
      })

      es.addEventListener('mqtt_connected', () => {
        setMqttConnected(true)
        setMqttError('')
      })
      es.addEventListener('mqtt_disconnected', () => setMqttConnected(false))
      es.addEventListener('mqtt_error', (e) => {
        const data = JSON.parse(e.data || '{}')
        setMqttError(data.message || 'MQTT 오류')
        setMqttConnected(false)
      })
      es.addEventListener('mqtt_status_snapshot', (e) => {
        const data = JSON.parse(e.data || '{}')
        setMqttConnected(!!data.connected)
        setMqttError(data.error || '')
      })
    }

    connectEventSource()
    window.addEventListener('pagehide', closeEventSource)
    window.addEventListener('beforeunload', closeEventSource)
    return () => {
      isUnmounted = true
      window.removeEventListener('pagehide', closeEventSource)
      window.removeEventListener('beforeunload', closeEventSource)
      closeEventSource()
    }
  }, [
    setServerConnected,
    setMcValues,
    setMcConnected,
    setMcError,
    setSensorTrend,
    setMqttConnected,
    setMqttError,
  ])
}
