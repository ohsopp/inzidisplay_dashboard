import React, { useState, useRef, useMemo, useCallback } from 'react'
import McProtocolCardView, {
  McProtocolCardHiddenPopover,
  loadMcCardHiddenInitial,
  persistMcCardHiddenSet,
} from './McProtocolCardView'
import McProtocolListView from './McProtocolListView'
import {
  buildDisplayVariableList,
  getDisplayValue,
  decodeForDisplayWithReset as decodeForDisplayWithResetCore,
  formatParsedValueAsBits,
  formatParsedValueAsHex,
} from '../utils/mcDisplayParse'
import { apiFetch } from '../utils/api'

export default function McProtocolPanel({
  ioVariableList,
  mcValues,
  mcConnected,
  mcError,
  onOpenMcEdit,
}) {
  const [mcSubTab, setMcSubTab] = useState('card')
  const [mcHost, setMcHost] = useState('192.168.0.5')
  const [mcPort, setMcPort] = useState('5002')
  const [localMcError, setLocalMcError] = useState('')
  const [showBitsCol, setShowBitsCol] = useState(false)
  const [showHexCol, setShowHexCol] = useState(false)
  const [showValueCol, setShowValueCol] = useState(true)
  const [showMetaBit, setShowMetaBit] = useState(false)
  const [showMetaType, setShowMetaType] = useState(false)
  const [showMetaDesc, setShowMetaDesc] = useState(true)
  const [mcCardHiddenNames, setMcCardHiddenNames] = useState(() =>
    typeof window !== 'undefined' ? loadMcCardHiddenInitial() : new Set()
  )
  const counterStartRef = useRef({})

  const handleMcCardHiddenChange = useCallback((nextSet) => {
    persistMcCardHiddenSet(nextSet)
    setMcCardHiddenNames(nextSet)
  }, [])

  const decodeForDisplayWithReset = useCallback(
    (raw, info, rowName) => decodeForDisplayWithResetCore(raw, info, rowName, counterStartRef),
    []
  )

  const displayVariableList = useMemo(
    () => buildDisplayVariableList(ioVariableList),
    [ioVariableList]
  )
  const mcDisplayList = useMemo(() => displayVariableList, [displayVariableList])

  const combinedMcError = localMcError || mcError

  const handleMcConnect = async () => {
    setLocalMcError('')
    try {
      const payload = {
        host: mcHost.trim(),
        port: parseInt(mcPort, 10) || 5002,
      }
      const res = await apiFetch('/api/mc/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (!res.ok) setLocalMcError(data.error || '연결 실패')
    } catch {
      setLocalMcError('서버에 연결할 수 없습니다.')
    }
  }

  const handleMcDisconnect = async () => {
    try {
      await apiFetch('/api/mc/disconnect', { method: 'POST' })
    } catch {
      // ignore
    }
  }

  return (
    <section className="parsed-view mc-view">
      <div className="parsed-view-header">
        <div className="parsed-view-title-row mc-view-title-row--split">
          <h2>MC Protocol (3E)</h2>
          <span
            className={`mc-protocol-card-pill ${mcConnected ? 'mc-protocol-card-pill--on' : 'mc-protocol-card-pill--off'}`}
          >
            {mcConnected ? 'MC 폴링 중' : 'MC 미연결'}
          </span>
        </div>
        <section className="control-panel mc-control">
          <div className="control-row">
            <div className="field-group">
              <label htmlFor="mc-host">IP</label>
              <input
                id="mc-host"
                type="text"
                value={mcHost}
                onChange={(e) => setMcHost(e.target.value)}
                placeholder="192.168.0.5"
                disabled={mcConnected}
              />
            </div>
            <div className="field-group">
              <label htmlFor="mc-port">포트</label>
              <input
                id="mc-port"
                type="number"
                value={mcPort}
                onChange={(e) => setMcPort(e.target.value)}
                placeholder="5002"
                min="1"
                max="65535"
                disabled={mcConnected}
              />
            </div>
          </div>
          <div className="button-row">
            <button type="button" className="btn btn-primary" onClick={handleMcConnect} disabled={mcConnected}>
              폴링 시작
            </button>
            <button type="button" className="btn btn-danger" onClick={handleMcDisconnect} disabled={!mcConnected}>
              연결 중지
            </button>
            <button type="button" className="btn btn-secondary" onClick={onOpenMcEdit}>
              값 편집
            </button>
          </div>
          {combinedMcError && <p className="error-message">{combinedMcError}</p>}
        </section>
      </div>
      <div className="mc-protocol-card-embedded-toolbar">
        <div
          className={`mc-protocol-card-embedded-toolbar-inner ${
            mcSubTab === 'card'
              ? 'mc-protocol-card-embedded-toolbar-inner--with-hidden'
              : 'mc-protocol-card-embedded-toolbar-inner--list'
          }`}
        >
          <div className="parsed-meta-toolbar mc-protocol-card-toolbar mc-protocol-card-toolbar--embedded">
            <span className="parsed-meta-toolbar-label">표시 열</span>
            <div className="parsed-meta-toolbar-checks">
              <label className="parsed-meta-check-wrap">
                <input type="checkbox" checked={showBitsCol} onChange={(e) => setShowBitsCol(e.target.checked)} /> 2진수
              </label>
              <label className="parsed-meta-check-wrap">
                <input type="checkbox" checked={showHexCol} onChange={(e) => setShowHexCol(e.target.checked)} /> 16진수
              </label>
              <label className="parsed-meta-check-wrap">
                <input type="checkbox" checked={showValueCol} onChange={(e) => setShowValueCol(e.target.checked)} /> 값
              </label>
              <label className="parsed-meta-check-wrap">
                <input type="checkbox" checked={showMetaBit} onChange={(e) => setShowMetaBit(e.target.checked)} /> 비트
              </label>
              <label className="parsed-meta-check-wrap">
                <input type="checkbox" checked={showMetaType} onChange={(e) => setShowMetaType(e.target.checked)} /> 타입
              </label>
              <label className="parsed-meta-check-wrap">
                <input type="checkbox" checked={showMetaDesc} onChange={(e) => setShowMetaDesc(e.target.checked)} /> 설명
              </label>
            </div>
          </div>
          {mcSubTab === 'card' ? (
            <McProtocolCardHiddenPopover
              mcDisplayList={mcDisplayList}
              hiddenNames={mcCardHiddenNames}
              onChange={handleMcCardHiddenChange}
            />
          ) : null}
        </div>
      </div>
      <div className="mc-view-subtabs" role="tablist" aria-label="Card / List">
        <button
          type="button"
          className={`mc-view-subtab ${mcSubTab === 'card' ? 'active' : ''}`}
          role="tab"
          aria-selected={mcSubTab === 'card'}
          onClick={() => setMcSubTab('card')}
        >
          Card
        </button>
        <button
          type="button"
          className={`mc-view-subtab ${mcSubTab === 'list' ? 'active' : ''}`}
          role="tab"
          aria-selected={mcSubTab === 'list'}
          onClick={() => setMcSubTab('list')}
        >
          List
        </button>
      </div>
      {mcSubTab === 'list' && (
        <McProtocolListView
          mcDisplayList={mcDisplayList}
          mcValues={mcValues}
          displayVariableListLength={displayVariableList.length}
          getDisplayValue={getDisplayValue}
          decodeForDisplayWithReset={decodeForDisplayWithReset}
          formatParsedValueAsBits={formatParsedValueAsBits}
          formatParsedValueAsHex={formatParsedValueAsHex}
          showBitsCol={showBitsCol}
          showHexCol={showHexCol}
          showValueCol={showValueCol}
          showMetaBit={showMetaBit}
          showMetaType={showMetaType}
          showMetaDesc={showMetaDesc}
        />
      )}
      {mcSubTab === 'card' && (
        <McProtocolCardView
          embedded
          parentHandlesColumns
          controlledHiddenNames={mcCardHiddenNames}
          onControlledHiddenChange={handleMcCardHiddenChange}
          mcDisplayList={mcDisplayList}
          mcValues={mcValues}
          mcConnected={mcConnected}
          mcError={mcError}
          displayVariableListLength={displayVariableList.length}
          getDisplayValue={getDisplayValue}
          decodeForDisplayWithReset={decodeForDisplayWithReset}
          formatParsedValueAsBits={formatParsedValueAsBits}
          formatParsedValueAsHex={formatParsedValueAsHex}
          showBitsCol={showBitsCol}
          setShowBitsCol={setShowBitsCol}
          showHexCol={showHexCol}
          setShowHexCol={setShowHexCol}
          showValueCol={showValueCol}
          setShowValueCol={setShowValueCol}
          showMetaBit={showMetaBit}
          setShowMetaBit={setShowMetaBit}
          showMetaType={showMetaType}
          setShowMetaType={setShowMetaType}
          showMetaDesc={showMetaDesc}
          setShowMetaDesc={setShowMetaDesc}
          onOpenMcEdit={onOpenMcEdit}
        />
      )}
    </section>
  )
}
