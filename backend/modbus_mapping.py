"""
매핑 포맷 확장, 주소 계산 옵션, 블록 자동 그룹핑, 범용 디코더.
- io_variables.json에 modbusType/modbusAddr/plcDevice 있으면 사용, 없으면 기존 순서 기반(호환).
- modbus_options.json으로 OFFSET/base/디바이스→Modbus 변환.
"""
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# .exe 패키징 시 PyInstaller가 풀어둔 번들 루트
_BUNDLE_ROOT = getattr(sys, "_MEIPASS", None)
REPO_ROOT = Path(_BUNDLE_ROOT) if _BUNDLE_ROOT else SCRIPT_DIR.parent
IO_VARIABLES_PATH = REPO_ROOT / "io_variables.json"
MODBUS_OPTIONS_PATH = (REPO_ROOT / "modbus_options.json") if _BUNDLE_ROOT else (SCRIPT_DIR / "modbus_options.json")

# 기존 폴러와 호환: Boolean 최대 개수(Coil), 나머지는 Holding 연속
LEGACY_COIL_MAX = 107

# 한 번에 읽는 최대 개수 (연속 주소만 묶고, 구간 끊기거나 이 개수 초과 시 블록 분리)
MAX_REGISTERS_OR_COILS_PER_READ = 125


