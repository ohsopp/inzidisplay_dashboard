/** MC/PLC 변수 표시용: io_variables 행 묶기, 값 맵에서 꺼내기, 2진·16진·디코딩 */

export function hexToBytes(hex) {
  const s = String(hex).replace(/\s/g, '')
  if (!/^[0-9a-fA-F]*$/.test(s) || s.length % 2 !== 0) return []
  const out = []
  for (let i = 0; i < s.length; i += 2) out.push(parseInt(s.slice(i, i + 2), 16))
  return out
}

export function toUnsigned(num, len) {
  const bits = Number(len) || 32
  const u32 = Number(num) >>> 0
  if (bits <= 8) return u32 & 0xff
  if (bits <= 16) return u32 & 0xffff
  return u32
}

export function toSigned32FromUnsigned(u) {
  const v = Number(u) >>> 0
  return v >= 0x80000000 ? v - 0x100000000 : v
}

export function decodePackedBcdFromUnsigned(u, bits) {
  const nibbleCount = Math.max(1, Math.floor((Number(bits) || 16) / 4))
  const hex = Number(u).toString(16).padStart(nibbleCount, '0').slice(-nibbleCount)
  if (!/^[0-9]+$/.test(hex)) return null
  return Number(hex)
}

/** 파싱된 raw 값을 DataType/scale에 따라 표시용으로 디코딩 */
export function decodeForDisplay(raw, info) {
  if (raw === '-' || raw === undefined || raw === null) return '-'
  const dt = (info?.dataType ?? '').toLowerCase()
  const scaleStr = String(info?.scale ?? '1').trim()
  const scaleNum = parseFloat(scaleStr) || 1
  const len = Number(info?.length) || 32

  if (dt === 'boolean') return String(Number(raw))

  if (dt === 'word' || dt === 'dword') {
    const num = Number(raw)
    if (Number.isNaN(num)) return '-'
    const u = toUnsigned(num, len)
    const isBcdMarked = /BCD/i.test(String(info?.description || ''))
    const bcd = isBcdMarked ? decodePackedBcdFromUnsigned(u, len) : null
    const base = bcd !== null ? bcd : u
    if (scaleNum === 0.1) return (base * 0.1).toFixed(1)
    if (scaleNum !== 1) return base * scaleNum
    return base
  }

  if (dt === 'string') {
    if (typeof raw === 'string') {
      return raw.replace(/\0+$/, '').trim() || '-'
    }
    let hexStr = ''
    if (typeof raw === 'number' && len === 16) {
      hexStr = (raw >>> 0).toString(16).padStart(4, '0')
    } else {
      return '-'
    }
    const bytes = hexToBytes(hexStr)
    if (!bytes.length) return '-'
    const s = String.fromCharCode(...bytes)
    return s.replace(/\0+$/, '').trim() || '-'
  }

  if (typeof raw === 'number') {
    return toUnsigned(raw, len)
  }
  return raw
}

/** 변수명에서 PLC 디바이스 그룹 추출. 예: xxx_Y14C -> 'Y', xxx_M300 -> 'M'. 없으면 null */
export function getDeviceGroup(name) {
  if (!name || typeof name !== 'string') return null
  const m = name.match(/_([YMDX])[\dA-Za-z]*$/i)
  return m ? m[1].toUpperCase() : null
}

