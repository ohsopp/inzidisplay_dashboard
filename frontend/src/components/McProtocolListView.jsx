import React, { useMemo } from 'react'

export default function McProtocolListView({
  mcDisplayList,
  mcValues,
  displayVariableListLength,
  getDisplayValue,
  decodeForDisplayWithReset,
  formatParsedValueAsBits,
  formatParsedValueAsHex,
  showBitsCol,
  showHexCol,
  showValueCol,
  showMetaBit,
  showMetaType,
  showMetaDesc,
}) {
  const gridTemplateColumns = useMemo(
    () =>
      [
        'minmax(180px, 1.2fr)',
        showBitsCol && 'minmax(160px, 2.5fr)',
        showHexCol && 'minmax(120px, 2fr)',
        showValueCol && 'minmax(220px, 1.3fr)',
        (showMetaBit || showMetaType || showMetaDesc) && 'minmax(340px, 1.5fr)',
      ]
        .filter(Boolean)
        .join(' '),
    [showBitsCol, showHexCol, showValueCol, showMetaBit, showMetaType, showMetaDesc]
  )

  const metaGridTemplateColumns = useMemo(
    () =>
      [showMetaBit && '56px', showMetaType && '100px', showMetaDesc && '1fr']
        .filter(Boolean)
        .join(' '),
    [showMetaBit, showMetaType, showMetaDesc]
  )

  return (
    <div className="parsed-view-body">
      {mcDisplayList.length === 0 ? (
        <p className="parsed-view-empty">
          {displayVariableListLength === 0
            ? 'io_variables.json을 불러오는 중…'
            : '해당하는 변수가 없습니다.'}
        </p>
      ) : (
        <div className="parsed-vars-grid">
          <div className="parsed-var-header" style={{ gridTemplateColumns }}>
            <span className="parsed-var-name">변수명</span>
            {showBitsCol && <span className="parsed-var-bits">2진수</span>}
            {showHexCol && <span className="parsed-var-hex">16진수</span>}
            {showValueCol && (
              <span className="parsed-var-value-wrap">
                <span className="boolean-dot-header-spacer" aria-hidden />
                <span className="parsed-var-value">값</span>
              </span>
            )}
            {(showMetaBit || showMetaType || showMetaDesc) && (
              <div
                className="parsed-var-meta-cols"
                style={{ gridTemplateColumns: metaGridTemplateColumns }}
              >
                {showMetaBit && <span className="parsed-meta-bit">비트</span>}
                {showMetaType && <span className="parsed-meta-type">타입</span>}
                {showMetaDesc && <span className="parsed-meta-desc">설명</span>}
              </div>
            )}
          </div>
          {mcDisplayList.map((row) => {
            const value = getDisplayValue(row, mcValues)
            const { name, info } = row
            const displayValue = decodeForDisplayWithReset(value, info, name)
            const isStringType = (info?.dataType ?? '').toLowerCase() === 'string'
            return (
              <div key={name} className="parsed-var-row" style={{ gridTemplateColumns }}>
                <span className="parsed-var-name" title={name}>
                  {name}
                </span>
                {showBitsCol && (
                  <span
                    className="parsed-var-bits"
                    title={formatParsedValueAsBits(value, info.length, info.dataType, false)}
                  >
                    {formatParsedValueAsBits(value, info.length, info.dataType, false)}
                  </span>
                )}
                {showHexCol && (
                  <span
                    className="parsed-var-hex"
                    title={formatParsedValueAsHex(value, info.length, info.dataType, false)}
                  >
                    {formatParsedValueAsHex(value, info.length, info.dataType, false)}
                  </span>
                )}
                {showValueCol && (
                  <span
                    className={`parsed-var-value-wrap ${isStringType ? 'parsed-var-value-wrap--string' : ''}`}
                  >
                    {(info.dataType || '').toLowerCase() === 'boolean' && (
                      <span
                        className={`boolean-dot boolean-dot--${value ? '1' : '0'}`}
                        title={value ? '1' : '0'}
                        aria-hidden
                      />
                    )}
                    <span
                      className={`parsed-var-value ${isStringType ? 'parsed-var-value--string' : ''}`}
                    >
                      {displayValue}
                    </span>
                  </span>
                )}
                {(showMetaBit || showMetaType || showMetaDesc) && (
                  <div
                    className="parsed-var-meta-cols"
                    style={{ gridTemplateColumns: metaGridTemplateColumns }}
                    title={[
                      info.dataType && `DataType: ${info.dataType}`,
                      info.scale && `scale: ${info.scale}`,
                      info.description,
                    ]
                      .filter(Boolean)
                      .join('\n')}
                  >
                    {showMetaBit && <span className="parsed-meta-bit">{info.length}bit</span>}
                    {showMetaType && (
                      <span className="parsed-meta-type">
                        {info.dataType}
                        {info.scale ? ` scale ${info.scale}` : ''}
                      </span>
                    )}
                    {showMetaDesc && (
                      <span className="parsed-meta-desc">
                        {info.description
                          ? info.description.length > 50
                            ? `${info.description.slice(0, 50)}…`
                            : info.description
                          : '-'}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