def load_options():
    """modbus_options.json 로드. 없으면 기본값."""
    defaults = {
        "address_base": 0,
        "coil_offset": 0,
        "holding_offset": 0,
        "input_reg_offset": 0,
        "discrete_offset": 0,
        "plc_device_rules": {
            "D": {"modbus_type": "holding", "offset": 0},
            "M": {"modbus_type": "coil", "offset": 0},
            "Y": {"modbus_type": "coil", "offset": 0},
            "X": {"modbus_type": "discrete", "offset": 0},
        },
    }
    if not MODBUS_OPTIONS_PATH.exists():
        return defaults
    with open(MODBUS_OPTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, v in defaults.items():
        if k not in data and k != "comment":
            data[k] = v
    return data


def load_io_variables():
    """io_variables.json 순서대로 로드. [(name, info), ...]"""
    with open(IO_VARIABLES_PATH, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return list(obj.items())


def get_device_group(name):
    """변수명에서 PLC 디바이스 접두어 추출. 예: xxx_Y14C -> 'Y', xxx_M300 -> 'M', xxx_D1820 -> 'D'. 없으면 None."""
    if not name or not isinstance(name, str):
        return None
    m = re.search(r"_([YMDX])[\dA-Za-z]*$", name.strip())
    return m.group(1).upper() if m else None


def filter_entries_by_device_group(entries, group):
    """entries [(name, info), ...]에서 group('Y'|'M'|'D'|'X')에 해당하는 것만 반환."""
    if not group or str(group).upper() not in ("Y", "M", "D", "X"):
        return entries
    g = str(group).upper()
    return [(name, info) for name, info in entries if get_device_group(name) == g]


def _reg_count_for_entry(info):
    """엔트리당 레지스터/코일 개수."""
    length = int(info.get("length", 0))
    dt = (info.get("dataType") or "").strip().lower()
    if dt == "boolean" and length == 1:
        return 1
    if dt == "word" and length == 16:
        return 1
    # Dword: PLC는 하위워드(저주소)+상위워드(고주소) 16비트씩 2레지스터로 저장
    if dt == "dword":
        return 2
    if dt == "string" and length == 128:
        return 8
    return max(1, (length + 15) // 16)


def _parse_plc_device(plc_device):
    """예: 'D100' -> ('D', 100), 'M300' -> ('M', 300)."""
    s = (plc_device or "").strip().upper()
    if not s:
        return None, None
    for prefix in ("D", "M", "Y", "X"):
        if s.startswith(prefix):
            try:
                num = int(s[len(prefix):].strip(), 10)
                return prefix, num
            except ValueError:
                return None, None
    return None, None


def _dword_half_name_to_base_and_index(name):
    """xxx_D1820 → ('xxx', 1820). Dword 16bit 쌍 병합 시 사용. 짝수 D=하위, 홀수 D=상위."""
    if "_D" not in name:
        return None, None
    parts = name.rsplit("_D", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None, None
    return parts[0], int(parts[1], 10)


def resolve_address(name, info, options, legacy_coil_index, legacy_reg_start):
    """
    한 엔트리의 Modbus (type, addr, count) 결정.
    - info에 modbusType + modbusAddr 있으면 그대로 사용.
    - plcDevice 있으면 options로 변환.
    - 없으면 legacy: boolean -> coil legacy_coil_index, 나머지 -> holding legacy_reg_start.
    반환: (modbus_type, addr, count)
    """
    count = _reg_count_for_entry(info)
    dt = (info.get("dataType") or "").strip().lower()

    modbus_type = (info.get("modbusType") or "").strip().lower()
    modbus_addr = info.get("modbusAddr")
    if modbus_addr is not None:
        try:
            addr = int(modbus_addr)
        except (TypeError, ValueError):
            addr = None
        else:
            if modbus_type in ("coil", "holding", "input_reg", "discrete"):
                base = options.get("address_base", 0)
                if modbus_type == "coil":
                    addr += options.get("coil_offset", 0)
                elif modbus_type == "holding":
                    addr += options.get("holding_offset", 0)
                elif modbus_type == "input_reg":
                    addr += options.get("input_reg_offset", 0)
                elif modbus_type == "discrete":
                    addr += options.get("discrete_offset", 0)
                # Dword: 홀수 주소는 짝수 쌍부터 2레지스터 읽도록 정규화
                if dt == "dword" and count == 2 and (addr & 1):
                    addr -= 1
                return modbus_type, addr, count
            return modbus_type or "holding", addr, count

    plc = (info.get("plcDevice") or "").strip()
    if plc:
        prefix, num = _parse_plc_device(plc)
        if prefix is not None:
            rules = options.get("plc_device_rules") or {}
            r = rules.get(prefix, {})
            modbus_type = r.get("modbus_type", "holding")
            off = r.get("offset", 0)
            addr = num + off
            if modbus_type == "coil":
                addr += options.get("coil_offset", 0)
            elif modbus_type == "holding":
                addr += options.get("holding_offset", 0)
            elif modbus_type == "input_reg":
                addr += options.get("input_reg_offset", 0)
            elif modbus_type == "discrete":
                addr += options.get("discrete_offset", 0)
            # Dword: 홀수 주소(D1811 등)는 짝수 쌍(D1810)부터 2레지스터 읽도록 정규화
            if dt == "dword" and count == 2 and (addr & 1):
                addr -= 1
            return modbus_type, addr, count

    # 레거시: Boolean 1bit -> coil 순서, 나머지 -> holding 연속
    if dt == "boolean" and count == 1 and legacy_coil_index is not None:
        return "coil", legacy_coil_index, 1
    if legacy_reg_start is not None:
        return "holding", legacy_reg_start, count
    return None, None, None


def build_full_map(entries, options):
    """
    전체 매핑 생성. (name_or_names, info, modbus_type, addr, count) 리스트.
    name_or_names: 단일 변수면 str, Dword 16+16 쌍이면 (name_low, name_high) 튜플.
    레거시 호환: 아무 엔트리도 modbusType/modbusAddr/plcDevice 없으면 coil 0~106, holding 0~N 연속.
    Dword는 io_variables에서 16bit 두 항목(xxx_D1820, xxx_D1821)으로 있으면 한 쌍으로 읽어 두 이름에 동일 값 설정.
    """
    has_explicit = any(
        "modbusType" in info or "modbusAddr" in info or info.get("plcDevice")
        for _, info in entries
    )
    result = []
    coil_index = 0
    reg_start = 0
    i = 0
    while i < len(entries):
        name, info = entries[i]
        if has_explicit and not ("modbusType" in info or "modbusAddr" in info or info.get("plcDevice")):
            i += 1
            continue
        dt = (info.get("dataType") or "").strip().lower()
        length = int(info.get("length", 0))
        count = _reg_count_for_entry(info)
        use_legacy_coil = (
            dt == "boolean"
            and count == 1
            and "modbusType" not in info
            and "modbusAddr" not in info
            and "plcDevice" not in info
        )
        use_legacy_reg = not use_legacy_coil and "modbusType" not in info and "modbusAddr" not in info and "plcDevice" not in info

        if use_legacy_coil and coil_index < LEGACY_COIL_MAX:
            result.append((name, info, "coil", coil_index, 1))
            coil_index += 1
            i += 1
            continue
        if use_legacy_reg:
            # Dword 16+16 쌍: 같은 base, 연속 D(짝수→홀수)면 한 번에 2레지스터 읽고 두 이름에 값 설정
            if dt == "dword" and length == 16:
                base, d_num = _dword_half_name_to_base_and_index(name)
                next_entry = entries[i + 1] if i + 1 < len(entries) else None
                if base is not None and (d_num & 1) == 0 and next_entry:
                    next_name, next_info = next_entry
                    next_dt = (next_info.get("dataType") or "").strip().lower()
                    next_len = int(next_info.get("length", 0))
                    next_base, next_d = _dword_half_name_to_base_and_index(next_name)
                    if (
                        next_dt == "dword"
                        and next_len == 16
                        and next_base == base
                        and next_d == d_num + 1
                    ):
                        merged_info = {**info, "length": 32}
                        result.append(((name, next_name), merged_info, "holding", reg_start, 2))
                        reg_start += 2
                        i += 2
                        continue
                if base is not None and (d_num & 1) == 1:
                    # 상위 워드 단독 엔트리: 이미 앞에서 쌍으로 처리됐으므로 스킵
                    i += 1
                    continue
            result.append((name, info, "holding", reg_start, count))
            reg_start += count
            i += 1
            continue

        modbus_type, addr, c = resolve_address(
            name, info, options,
            legacy_coil_index if coil_index < LEGACY_COIL_MAX else None,
            reg_start if not use_legacy_coil else None,
        )
        if modbus_type and addr is not None:
            result.append((name, info, modbus_type, addr, c))
            if modbus_type == "coil":
                coil_index = max(coil_index, addr + 1)
            elif modbus_type == "holding":
                reg_start = max(reg_start, addr + c)
        i += 1
    return result


def _is_string_entry(info):
    return (info.get("dataType") or "").strip().lower() == "string"


def build_read_blocks(full_map):
    """
    (name, info, type, addr, count) 리스트를 읽기 최적 블록으로 묶음.
    coil/discrete: 그대로. holding/input_reg: data vs string 분리(금형 이름 등).
    반환: coil, discrete, holding_data, holding_string, input_reg_data, input_reg_string
    """
    by_type = {}
    for name, info, mtype, addr, count in full_map:
        by_type.setdefault(mtype, []).append((name, info, addr, count))

    def merge_blocks(tags):
        if not tags:
            return []
        sorted_tags = sorted(tags, key=lambda t: t[2])
        blocks = []
        cur_start = sorted_tags[0][2]
        cur_end = cur_start + sorted_tags[0][3]
        cur_list = [sorted_tags[0]]
        for name, info, addr, count in sorted_tags[1:]:
            new_end = max(cur_end, addr + count)
            block_len = new_end - cur_start
            # 연속(addr <= cur_end)이고 블록 길이 <= 125일 때만 합침. 구간 끊기거나 125 초과면 여기서 자름
            if addr <= cur_end and block_len <= MAX_REGISTERS_OR_COILS_PER_READ:
                cur_end = new_end
                cur_list.append((name, info, addr, count))
            else:
                blocks.append((cur_start, cur_end - cur_start, cur_list))
                cur_start = addr
                cur_end = addr + count
                cur_list = [(name, info, addr, count)]
        blocks.append((cur_start, cur_end - cur_start, cur_list))
        return blocks

    out = {}
    for mtype, tags in by_type.items():
        if not tags:
            continue
        if mtype in ("coil", "discrete"):
            out[mtype] = merge_blocks(tags)
            continue
        if mtype == "holding":
            data_tags = [(n, i, a, c) for n, i, a, c in tags if not _is_string_entry(i)]
            string_tags = [(n, i, a, c) for n, i, a, c in tags if _is_string_entry(i)]
            out["holding_data"] = merge_blocks(data_tags)
            out["holding_string"] = merge_blocks(string_tags)
            continue
        if mtype == "input_reg":
            data_tags = [(n, i, a, c) for n, i, a, c in tags if not _is_string_entry(i)]
            string_tags = [(n, i, a, c) for n, i, a, c in tags if _is_string_entry(i)]
            out["input_reg_data"] = merge_blocks(data_tags)
            out["input_reg_string"] = merge_blocks(string_tags)
            continue
        out[mtype] = merge_blocks(tags)
    return out


def decode_value(info, raw_regs=None, raw_bits=None, word_swap=False):
    """
    범용 디코더: dataType, length, scale, unit 반영.
    raw_regs: 레지스터 리스트 (holding/input_reg)
    raw_bits: 비트 리스트 (coil/discrete)
    word_swap: True면 다중 레지스터 해석 시 워드 순서 반전 (하위워드→상위워드). 00 01 E8 5E → E8 5E 00 01로 해석.
    """
    if raw_bits is not None and len(raw_bits) >= 1:
        return 1 if raw_bits[0] else 0

    if not raw_regs:
        return "-"
    dt = (info.get("dataType") or "").strip().lower()
    length = int(info.get("length", 0))
    scale = 1.0
    try:
        s = info.get("scale")
        if s is not None:
            scale = float(s)
    except (TypeError, ValueError):
        pass

    if dt == "word" and len(raw_regs) >= 1:
        v = raw_regs[0] & 0xFFFF
        if v >= 0x8000:
            v -= 0x10000
        return round(v * scale, 4) if scale != 1 else v
    if dt == "dword" and len(raw_regs) >= 2:
        # word_swap=False: 첫 레지스터=상위 16비트, 둘째=하위 (00 01 E8 5E → 0x0001E85E)
        # word_swap=True:  둘째=상위, 첫째=하위 (00 01 E8 5E → 0xE85E0001, 즉 E8 5E 00 01)
        if word_swap:
            v = ((raw_regs[1] & 0xFFFF) << 16) | (raw_regs[0] & 0xFFFF)
        else:
            v = ((raw_regs[0] & 0xFFFF) << 16) | (raw_regs[1] & 0xFFFF)
        if v >= 0x80000000:
            v -= 0x100000000
        return round(v * scale, 4) if scale != 1 else v
    if dt == "string":
        regs = raw_regs[:8]
        if word_swap:
            regs = list(reversed(regs))
        buf = []
        for r in regs:
            buf.append((r >> 8) & 0xFF)
            buf.append(r & 0xFF)
        return "".join(f"{b:02x}" for b in buf)
    if raw_regs:
        v = raw_regs[0] & 0xFFFF
        if v >= 0x8000:
            v -= 0x10000
        return round(v * scale, 4) if scale != 1 else v
    return "-"
