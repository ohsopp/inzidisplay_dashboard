"""
Modbus TCP 폴링: 매핑/옵션/블록 그룹핑/범용 디코더(modbus_mapping) 사용.
간격 3종: Boolean(Coil/Discrete), 데이터(Holding/InputReg 비문자열), 금형이름(String).
"""
import json
import threading
import time
from pathlib import Path

from modbus_mapping import (
    load_io_variables,
    load_options,
    build_full_map,
    build_read_blocks,
    decode_value,
)

SCRIPT_DIR = Path(__file__).resolve().parent
INTERVALS_FILE = SCRIPT_DIR / "modbus_poll_intervals.json"

# GUI/API에서 수정 가능한 폴링 간격(ms). 경고등/금형 기동 등 자주 갱신되도록 Boolean/데이터 기본값 단축.
DEFAULT_INTERVALS = {"boolean_ms": 500, "data_ms": 500, "string_ms": 5000}
MIN_INTERVAL_MS = 200
MAX_INTERVAL_MS = 1800000  # 30분


def _load_intervals_from_file():
    if not INTERVALS_FILE.exists():
        return None
    try:
        with open(INTERVALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {
                "boolean_ms": int(data.get("boolean_ms", DEFAULT_INTERVALS["boolean_ms"])),
                "data_ms": int(data.get("data_ms", DEFAULT_INTERVALS["data_ms"])),
                "string_ms": int(data.get("string_ms", DEFAULT_INTERVALS["string_ms"])),
            }
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _save_intervals_to_file():
    try:
        with open(INTERVALS_FILE, "w", encoding="utf-8") as f:
            json.dump(poll_intervals, f, indent=2)
    except OSError:
        pass


poll_intervals = dict(DEFAULT_INTERVALS)
_loaded = _load_intervals_from_file()
if _loaded:
    poll_intervals.update(_loaded)


def get_poll_intervals():
    return dict(poll_intervals)


def _parse_ms(val):
    if val is None:
        return None
    try:
        v = int(float(val))
        return v if MIN_INTERVAL_MS <= v <= MAX_INTERVAL_MS else None
    except (TypeError, ValueError):
        return None


def set_poll_intervals(boolean_ms=None, data_ms=None, string_ms=None):
    global poll_intervals
    v = _parse_ms(boolean_ms)
    if v is not None:
        poll_intervals["boolean_ms"] = v
    v = _parse_ms(data_ms)
    if v is not None:
        poll_intervals["data_ms"] = v
    v = _parse_ms(string_ms)
    if v is not None:
        poll_intervals["string_ms"] = v
    _save_intervals_to_file()


def run_poller(host, port, slave_id, on_parsed, on_error, stop_event):
    """
    폴링 스레드: Boolean(Coil/Discrete), 데이터(holding_data/input_reg_data), 금형이름(holding_string/input_reg_string) 각각 간격 적용.
    """
    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        on_error("pymodbus가 설치되지 않았습니다. pip install pymodbus")
        return

    options = load_options()
    entries = load_io_variables()
    full_map = build_full_map(entries, options)
    blocks = build_read_blocks(full_map)

    port = port or 502
    parsed = {}
    last_coil_time = [0]
    last_reg_time = [0]
    last_string_time = [0]

    def connect_client():
        c = ModbusTcpClient(host=host, port=port, timeout=3)
        if not c.connect():
            return None
        return c

    def _set_parsed(name_or_names, val):
        if isinstance(name_or_names, (list, tuple)):
            for n in name_or_names:
                parsed[n] = val
        else:
            parsed[name_or_names] = val

    def do_coils_and_discrete():
        """Coil + Discrete를 한 연결로 연속 읽기."""
        client = connect_client()
        if not client:
            on_error("Modbus TCP 연결 실패")
            return
        try:
            for start, count, tags in blocks.get("coil", []):
                rr = client.read_coils(start, count=count, device_id=slave_id)
                if rr.isError():
                    for name, *_ in tags:
                        parsed[name] = "-"
                    continue
                bits = rr.bits[:count]
                for name, info, addr, tag_count in tags:
                    off = addr - start
                    sl = bits[off : off + tag_count] if off + tag_count <= len(bits) else []
                    parsed[name] = decode_value(info, raw_bits=sl)
            for start, count, tags in blocks.get("discrete", []):
                rr = client.read_discrete_inputs(start, count=count, device_id=slave_id)
                if rr.isError():
                    for name, *_ in tags:
                        parsed[name] = "-"
                    continue
                bits = rr.bits[:count]
                for name, info, addr, tag_count in tags:
                    off = addr - start
                    sl = bits[off : off + tag_count] if off + tag_count <= len(bits) else []
                    parsed[name] = decode_value(info, raw_bits=sl)
        except Exception as e:
            on_error(str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass

    def do_holding_blocks(block_list, client=None):
        own_client = client is None
        for start, count, tags in block_list:
            c = client or connect_client()
            if not c:
                if own_client:
                    on_error("Modbus TCP 연결 실패")
                continue
            try:
                rr = c.read_holding_registers(start, count=count, device_id=slave_id)
                if rr.isError():
                    for name_or_names, *_ in tags:
                        _set_parsed(name_or_names, "-")
                    continue
                regs = rr.registers[:count]
                for name_or_names, info, addr, tag_count in tags:
                    off = addr - start
                    chunk = regs[off : off + tag_count] if off + tag_count <= len(regs) else []
                    val = decode_value(info, raw_regs=chunk)
                    _set_parsed(name_or_names, val)
            except Exception as e:
                if own_client:
                    on_error(str(e))
                for name_or_names, *_ in tags:
                    _set_parsed(name_or_names, "-")
            finally:
                if own_client:
                    try:
                        c.close()
                    except Exception:
                        pass

    def do_input_reg_blocks(block_list, client=None):
        own_client = client is None
        for start, count, tags in block_list:
            c = client or connect_client()
            if not c:
                continue
            try:
                rr = c.read_input_registers(start, count=count, device_id=slave_id)
                if rr.isError():
                    for name_or_names, *_ in tags:
                        _set_parsed(name_or_names, "-")
                    continue
                regs = rr.registers[:count]
                for name_or_names, info, addr, tag_count in tags:
                    off = addr - start
                    chunk = regs[off : off + tag_count] if off + tag_count <= len(regs) else []
                    val = decode_value(info, raw_regs=chunk)
                    _set_parsed(name_or_names, val)
            except Exception as e:
                for name_or_names, *_ in tags:
                    _set_parsed(name_or_names, "-")
            finally:
                if own_client:
                    try:
                        c.close()
                    except Exception:
                        pass

    def do_data_poll():
        """Holding + InputReg 데이터만 한 연결로 읽기 (타발수·금형 기동시간 등). 1회 읽기로 +2 방지."""
        client = connect_client()
        if not client:
            on_error("Modbus TCP 연결 실패")
            return
        try:
            do_holding_blocks(blocks.get("holding_data", []), client=client)
            do_input_reg_blocks(blocks.get("input_reg_data", []), client=client)
        finally:
            try:
                client.close()
            except Exception:
                pass

    def do_string_poll():
        """금형 이름 등 String 블록만 읽기. 데이터 폴링과 분리해 데이터가 2번 읽히지 않게."""
        client = connect_client()
        if not client:
            return
        try:
            do_holding_blocks(blocks.get("holding_string", []), client=client)
            do_input_reg_blocks(blocks.get("input_reg_string", []), client=client)
        finally:
            try:
                client.close()
            except Exception:
                pass

    try:
        do_coils_and_discrete()
        do_data_poll()
        do_string_poll()
        on_parsed(dict(parsed))
    except Exception as e:
        on_error(str(e))
    # 첫 루프에서 같은 초에 데이터를 두 번 읽지 않도록 기준 시간 설정
    _t0 = time.monotonic()
    last_coil_time[0] = _t0
    last_reg_time[0] = _t0
    last_string_time[0] = _t0

    while not stop_event.is_set():
        now = time.monotonic()
        iv = get_poll_intervals()
        i_bool = (iv.get("boolean_ms", 500) or 500) / 1000.0
        i_data = (iv.get("data_ms", 500) or 500) / 1000.0
        i_str = (iv.get("string_ms", 5000) or 5000) / 1000.0
        if now - last_coil_time[0] >= i_bool:
            last_coil_time[0] = now
            do_coils_and_discrete()
            on_parsed(dict(parsed))
        if now - last_reg_time[0] >= i_data:
            last_reg_time[0] = now
            do_data_poll()
            on_parsed(dict(parsed))
        if now - last_string_time[0] >= i_str:
            last_string_time[0] = now
            do_string_poll()
            on_parsed(dict(parsed))
        time.sleep(0.2)
