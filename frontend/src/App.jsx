import React, { useState, useEffect } from 'react'
import './App.css'
import PlcDashboard from './components/PlcDashboard'
import PlcMainDashboard from './components/PlcMainDashboard'
import SensorTrendCharts from './components/SensorTrendCharts'
import McEditModal from './components/McEditModal'
import McProtocolPanel from './components/McProtocolPanel'
import AppHeader from './components/AppHeader'
import CsvExportModal from './components/CsvExportModal'
import useMcEditEditor from './hooks/useMcEditEditor'
import useDashboardEventSource from './hooks/useDashboardEventSource'
import { API_URL, apiFetch } from './utils/api'

function App() {
  const [serverConnected, setServerConnected] = useState(false)
  const [activeView, setActiveView] = useState('plcMain')
  const [ioVariableList, setIoVariableList] = useState([])
  const [mcValues, setMcValues] = useState({})
  const [mcConnected, setMcConnected] = useState(false)
  const [mcError, setMcError] = useState('')
  const [sensorTrend, setSensorTrend] = useState({ 'VVB001(A)': [], 'VVB001(B)': [] })
  const [mqttConnected, setMqttConnected] = useState(false)
  const [mqttError, setMqttError] = useState('')
  const [csvExportOpen, setCsvExportOpen] = useState(false)
  const [parquetEnabled, setParquetEnabled] = useState(true)

  const mcEdit = useMcEditEditor({ apiUrl: API_URL, activeView })

  useDashboardEventSource({
    setServerConnected,
    setMcValues,
    setMcConnected,
    setMcError,
    setSensorTrend,
    setMqttConnected,
    setMqttError,
  })

  useEffect(() => {
    fetch('/io_variables.json')
      .then((res) => res.json())
      .then((obj) => {
        const entries = Object.entries(obj).map(([name, val]) => {
          const info =
            typeof val === 'object' && val !== null && 'length' in val
              ? {
                  length: val.length,
                  dataType: val.dataType ?? '',
                  scale: val.scale ?? '',
                  description: val.description ?? '',
                }
              : { length: Number(val), dataType: '', scale: '', description: '' }
          return [name, info]
        })
        setIoVariableList(entries)
      })
      .catch(() => setIoVariableList([]))
  }, [])

  useEffect(() => {
    let cancelled = false
    const loadParquetStatus = async () => {
      try {
        const res = await apiFetch('/api/parquet/status')
        const data = await res.json().catch(() => ({}))
        if (!cancelled && res.ok) {
          setParquetEnabled(Boolean(data.enabled))
        }
      } catch {
        // no-op
      }
    }
    loadParquetStatus()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="app">
      <AppHeader
        serverConnected={serverConnected}
        parquetEnabled={parquetEnabled}
        onParquetEnabledChange={setParquetEnabled}
        onOpenCsvExport={() => setCsvExportOpen(true)}
      />
      <CsvExportModal open={csvExportOpen} onClose={() => setCsvExportOpen(false)} />
      <McEditModal
        isOpen={mcEdit.isOpen}
        rows={mcEdit.rows}
        addressOptionsByDevice={mcEdit.addressOptionsByDevice}
        addressMap={mcEdit.addressMap}
        loading={mcEdit.loading}
        saving={mcEdit.saving}
        error={mcEdit.error}
        message={mcEdit.message}
        onClose={mcEdit.closePopup}
        onAddRow={mcEdit.addRow}
        onDeviceChange={mcEdit.changeDevice}
        onAddressChange={mcEdit.changeAddress}
        onValueChange={mcEdit.changeValue}
        onRemoveRow={mcEdit.removeRow}
        onSave={mcEdit.save}
        onReload={mcEdit.reload}
      />

      <main className="main-wrap">
        <nav className="side-tabs" aria-label="화면 전환">
          <button
            type="button"
            className={`side-tab ${activeView === 'plcMain' || activeView === 'plc' ? 'active' : ''}`}
            onClick={() => setActiveView('plcMain')}
          >
            <span className="side-tab-label">PLC 대시보드</span>
            <span className="side-tab-desc">운영 현황 요약</span>
          </button>
          <button
            type="button"
            className={`side-tab ${activeView === 'mc' ? 'active' : ''}`}
            onClick={() => setActiveView('mc')}
          >
            <span className="side-tab-label">MC Protocol</span>
            <span className="side-tab-desc">MC 3E 폴링</span>
          </button>
          <button
            type="button"
            className={`side-tab ${activeView === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveView('dashboard')}
          >
            <span className="side-tab-label">센서 대시보드</span>
            <span className="side-tab-desc">MQTT 진동 2채널 실시간</span>
          </button>
        </nav>

        <div className="view-content">
          {activeView === 'plcMain' && (
            <PlcMainDashboard
              mcValues={mcValues}
              ioVariableList={ioVariableList}
              onNavigateToPlc={() => setActiveView('plc')}
            />
          )}

          {activeView === 'plc' && (
            <PlcDashboard
              mcConnected={mcConnected}
              mcValues={mcValues}
              ioVariableList={ioVariableList}
              onBackToOverview={() => setActiveView('plcMain')}
            />
          )}

          {activeView === 'mc' && (
            <McProtocolPanel
              ioVariableList={ioVariableList}
              mcValues={mcValues}
              mcConnected={mcConnected}
              mcError={mcError}
              onOpenMcEdit={mcEdit.openPopup}
            />
          )}

          {activeView === 'dashboard' && (
            <section className="parsed-view dashboard-view">
              <div className="dashboard-header">
                <h2>센서 대시보드</h2>
                <span className={`mqtt-status ${mqttConnected ? 'connected' : 'disconnected'}`}>
                  {mqttConnected ? 'MQTT 연결됨' : 'MQTT 미연결'}
                </span>
                {mqttError && <p className="dashboard-error">{mqttError}</p>}
              </div>
              <div className="dashboard-body">
                <SensorTrendCharts
                  vibrationTrendA={sensorTrend['VVB001(A)']}
                  vibrationTrendB={sensorTrend['VVB001(B)']}
                />
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
