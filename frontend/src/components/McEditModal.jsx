import React from 'react'

function McEditModal({
  isOpen,
  rows,
  addressOptionsByDevice,
  addressMap,
  loading,
  saving,
  error,
  message,
  onClose,
  onAddRow,
  onDeviceChange,
  onAddressChange,
  onValueChange,
  onRemoveRow,
  onSave,
  onReload,
}) {
  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={onClose} aria-hidden="false">
      <div className="modal mc-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mc-edit-head">
          <h3>MC 값 편집</h3>
          <button type="button" className="btn btn-secondary" onClick={onClose}>닫기</button>
        </div>
        <p className="mc-edit-hint">
          주소를 선택하고 값을 입력한 뒤 저장하면 즉시 반영됩니다. Boolean은 0/1만 허용됩니다.
        </p>
        {rows.map((row) => {
          const taken = new Set(
            rows
              .filter((r) => r.id !== row.id)
              .map((r) => String(r.address || '').trim().toUpperCase())
              .filter(Boolean)
          )
          const addresses = (addressOptionsByDevice[row.device] || [])
            .filter((item) => {
              const addr = String(item.address || '').toUpperCase()
              return addr === String(row.address || '').toUpperCase() || !taken.has(addr)
            })
          const option = addressMap[row.address]
          const rangeText = option && option.min !== null && option.min !== undefined
            ? `${option.min} ~ ${option.max}`
            : '-'
          return (
            <div key={row.id} className="mc-edit-row">
              <select
                className="mc-edit-select"
                value={row.device}
                onChange={(e) => onDeviceChange(row.id, e.target.value)}
                disabled={saving || loading}
              >
                <option value="">디바이스</option>
                {['Y', 'M', 'D']
                  .filter((device) => (addressOptionsByDevice[device] || []).length > 0)
                  .map((device) => (
                    <option key={device} value={device}>{device}</option>
                  ))}
              </select>
              <select
                className="mc-edit-select"
                value={row.address}
                onChange={(e) => onAddressChange(row.id, e.target.value)}
                disabled={saving || loading}
              >
                <option value="">항목 선택</option>
                {addresses.map((item) => (
                  <option key={item.address} value={item.address}>
                    {item.address.slice(1)} | {item.name}
                  </option>
                ))}
              </select>
              <input
                type={option?.dataType === 'string' ? 'text' : 'number'}
                className="mc-edit-input"
                value={row.value}
                onChange={(e) => onValueChange(row.id, e.target.value)}
                placeholder={option ? `현재값 ${option.value ?? '-'}` : '값'}
                disabled={saving || loading}
              />
              <span className="mc-edit-range">
                {option ? `${option.dataType} / ${rangeText}` : '-'}
              </span>
              <button
                type="button"
                className="btn btn-secondary mc-edit-remove"
                onClick={() => onRemoveRow(row.id)}
                disabled={rows.length <= 1 || saving}
              >
                삭제
              </button>
            </div>
          )
        })}
        <div className="button-row">
          <button type="button" className="btn btn-secondary" onClick={onAddRow} disabled={saving || loading}>
            + 항목 추가
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSave}
            disabled={saving || loading || !Object.keys(addressMap).length}
          >
            {saving ? '저장 중...' : '값 저장'}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onReload}
            disabled={saving || loading}
          >
            {loading ? '로딩 중...' : '목록 새로고침'}
          </button>
        </div>
        {error && <p className="error-message">{error}</p>}
        {message && <p className="mc-edit-ok">{message}</p>}
      </div>
    </div>
  )
}

export default McEditModal
