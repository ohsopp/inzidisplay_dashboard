import json
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MC_FAKE_VALUES_PATH = SCRIPT_DIR / "mc_fake_values.json"

_LOCK = threading.Lock()

# 사용자 요청 범위
_CUSTOM_RANGES = {
    "D711": (3500, 8000),
    "D511": (3500, 8000),
    "D713": (20, 70),
    "D513": (20, 70),
    "D140": (1, 99),
    "D510": (1, 99),
    "D100": (0, 360),
}


def _load_values_unlocked():
    if not MC_FAKE_VALUES_PATH.exists():
        return {}
    with open(MC_FAKE_VALUES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return data


def _save_values_unlocked(data):
    with open(MC_FAKE_VALUES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _normalize_data_type(raw):
    return str(raw or "").strip().lower()


def _value_range(address_key, data_type):
    t = _normalize_data_type(data_type)
    if address_key in _CUSTOM_RANGES:
        return _CUSTOM_RANGES[address_key]
    if t == "boolean":
        return (0, 1)
    if t == "word":
        return (0, 65535)
    if t == "dword":
        return (0, 4294967295)
    return (None, None)


def list_editable_entries():
    with _LOCK:
        data = _load_values_unlocked()
    entries = []
    for address_key, entry in data.items():
        if not isinstance(entry, dict) or str(address_key).startswith("_"):
            continue
        data_type = _normalize_data_type(entry.get("dataType"))
        min_value, max_value = _value_range(address_key, data_type)
        entries.append(
            {
                "address": address_key,
                "name": entry.get("name") or address_key,
                "dataType": data_type or "word",
                "length": int(entry.get("length") or 1),
                "value": entry.get("value"),
                "min": min_value,
                "max": max_value,
            }
        )
    entries.sort(key=lambda x: x["name"])
    return entries


def apply_updates(updates):
    """
    updates: [{name: str, value: any}, ...]
    returns: (applied_list, error_list)
    applied item: {name, address, value}
    error item: {name, reason}
    """
    if not isinstance(updates, list):
        return [], [{"name": "", "reason": "updates는 배열이어야 합니다."}]

    with _LOCK:
        data = _load_values_unlocked()

        name_to_key = {}
        for key, entry in data.items():
            if not isinstance(entry, dict) or str(key).startswith("_"):
                continue
            name = entry.get("name") or key
            name_to_key[name] = key

        applied = []
        errors = []
        for item in updates:
            if not isinstance(item, dict):
                errors.append({"name": "", "reason": "업데이트 항목 형식이 올바르지 않습니다."})
                continue

            name = str(item.get("name") or "").strip()
            if not name:
                errors.append({"name": "", "reason": "name이 비어 있습니다."})
                continue

            if name not in name_to_key:
                errors.append({"name": name, "reason": "해당 변수명을 찾을 수 없습니다."})
                continue

            key = name_to_key[name]
            entry = data.get(key) or {}
            data_type = _normalize_data_type(entry.get("dataType"))
            raw_value = item.get("value")

            if data_type == "string":
                length = int(entry.get("length") or 1)
                s = str(raw_value if raw_value is not None else "")
                encoded = s.encode("ascii", errors="replace")[:length]
                value = encoded.decode("ascii", errors="replace")
            else:
                if raw_value is None or str(raw_value).strip() == "":
                    errors.append({"name": name, "reason": "값이 비어 있습니다."})
                    continue
                try:
                    value = int(str(raw_value).strip(), 10)
                except ValueError:
                    errors.append({"name": name, "reason": "숫자 형식이 아닙니다."})
                    continue

                min_value, max_value = _value_range(key, data_type)
                if min_value is not None and value < min_value:
                    errors.append({"name": name, "reason": f"최소값 {min_value}보다 작을 수 없습니다."})
                    continue
                if max_value is not None and value > max_value:
                    errors.append({"name": name, "reason": f"최대값 {max_value}보다 클 수 없습니다."})
                    continue

            entry["value"] = value
            data[key] = entry
            applied.append({"name": name, "address": key, "value": value})

        if applied:
            _save_values_unlocked(data)

    return applied, errors