/** Dword 쌍·String 연속(같은 이름 + 연속 D주소)을 한 행으로 묶은 표시용 리스트. */
export function buildDisplayVariableList(ioVariableList) {
  const result = []
  for (let i = 0; i < ioVariableList.length; i++) {
    const [name, info] = ioVariableList[i]
    const dt = (info?.dataType ?? '').toLowerCase()
    const len = Number(info?.length) || 0
    const next = ioVariableList[i + 1]
    const nextName = next?.[0]
    const nextInfo = next?.[1]
    const nextDt = (nextInfo?.dataType ?? '').toLowerCase()
    const nextLen = Number(nextInfo?.length) || 0
    if (dt === 'dword' && len === 16 && nextDt === 'dword' && nextLen === 16) {
      const m = name.match(/^(.+)_D(\d+)$/)
      const n = nextName && nextName.match(/^(.+)_D(\d+)$/)
      if (m && n && m[1] === n[1] && parseInt(n[2], 10) === parseInt(m[2], 10) + 1) {
        result.push({
          name,
          keys: [name, nextName],
          info: { ...info, length: 32 },
        })
        i++
        continue
      }
    }
    if (dt === 'string' && len === 16) {
      const m = name.match(/^(.+)_D(\d+)$/)
      if (m) {
        const prefix = m[1]
        let lastNum = parseInt(m[2], 10)
        const keys = [name]
        let j = i + 1
        while (j < ioVariableList.length) {
          const [nName, nInfo] = ioVariableList[j]
          const nDt = (nInfo?.dataType ?? '').toLowerCase()
          const nLen = Number(nInfo?.length) || 0
          if (nDt !== 'string' || nLen !== 16) break
          const nm = nName.match(/^(.+)_D(\d+)$/)
          if (!nm || nm[1] !== prefix || parseInt(nm[2], 10) !== lastNum + 1) break
          keys.push(nName)
          lastNum = parseInt(nm[2], 10)
          j++
        }
        if (keys.length > 1) {
          result.push({
            name,
            keys,
            info: { ...info, length: 16 * keys.length },
          })
          i = j - 1
          continue
        }
      }
    }
    result.push({ name, keys: [name], info })
  }
  return result
}

/** 표시용 행의 값. String은 연속 키를 결합하고, Dword는 첫 키 값을 표시한다. */
export function getDisplayValue(row, valueMap) {
  if (row.keys.length === 1) return valueMap[row.name]
  const dt = (row.info?.dataType ?? '').toLowerCase()
  if (dt === 'string') {
    for (const k of row.keys) {
      const v = valueMap[k]
      if (typeof v === 'string' && v.replace(/\0+$/, '').trim()) {
        return v
      }
    }
    let combined = ''
    for (const k of row.keys) {
      const v = valueMap[k]
      if (v === undefined || v === null || v === '-') continue
      if (typeof v === 'string' && /^[0-9a-fA-F]*$/.test(v)) combined += v.replace(/\s/g, '')
      else if (typeof v === 'string') combined += v
      else if (typeof v === 'number') combined += (v & 0xffff).toString(16).padStart(4, '0')
    }
    return combined || undefined
  }
  return valueMap[row.keys[0]]
}

/** Word/Dword: 음수(리셋) 시 처음 본 값을 시작값으로 표시. counterStartRef.current에 행별 시작 raw 저장 */
export function decodeForDisplayWithReset(raw, info, rowName, counterStartRef) {
  const dt = (info?.dataType ?? '').toLowerCase()
  if (rowName === 'defficiencyQuantity_D1814' || rowName === 'defficiencyQuantity_D1815') {
    if (raw === '-' || raw === undefined || raw === null) return '-'
    const num = Number(raw)
    if (!Number.isFinite(num)) return '-'
    const scaleStr = String(info?.scale ?? '1').trim()
    const scaleNum = parseFloat(scaleStr) || 1
    const signed = toSigned32FromUnsigned(toUnsigned(num, 32))
    if (scaleNum === 0.1) return (signed * 0.1).toFixed(1)
    if (scaleNum !== 1) return signed * scaleNum
    return signed
  }

  const store = counterStartRef.current
  const isCounter = dt === 'word' || dt === 'dword'
  const num = typeof raw === 'number' ? raw : parseInt(raw, 10)
  if (isCounter && typeof raw === 'number' && num >= 0 && store[rowName] === undefined) {
    store[rowName] = raw
  }
  if (isCounter && typeof raw === 'number' && num < 0) {
    const startRaw = store[rowName]
    return startRaw !== undefined ? decodeForDisplay(startRaw, info) : decodeForDisplay(raw, info)
  }
  return decodeForDisplay(raw, info)
}

