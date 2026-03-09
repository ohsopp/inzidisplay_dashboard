"""
MC 프로토콜(3E) 대시보드용 매핑. mc_fake_values.json에 정의된 항목을 폴링·표시.
JSON에 키(예: M300, D140)를 추가하면 해당 변수가 폴링되고 가짜 응답 서버가 value로 응답.
"""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MC_FAKE_VALUES_PATH = SCRIPT_DIR / "mc_fake_values.json"


def _parse_key(key: str) -> tuple[str, int] | None:
    '''키 "M300", "D140", "Y14C" → (device, address).'''
    if not key or key.startswith("_"):
        return None
    device = key[0].upper()
    if device not in ("Y", "M", "D"):
        return None
    addr_text = key[1:].strip().upper()
    if not addr_text:
        return None
    try:
        # Mitsubishi Y 디바이스는 16진 표기 주소를 사용한다. (예: Y107, Y14C)
        if device == "Y":
            address = int(addr_text, 16)
        elif any(ch in "ABCDEF" for ch in addr_text):
            address = int(addr_text, 16)
        else:
            address = int(addr_text, 10)
    except ValueError:
        return None
    return (device, address)


def get_mc_entries():
    """mc_fake_values.json에서 (변수명, device, address, data_type, length) 리스트 반환."""
    if not MC_FAKE_VALUES_PATH.exists():
        return []
    try:
        with open(MC_FAKE_VALUES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    result = []
    for key, entry in data.items():
        if not isinstance(entry, dict) or key.startswith("_"):
            continue
        parsed = _parse_key(key)
        if not parsed:
            continue
        device, address = parsed
        data_type = (entry.get("dataType") or "word").strip().lower()
        length = int(entry.get("length") or 1)
        name = entry.get("name") or key
        result.append((name, device, address, data_type, length))
    return result


# InfluxDB 1시간 주기 저장 대상 (50ms 폴링은 하되 저장만 1시간마다)
INFLUX_HOURLY_SAVE_NAMES = frozenset({
    "currentDieNumber_D140",
    "currentDieName_D1560", "currentDieName_D1561", "currentDieName_D1562", "currentDieName_D1563",
    "currentDieName_D1564", "currentDieName_D1565", "currentDieName_D1566", "currentDieName_D1567",
    "currentDieHeight_D711",
    "currentBalanceAirPressure_D713",
    "nextDieNumber_D510",
    "nextDieName_D549", "nextDieName_D550", "nextDieName_D551", "nextDieName_D552",
    "nextDieName_D553", "nextDieName_D554", "nextDieName_D555", "nextDieName_D556",
    "nextDieHeight_D511",
    "nextBalanceAirPressure_D513",
    "presetCounter_D1816",
    "presetCounter_D1817",
})


def get_mc_entries_by_device(device: str, exclude_hourly_d: bool = False):
    """
    device: "M" | "D" | "Y"
    exclude_hourly_d: True면 D 중 INFLUX_HOURLY_SAVE_NAMES 제외 (일반 D만)
    """
    entries = get_mc_entries()
    out = []
    for e in entries:
        name, dev, *_ = e
        if dev != device:
            continue
        if device == "D" and exclude_hourly_d and name in INFLUX_HOURLY_SAVE_NAMES:
            continue
        out.append(e)
    return out


def get_mc_entries_hourly_d():
    """D 중 1시간마다 InfluxDB에 저장할 항목만."""
    entries = get_mc_entries()
    return [e for e in entries if e[1] == "D" and e[0] in INFLUX_HOURLY_SAVE_NAMES]


def get_name_to_device() -> dict:
    """변수명 → device ("M"|"D"|"Y") 매핑. InfluxDB 기록 시 구분용."""
    entries = get_mc_entries()
    return {e[0]: e[1] for e in entries}


def num_words_from_type(data_type: str, length: int) -> int:
    t = (data_type or "").strip().lower()
    if t == "boolean":
        return max(1, (length + 15) // 16)
    if t == "word":
        return max(1, length)
    if t == "dword":
        return max(1, length * 2)
    if t == "string":
        return max(1, (length + 1) // 2)
    return max(1, length)
