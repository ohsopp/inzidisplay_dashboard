import React, { useState } from 'react'
import { apiFetch } from '../utils/api'

export default function AppHeader({
  serverConnected,
  parquetEnabled,
  onParquetEnabledChange,
  onOpenCsvExport,
}) {
  const [parquetToggleLoading, setParquetToggleLoading] = useState(false)

  const toggleParquetWrite = async () => {
    if (parquetToggleLoading) return
    const next = !parquetEnabled
    setParquetToggleLoading(true)
    try {
      const res = await apiFetch('/api/parquet/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || data.message || `오류 ${res.status}`)
      onParquetEnabledChange(Boolean(data.enabled))
    } catch (e) {
      alert(e.message || 'Parquet 저장 상태 변경 실패')
    } finally {
      setParquetToggleLoading(false)
    }
  }

  return (
    <header className="header">
      <div className="logo">
        <span className="logo-icon">◉</span>
        <h1>MC Protocol(3E) & MQTT(IOLink)</h1>
      </div>
      <div className="header-actions">
        <button
          type="button"
          className={`btn parquet-toggle-btn ${parquetEnabled ? 'is-stop' : 'is-start'}`}
          onClick={toggleParquetWrite}
          disabled={parquetToggleLoading}
        >
          {parquetToggleLoading ? '처리 중…' : parquetEnabled ? 'Parquet 저장 중지' : 'Parquet 저장 시작'}
        </button>
        <button type="button" className="btn csv-export-btn" onClick={onOpenCsvExport}>
          Data Export
        </button>
        <div className={`status-badge ${serverConnected ? 'online' : 'offline'}`}>
          {serverConnected ? '서버 연결됨' : '서버 연결 끊김'}
        </div>
      </div>
    </header>
  )
}