function byteToBits8(b) {
  return (b & 0xff).toString(2).padStart(8, '0')
}

/** 파싱된 값을 리틀/빅엔디안에 맞춘 2진수로 표시 */
export function formatParsedValueAsBits(value, lengthBit, dataType, littleEndian) {
  const len = Number(lengthBit) || 0
  if (value === '-' || value === undefined) return ''
  const le = littleEndian ?? true
  const isStringType = String(dataType || '').toLowerCase() === 'string'
  let bits
  if (typeof value === 'number') {
    if (len <= 0 || len > 32) return ''
    const u = toUnsigned(value, len)
    if (len === 1) bits = String(u & 1)
    else if (len === 8) bits = byteToBits8(u)
    else if (len === 16) {
      const low = u & 0xff
      const high = (u >> 8) & 0xff
      bits = byteToBits8(high) + byteToBits8(low)
    } else if (len === 32) {
      const b0 = u & 0xff
      const b1 = (u >> 8) & 0xff
      const b2 = (u >> 16) & 0xff
      const b3 = (u >> 24) & 0xff
      bits = byteToBits8(b3) + byteToBits8(b2) + byteToBits8(b1) + byteToBits8(b0)
    } else if (le) {
      bits = ''
      for (let i = 0; i < len; i++) bits += (u >> i) & 1 ? '1' : '0'
    } else {
      bits = ''
      for (let i = len - 1; i >= 0; i--) bits += (u >> i) & 1 ? '1' : '0'
    }
  } else if (typeof value === 'string' && !isStringType && /^[0-9a-fA-F]+$/.test(value)) {
    const bytes = hexToBytes(value)
    if (!bytes.length) return ''
    const byteCount = Math.ceil((len || bytes.length * 8) / 8)
    let ordered = bytes.slice(0, byteCount)
    if (le && byteCount >= 2) {
      ordered = []
      for (let i = 0; i < byteCount; i += 2) {
        if (i + 1 < byteCount) ordered.push(bytes[i + 1], bytes[i])
        else ordered.push(bytes[i])
      }
    }
    bits = ordered
      .map((b) => byteToBits8(b))
      .join('')
      .slice(0, len || 999)
      .padStart(len || ordered.length * 8, '0')
  } else if (typeof value === 'string') {
    const bytes = Array.from(value).map((c) => c.charCodeAt(0) & 0xff)
    if (!bytes.length) return ''
    bits = bytes.map((b) => byteToBits8(b)).join(' ')
  } else {
    return ''
  }
  return typeof bits === 'string' && bits.includes(' ')
    ? bits
    : bits.replace(/(.{8})/g, '$1 ').trim()
}

/** 파싱된 값을 16진수 문자열로 표시 */
export function formatParsedValueAsHex(value, lengthBit, dataType, _littleEndian) {
  const len = Number(lengthBit) || 0
  if (value === '-' || value === undefined) return ''
  const isStringType = String(dataType || '').toLowerCase() === 'string'
  if (typeof value === 'number') {
    if (len <= 0) return ''
    const u = toUnsigned(value, len)
    const byteCount = Math.ceil(len / 8)
    if (byteCount <= 0) return ''
    const bytes = []
    for (let i = 0; i < byteCount; i++) {
      bytes.push((u >> (8 * i)) & 0xff)
    }
    const ordered = [...bytes].reverse()
    return ordered.map((b) => b.toString(16).padStart(2, '0').toUpperCase()).join(' ')
  }
  if (typeof value === 'string' && !isStringType && /^[0-9a-fA-F]+$/.test(value)) {
    const pairs = value.match(/.{1,2}/g) || []
    return pairs.join(' ').toUpperCase()
  }
  if (typeof value === 'string') {
    const bytes = Array.from(value).map((c) => c.charCodeAt(0) & 0xff)
    return bytes.map((b) => b.toString(16).padStart(2, '0').toUpperCase()).join(' ')
  }
  return ''
}
