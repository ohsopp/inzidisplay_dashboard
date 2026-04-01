import React, { useCallback, useMemo, useState } from 'react'
import './McProtocolCardView.css'

const STORAGE_KEY = 'mcProtocolCardHiddenNames'

function IconEyeOff({ className }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19 12 19c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0 1 12 5c4.756 0 8.773 2.663 10.065 7.022a10.497 10.497 0 0 1-5.307 5.307M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
    </svg>
  )
}

function IconEye({ className }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function loadHiddenFromStorage() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.filter((x) => typeof x === 'string' && x.length))
  } catch {
    return new Set()
  }
}

function saveHiddenToStorage(set) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]))
  } catch {
    // ignore quota / private mode
  }
}

/**
 * MC Protocol 변수 목록을 카드 그리드로 표시. 카드별 숨김은 localStorage에 유지됩니다.
 * 표시 열 옵션은 MC Protocol 표 탭과 동일한 state를 공유합니다.
 */
export default function McProtocolCardView({
  mcDisplayList,
  mcValues,
  mcConnected,
  mcError,
  displayVariableListLength,
  getDisplayValue,
  decodeForDisplayWithReset,
  formatParsedValueAsBits,
  formatParsedValueAsHex,
  showBitsCol,
  setShowBitsCol,
  showHexCol,
  setShowHexCol,
  showValueCol,
  setShowValueCol,
  showMetaBit,
  setShowMetaBit,
  showMetaType,
  setShowMetaType,
  showMetaDesc,
  setShowMetaDesc,
  onOpenMcEdit,
}) {
  const [hiddenNames, setHiddenNames] = useState(() =>
    typeof window !== 'undefined' ? loadHiddenFromStorage() : new Set()
  )

  const hideCard = useCallback((name) => {
    setHiddenNames((prev) => {
      const next = new Set(prev)
      next.add(name)
      saveHiddenToStorage(next)
      return next
    })
  }, [])

  const showCard = useCallback((name) => {
    setHiddenNames((prev) => {
      const next = new Set(prev)
      next.delete(name)
      saveHiddenToStorage(next)
      return next
    })
  }, [])

  const showAllCards = useCallback(() => {
    setHiddenNames(() => {
      const next = new Set()
      saveHiddenToStorage(next)
      return next
    })
  }, [])

  const hideAllCards = useCallback(() => {
    setHiddenNames(() => {
      const next = new Set(mcDisplayList.map((r) => r.name))
      saveHiddenToStorage(next)
      return next
    })
  }, [mcDisplayList])

  const visibleRows = useMemo(
    () => mcDisplayList.filter((row) => !hiddenNames.has(row.name)),
    [mcDisplayList, hiddenNames]
  )

  /** io_variables / mcDisplayList 정의 순서 유지 */
  const hiddenList = useMemo(
    () => mcDisplayList.map((r) => r.name).filter((name) => hiddenNames.has(name)),
    [hiddenNames, mcDisplayList]
  )

  return (
    <section className="parsed-view mc-view mc-protocol-card-section">
      <div className="parsed-view-header mc-protocol-card-header">
        <div className="parsed-view-title-row mc-protocol-card-title-row">
          <div className="mc-protocol-card-title-block">
            <h2>MC Protocol (card)</h2>
            <p className="mc-protocol-card-hint">
              폴링 시작·중지는 &quot;MC Protocol&quot; 탭에서 가능합니다. 숨긴 카드는 이 브라우저에만 저장됩니다.
            </p>
          </div>
          <div className="mc-protocol-card-header-actions">
            <span
              className={`mc-protocol-card-pill ${mcConnected ? 'mc-protocol-card-pill--on' : 'mc-protocol-card-pill--off'}`}
            >
              {mcConnected ? 'MC 폴링 중' : 'MC 미연결'}
            </span>
            <button type="button" className="btn btn-secondary" onClick={onOpenMcEdit}>
              값 편집
            </button>
          </div>
        </div>
        <div className="mc-protocol-card-toolbar-wrap">
          <div className="parsed-meta-toolbar mc-protocol-card-toolbar">
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
          {mcDisplayList.length > 0 && (
            <details className="mc-protocol-card-hidden-pop">
              <summary className="mc-protocol-card-hidden-trigger">
                <span className="mc-protocol-card-hidden-trigger-label">숨김처리 된 항목</span>
                <span className="mc-protocol-card-hidden-badge">{hiddenList.length}</span>
                <span className="mc-protocol-card-hidden-chevron" aria-hidden>
                  ▾
                </span>
              </summary>
              <div className="mc-protocol-card-hidden-pop-panel">
                <div className="mc-protocol-card-bulk-actions">
                  <button
                    type="button"
                    className="mc-protocol-card-bulk-btn"
                    disabled={hiddenList.length === 0}
                    onClick={(e) => {
                      e.preventDefault()
                      showAllCards()
                    }}
                  >
                    전체 표시
                  </button>
                  <button
                    type="button"
                    className="mc-protocol-card-bulk-btn"
                    disabled={visibleRows.length === 0}
                    onClick={(e) => {
                      e.preventDefault()
                      hideAllCards()
                    }}
                  >
                    전체 숨기기
                  </button>
                </div>
                {hiddenList.length > 0 ? (
                  <div className="mc-protocol-card-hidden-chips">
                    {hiddenList.map((name) => (
                      <button
                        key={name}
                        type="button"
                        className="mc-protocol-card-hidden-chip"
                        title={name}
                        onClick={() => showCard(name)}
                      >
                        <IconEye className="mc-protocol-card-hidden-chip-icon" />
                        <span className="mc-protocol-card-hidden-chip-text">{name}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="mc-protocol-card-hidden-empty">숨긴 카드가 없습니다. 개별 숨기기는 각 카드의 눈 아이콘을 누르세요.</p>
                )}
              </div>
            </details>
          )}
        </div>
        {mcError && <p className="error-message mc-protocol-card-error">{mcError}</p>}
      </div>
      <div className="parsed-view-body mc-protocol-card-body">
        {mcDisplayList.length === 0 ? (
          <p className="parsed-view-empty">
            {displayVariableListLength === 0 ? 'io_variables.json을 불러오는 중…' : '해당하는 변수가 없습니다.'}
          </p>
        ) : visibleRows.length === 0 ? (
          <p className="parsed-view-empty">표시할 카드가 없습니다. 위에서 숨긴 항목을 다시 켜 주세요.</p>
        ) : (
          <div className="mc-protocol-card-grid">
            {visibleRows.map((row) => {
              const value = getDisplayValue(row, mcValues)
              const { name, info } = row
              const displayValue = decodeForDisplayWithReset(value, info, name)
              const dt = (info?.dataType ?? '').toLowerCase()
              const isBoolean = dt === 'boolean'
              const isStringType = dt === 'string'
              const bits = formatParsedValueAsBits(value, info.length, info.dataType, false)
              const hex = formatParsedValueAsHex(value, info.length, info.dataType, false)
              const showAuxBlock =
                (showBitsCol && bits) ||
                (showHexCol && hex) ||
                showMetaBit ||
                showMetaType
              const typeDisplay =
                `${info.dataType || ''}${info.scale ? ` scale ${info.scale}` : ''}`.trim() || '—'
              const descText = info.description
                ? info.description.length > 50
                  ? `${info.description.slice(0, 50)}…`
                  : info.description
                : '-'

              return (
                <article key={name} className="mc-protocol-card-item">
                  <div className="mc-protocol-card-item-top">
                    <span className="mc-protocol-card-item-name" title={name}>
                      {name}
                    </span>
                    <button
                      type="button"
                      className="mc-protocol-card-eye-btn"
                      title="카드에서 숨기기"
                      aria-label={`${name} 카드 숨기기`}
                      onClick={() => hideCard(name)}
                    >
                      <IconEyeOff className="mc-protocol-card-eye-btn-icon" />
                    </button>
                  </div>
                  {showAuxBlock && (
                    <div className="mc-protocol-card-aux">
                      {showBitsCol && bits && (
                        <div className="mc-protocol-card-aux-line" title="2진수">
                          <span className="mc-protocol-card-aux-label">2진수</span>
                          <span className="mc-protocol-card-aux-val">{bits}</span>
                        </div>
                      )}
                      {showHexCol && hex && (
                        <div className="mc-protocol-card-aux-line" title="16진수">
                          <span className="mc-protocol-card-aux-label">16진수</span>
                          <span className="mc-protocol-card-aux-val">{hex}</span>
                        </div>
                      )}
                      {showMetaBit && (
                        <div
                          className="mc-protocol-card-aux-line"
                          title="비트 길이"
                        >
                          <span className="mc-protocol-card-aux-label">비트</span>
                          <span className="mc-protocol-card-aux-val">{info.length}bit</span>
                        </div>
                      )}
                      {showMetaType && (
                        <div
                          className="mc-protocol-card-aux-line"
                          title={[info.dataType && `DataType: ${info.dataType}`, info.scale && `scale: ${info.scale}`]
                            .filter(Boolean)
                            .join('\n')}
                        >
                          <span className="mc-protocol-card-aux-label">타입</span>
                          <span className="mc-protocol-card-aux-val">{typeDisplay}</span>
                        </div>
                      )}
                    </div>
                  )}
                  {showValueCol && (
                    <div
                      className={`mc-protocol-card-value-row ${isStringType ? 'mc-protocol-card-value-row--string' : ''}`}
                    >
                      {isBoolean && (
                        <span
                          className={`boolean-dot boolean-dot--${value ? '1' : '0'}`}
                          title={value ? '1' : '0'}
                          aria-hidden
                        />
                      )}
                      <span
                        className={`mc-protocol-card-value ${isStringType ? 'mc-protocol-card-value--string' : ''}`}
                      >
                        {displayValue}
                      </span>
                    </div>
                  )}
                  {showMetaDesc && (
                    <div
                      className="mc-protocol-card-meta"
                      title={info.description || undefined}
                    >
                      <span className="parsed-meta-desc mc-protocol-card-meta-desc">{descText}</span>
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
