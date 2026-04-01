import { useEffect, useMemo, useRef, useState } from 'react'

export default function useMcEditEditor({ apiUrl, activeView }) {
  const [mcEditOptions, setMcEditOptions] = useState([])
  const [mcEditRows, setMcEditRows] = useState([{ id: 1, device: '', address: '', value: '' }])
  const [mcEditLoading, setMcEditLoading] = useState(false)
  const [mcEditSaving, setMcEditSaving] = useState(false)
  const [mcEditError, setMcEditError] = useState('')
  const [mcEditMessage, setMcEditMessage] = useState('')
  const [mcEditPopupOpen, setMcEditPopupOpen] = useState(false)
  const mcEditRowIdRef = useRef(2)

  const mcEditAddressMap = useMemo(
    () => Object.fromEntries(mcEditOptions.map((item) => [item.address, item])),
    [mcEditOptions]
  )

  const mcEditAddressOptionsByDevice = useMemo(() => {
    const out = { Y: [], M: [], D: [] }
    for (const item of mcEditOptions) {
      const address = String(item.address || '').toUpperCase()
      const device = address.slice(0, 1)
      if (!out[device]) continue
      const raw = address.slice(1)
      const base = device === 'Y' ? 16 : 10
      let num = parseInt(raw, base)
      if (!Number.isFinite(num)) num = parseInt(raw, 16)
      if (!Number.isFinite(num)) num = Number.MAX_SAFE_INTEGER
      out[device].push({ ...item, _sortNum: num, _addrRaw: raw })
    }
    for (const device of Object.keys(out)) {
      out[device].sort((a, b) => (a._sortNum - b._sortNum) || a._addrRaw.localeCompare(b._addrRaw))
    }
    return out
  }, [mcEditOptions])

  const loadMcEditOptions = async () => {
    setMcEditLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/mc/fake-values`)
      const raw = await res.text()
      let data = {}
      try {
        data = raw ? JSON.parse(raw) : {}
      } catch {
        data = {}
      }
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error('편집 API를 찾지 못했습니다. 백엔드를 재시작해 주세요.')
        }
        throw new Error(data.error || `편집 대상 목록을 불러오지 못했습니다. (HTTP ${res.status})`)
      }
      const entries = Array.isArray(data.entries) ? data.entries : []
      setMcEditOptions(entries)
      setMcEditRows((prev) => {
        if (!prev.length) return [{ id: 1, device: '', address: '', value: '' }]
        return prev.map((row) => {
          const option = row.address ? entries.find((e) => e.address === row.address) : null
          if (!option) return row
          return {
            ...row,
            device: String(option.address || '').slice(0, 1),
            address: option.address,
            value: row.value ?? String(option.value ?? ''),
          }
        })
      })
      setMcEditError('')
    } catch (err) {
      setMcEditError(err.message || '편집 대상 목록을 불러오지 못했습니다.')
    } finally {
      setMcEditLoading(false)
    }
  }

  useEffect(() => {
    if (activeView !== 'mc' && activeView !== 'mcCard') {
      setMcEditPopupOpen(false)
    }
  }, [activeView])

  const handleAddMcEditRow = () => {
    const nextId = mcEditRowIdRef.current++
    setMcEditRows((prev) => [
      ...prev,
      { id: nextId, device: '', address: '', value: '' },
    ])
  }

  const handleRemoveMcEditRow = (id) => {
    setMcEditRows((prev) => {
      if (prev.length <= 1) return prev
      return prev.filter((row) => row.id !== id)
    })
  }

  const handleMcEditDeviceChange = (id, device) => {
    setMcEditRows((prev) => {
      const taken = new Set(
        prev
          .filter((row) => row.id !== id)
          .map((row) => String(row.address || '').trim().toUpperCase())
          .filter(Boolean)
      )
      const addresses = (mcEditAddressOptionsByDevice[device] || [])
        .filter((item) => !taken.has(String(item.address || '').toUpperCase()))
      const first = addresses[0]
      return prev.map((row) => (
        row.id === id
          ? {
              ...row,
              device,
              address: first?.address || '',
              value: first ? String(first.value ?? '') : '',
            }
          : row
      ))
    })
  }

  const handleMcEditAddressChange = (id, address) => {
    const option = mcEditAddressMap[address]
    setMcEditRows((prev) => prev.map((row) => (
      row.id === id
        ? { ...row, address, value: option ? String(option.value ?? '') : '' }
        : row
    )))
  }

  const handleMcEditValueChange = (id, value) => {
    setMcEditRows((prev) => prev.map((row) => (row.id === id ? { ...row, value } : row)))
  }

  const handleMcEditSave = async () => {
    setMcEditError('')
    setMcEditMessage('')

    const updates = []
    for (const row of mcEditRows) {
      const address = String(row.address || '').trim().toUpperCase()
      if (!address) continue
      const option = mcEditAddressMap[address]
      const rawValue = String(row.value ?? '').trim()
      if (!option) continue
      const label = `${option.address} (${option.name})`
      if (!rawValue) {
        setMcEditError(`${label}: 값을 입력하세요.`)
        return
      }
      if (option.dataType !== 'string') {
        const n = Number(rawValue)
        if (!Number.isFinite(n) || !Number.isInteger(n)) {
          setMcEditError(`${label}: 정수만 입력할 수 있습니다.`)
          return
        }
        if (option.min !== null && option.min !== undefined && n < Number(option.min)) {
          setMcEditError(`${label}: 최소값은 ${option.min} 입니다.`)
          return
        }
        if (option.max !== null && option.max !== undefined && n > Number(option.max)) {
          setMcEditError(`${label}: 최대값은 ${option.max} 입니다.`)
          return
        }
      }
      updates.push({ name: option.name, value: rawValue })
    }

    if (!updates.length) {
      setMcEditError('저장할 항목을 하나 이상 선택하세요.')
      return
    }

    setMcEditSaving(true)
    try {
      const res = await fetch(`${apiUrl}/api/mc/fake-values`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates }),
      })
      const raw = await res.text()
      let data = {}
      try {
        data = raw ? JSON.parse(raw) : {}
      } catch {
        data = {}
      }
      if (!res.ok) {
        if (res.status === 404) throw new Error('편집 API를 찾지 못했습니다. 백엔드를 재시작해 주세요.')
        const detail = Array.isArray(data.errors)
          ? data.errors.map((e) => `${e.name || '-'}: ${e.reason}`).join(' / ')
          : (data.error || '저장 실패')
        throw new Error(detail)
      }
      setMcEditMessage(`${updates.length}개 항목을 저장했습니다.`)
      await loadMcEditOptions()
    } catch (err) {
      setMcEditError(err.message || '저장 실패')
    } finally {
      setMcEditSaving(false)
    }
  }

  const openMcEditPopup = async () => {
    setMcEditPopupOpen(true)
    setMcEditError('')
    setMcEditMessage('')
    await loadMcEditOptions()
  }

  const closeMcEditPopup = () => {
    setMcEditPopupOpen(false)
    setMcEditRows([{ id: 1, device: '', address: '', value: '' }])
    mcEditRowIdRef.current = 2
    setMcEditError('')
    setMcEditMessage('')
  }

  return {
    isOpen: mcEditPopupOpen,
    rows: mcEditRows,
    addressOptionsByDevice: mcEditAddressOptionsByDevice,
    addressMap: mcEditAddressMap,
    loading: mcEditLoading,
    saving: mcEditSaving,
    error: mcEditError,
    message: mcEditMessage,
    openPopup: openMcEditPopup,
    closePopup: closeMcEditPopup,
    addRow: handleAddMcEditRow,
    removeRow: handleRemoveMcEditRow,
    changeDevice: handleMcEditDeviceChange,
    changeAddress: handleMcEditAddressChange,
    changeValue: handleMcEditValueChange,
    save: handleMcEditSave,
    reload: loadMcEditOptions,
  }
}
