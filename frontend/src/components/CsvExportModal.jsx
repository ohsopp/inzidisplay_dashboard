import React, { useEffect, useState } from 'react'
import { apiFetch } from '../utils/api'

function formatKstForInput(d) {
  const dateStr = d.toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' })
  const timeStr = d.toLocaleTimeString('en-GB', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return `${dateStr}T${timeStr}`
}

function kstInputToIso(s) {
  return new Date(s.trim() + ':00+09:00').toISOString()
}

export default function CsvExportModal({ open, onClose }) {
  const [csvExportStart, setCsvExportStart] = useState('')
  const [csvExportEnd, setCsvExportEnd] = useState('')
  const [csvExportGroup, setCsvExportGroup] = useState('50ms')
  const [csvExportError, setCsvExportError] = useState('')
  const [csvExportLoading, setCsvExportLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    const now = new Date()
    const end = new Date(now)
    const start = new Date(now.getTime() - 1 * 60 * 60 * 1000)
    setCsvExportStart(formatKstForInput(start))
    setCsvExportEnd(formatKstForInput(end))
    setCsvExportError('')
  }, [open])

  const setQuickRange = (minutes) => {
    const end = new Date()
    const start = new Date(end.getTime() - minutes * 60 * 1000)
    setCsvExportStart(formatKstForInput(start))
    setCsvExportEnd(formatKstForInput(end))
  }

  const handleDownload = async () => {
    const start = csvExportStart.trim()
    const end = csvExportEnd.trim()
    const group = csvExportGroup || '50ms'
    if (!start || !end) {
      setCsvExportError('시작 시간과 종료 시간을 입력하세요.')
      return
    }
    const startISO = encodeURIComponent(kstInputToIso(start))
    const endISO = encodeURIComponent(kstInputToIso(end))
    const groupEnc = encodeURIComponent(group)
    setCsvExportError('')
    setCsvExportLoading(true)
    try {
      const res = await apiFetch(`/api/influxdb/export-csv?start=${startISO}&end=${endISO}&group=${groupEnc}`, {
        method: 'GET',
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setCsvExportError(data.error || `오류 ${res.status}`)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const safe = (s) => String(s).replace(/:/g, '-')
      const filename = `${safe(start)}_${safe(end)}_${group}.csv`
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      onClose()
    } catch (e) {
      setCsvExportError(e.message || '다운로드 실패')
    } finally {
      setCsvExportLoading(false)
    }
  }

  if (!open) return null

  return (
    <div className="modal-overlay csv-export-overlay" onClick={onClose} aria-hidden="false">
      <div className="modal csv-export-modal" onClick={(e) => e.stopPropagation()}>
        <div className="csv-modal-header">
          <h3 className="csv-modal-title">CSV보내기</h3>
          <p className="csv-modal-subtitle">InfluxDB 저장 데이터를 기간·폴링 그룹별로 다운로드합니다. (KST 기준)</p>
        </div>
        <section className="csv-modal-section">
          <span className="csv-modal-label">폴링 주기 그룹</span>
          <div className="csv-group-options" role="group" aria-label="폴링 주기 선택">
            {['50ms', '1s'].map((g) => (
              <button
                key={g}
                type="button"
                className={`csv-group-option ${csvExportGroup === g ? 'active' : ''}`}
                onClick={() => setCsvExportGroup(g)}
              >
                {g}
              </button>
            ))}
          </div>
        </section>
        <section className="csv-modal-section csv-section-datetime">
          <span className="csv-modal-label">
            조회 기간
            <em className="csv-label-tz">KST</em>
          </span>
          <div className="csv-datetime-block">
            <div className="csv-datetime-field">
              <label htmlFor="csv-start">시작 시간</label>
              <input
                id="csv-start"
                type="datetime-local"
                value={csvExportStart}
                onChange={(e) => setCsvExportStart(e.target.value)}
                aria-label="시작 일시 (KST)"
              />
            </div>
            <span className="csv-datetime-arrow" aria-hidden="true">→</span>
            <div className="csv-datetime-field">
              <label htmlFor="csv-end">종료 시간</label>
              <input
                id="csv-end"
                type="datetime-local"
                value={csvExportEnd}
                onChange={(e) => setCsvExportEnd(e.target.value)}
                aria-label="종료 일시 (KST)"
              />
            </div>
          </div>
          <div className="csv-quick-range">
            <span className="csv-quick-label">빠른 선택</span>
            <div className="csv-quick-btns">
              {[
                [1, '최근 1분'],
                [5, '최근 5분'],
                [30, '최근 30분'],
                [60, '최근 1시간'],
                [24 * 60, '최근 24시간'],
              ].map(([mins, label]) => (
                <button key={mins} type="button" className="csv-quick-btn" onClick={() => setQuickRange(mins)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        </section>
        {csvExportError && <p className="csv-modal-error">{csvExportError}</p>}
        <div className="csv-modal-actions">
          <button type="button" className="btn btn-secondary csv-modal-cancel" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="btn btn-primary csv-modal-download"
            onClick={handleDownload}
            disabled={csvExportLoading}
          >
            {csvExportLoading ? '다운로드 중…' : 'CSV 다운로드'}
          </button>
        </div>
      </div>
    </div>
  )
}
