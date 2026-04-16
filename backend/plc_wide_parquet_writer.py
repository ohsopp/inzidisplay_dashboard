"""
PLC 폴링값을 일별 단일 Parquet(와이드)로 저장.

- 경로: {PLC_WIDE_PARQUET_DIR 또는 parquet_logs/plc_data}/{YYYYMMDD}.parquet (날짜는 KST, 하위 폴더 없음)
- 컬럼: t_kst, poll_interval(이번 행을 만든 폴링: 50ms|1s), 각 변수명(매핑 순서·이름 그대로)
- 50ms 행: 1s 주기 변수는 직전 1s 스냅샷으로 채움(전방 패딩). 1s 행: 50ms 변수는 직전 50ms 스냅샷으로 채움.

온도/진동 등 MQTT·기타 경로는 parquet_dual_writer를 그대로 사용한다.
"""
from __future__ import annotations

import atexit
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from parquet_control import is_parquet_write_enabled

KST = timezone(timedelta(hours=9))

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DIR = os.path.join(_BACKEND_DIR, "..", "parquet_logs", "plc_data")

_BATCH_SIZE = int(os.environ.get("PLC_WIDE_PARQUET_BATCH_SIZE", "200") or "200")
_FLUSH_SEC = float(os.environ.get("PLC_WIDE_PARQUET_FLUSH_SEC", "2.0") or "2.0")
_COMPRESSION = (os.environ.get("PLC_WIDE_PARQUET_COMPRESSION", "snappy") or "snappy").strip().lower()

_LOCK = threading.RLock()
_state_50ms: dict[str, Any] = {}
_state_1s: dict[str, Any] = {}
_buffers: dict[str, list[dict[str, Any]]] = {}
_buffer_first_mono: dict[str, float] = {}
_meta_cache: dict[str, Any] | None = None
_write_error_logged = False


def _base_dir() -> str:
    return os.environ.get("PLC_WIDE_PARQUET_DIR", "").strip() or _DEFAULT_DIR


def _refresh_meta() -> tuple[list[str], set[str], set[str], pa.Schema]:
    """변수 컬럼 순서(정렬), 50ms/1s 집합, PyArrow 스키마."""
    from mc_mapping import get_mc_entries, get_variable_names_by_poll_interval

    grouped = get_variable_names_by_poll_interval()
    names_50 = list(grouped.get("50ms") or [])
    names_1s = list(grouped.get("1s") or [])
    col_order = sorted(set(names_50) | set(names_1s))

    string_names: set[str] = set()
    dword_names: set[str] = set()
    string_stem_min_addr: dict[str, int] = {}
    string_stem_min_name: dict[str, str] = {}
    dword_stem_min_addr: dict[str, int] = {}
    dword_stem_min_name: dict[str, str] = {}
    for name, dev, addr, data_type, _length in get_mc_entries():
        dt = (data_type or "").strip().lower()
        if dt == "string":
            string_names.add(name)
            # 문자열이 연속 워드 주소(D1560~D1567)로 펼쳐진 경우,
            # 와이드 Parquet에는 대표 시작 주소 1개만 컬럼으로 유지한다.
            # 예: currentDieName_D1560만 남기고 D1561~D1567은 제외.
            if dev == "D" and "_D" in name:
                stem = name.rsplit("_D", 1)[0]
                prev = string_stem_min_addr.get(stem)
                if prev is None or int(addr) < prev:
                    string_stem_min_addr[stem] = int(addr)
                    string_stem_min_name[stem] = name
        elif dt == "dword":
            dword_names.add(name)
            # Dword가 시작/다음 워드 주소로 중복 정의된 경우(예: D1810, D1811),
            # 와이드 Parquet에는 대표 시작 주소 1개만 컬럼으로 유지한다.
            if dev == "D" and "_D" in name:
                stem = name.rsplit("_D", 1)[0]
                prev = dword_stem_min_addr.get(stem)
                if prev is None or int(addr) < prev:
                    dword_stem_min_addr[stem] = int(addr)
                    dword_stem_min_name[stem] = name

    if string_stem_min_name:
        allowed_string_names = set(string_stem_min_name.values())
        col_order = [n for n in col_order if (n not in string_names) or (n in allowed_string_names)]
    if dword_stem_min_name:
        allowed_dword_names = set(dword_stem_min_name.values())
        col_order = [n for n in col_order if (n not in dword_names) or (n in allowed_dword_names)]

    fields = [
        pa.field("t_kst", pa.string()),
        pa.field("poll_interval", pa.string()),
    ]
    for name in col_order:
        fields.append(pa.field(name, pa.string() if name in string_names else pa.float64()))
    schema = pa.schema(fields)
    return col_order, set(names_50), set(names_1s), schema


def _mc_fake_values_mtime() -> float | None:
    """mc_fake_values.json 변경 시 Parquet 컬럼 스키마를 다시 잡기 위한 mtime."""
    from mc_mapping import MC_FAKE_VALUES_PATH

    try:
        if not MC_FAKE_VALUES_PATH.exists():
            return None
        return MC_FAKE_VALUES_PATH.stat().st_mtime
    except OSError:
        return None


def _ensure_meta() -> tuple[list[str], set[str], set[str], pa.Schema]:
    global _meta_cache
    mtime = _mc_fake_values_mtime()
    with _LOCK:
        if (
            _meta_cache is not None
            and _meta_cache.get("file_mtime") == mtime
        ):
            m = _meta_cache
            return m["col_order"], m["set_50"], m["set_1s"], m["schema"]
        c50, s50, s1s, schema = _refresh_meta()
        _meta_cache = {
            "col_order": c50,
            "set_50": s50,
            "set_1s": s1s,
            "schema": schema,
            "file_mtime": mtime,
        }
        m = _meta_cache
        return m["col_order"], m["set_50"], m["set_1s"], m["schema"]


def invalidate_meta_cache() -> None:
    """mc_fake_values.json 등을 바꾼 뒤 호출하면 스키마를 다시 읽는다."""
    global _meta_cache
    with _LOCK:
        _meta_cache = None


def _norm_incoming(v: Any) -> Any:
    if v == "-" or v is None:
        return None
    return v


def _cell_value(name: str, v: Any, string_names: set[str]) -> Any:
    if v is None:
        return None
    if name in string_names:
        return str(v).replace("\x00", "").strip() or None
    if isinstance(v, bool):
        return float(int(v))
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _align_table_to_schema(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """기존 파일을 현재 스키마에 맞춘다(컬럼 추가·재배열)."""
    n = table.num_rows
    cols = []
    for field in schema:
        name = field.name
        if name in table.column_names:
            col = table[name]
            if col.type == field.type:
                cols.append(col)
            else:
                try:
                    cols.append(col.cast(field.type))
                except Exception:
                    cols.append(pa.array([None] * n, type=field.type))
        else:
            cols.append(pa.array([None] * n, type=field.type))
    return pa.Table.from_arrays(cols, schema=schema)


def _rows_to_table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    arrays = []
    for field in schema:
        name = field.name
        arrays.append(pa.array([r.get(name) for r in rows], type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _merge_write(file_path: str, new_rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    table_new = _rows_to_table(new_rows, schema)
    if os.path.exists(file_path):
        try:
            old = pq.read_table(file_path)
            old_aligned = _align_table_to_schema(old, schema)
            table = pa.concat_tables([old_aligned, table_new])
        except Exception:
            table = table_new
    else:
        table = table_new
    tmp = file_path + ".tmp"
    try:
        pq.write_table(
            table,
            tmp,
            compression=None if _COMPRESSION in ("none", "uncompressed") else _COMPRESSION,
        )
    except Exception:
        pq.write_table(table, tmp, compression=None)
    os.replace(tmp, file_path)


def _flush_key_locked(date_str: str) -> None:
    global _write_error_logged
    rows = _buffers.get(date_str)
    if not rows:
        return
    chunk = rows[:]
    rows.clear()
    _buffer_first_mono.pop(date_str, None)

    _, _, _, schema = _ensure_meta()

    base = _base_dir()
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        _buffers[date_str].extend(chunk)
        if chunk:
            _buffer_first_mono[date_str] = time.monotonic()
        return

    file_path = os.path.join(base, date_str + ".parquet")
    try:
        _merge_write(file_path, chunk, schema)
    except Exception as e:
        if not _write_error_logged:
            print(f"[PLC Wide Parquet] flush 실패: {e}", flush=True)
            _write_error_logged = True
        _buffers[date_str].extend(chunk)
        if chunk:
            _buffer_first_mono[date_str] = time.monotonic()


def _flush_all_buffers() -> None:
    with _LOCK:
        for key in list(_buffers.keys()):
            _flush_key_locked(key)


def seed_plc_wide_from_bootstrap(parsed: dict[str, Any]) -> None:
    """
    MC 연결 직후 전체 변수 순차 로드(부트스트랩) 직후에만 호출.
    50ms/1s 내부 스냅샷을 한 번에 채워, 이후 첫 주기 Parquet 행에서 상대 그룹 컬럼이 공란이 되지 않게 한다.
    """
    if not is_parquet_write_enabled():
        return
    if not parsed:
        return
    _, set_50, set_1s, _ = _ensure_meta()
    with _LOCK:
        for k, v in parsed.items():
            if k in set_50:
                nv = _norm_incoming(v)
                if nv is None:
                    continue
                _state_50ms[k] = v
            elif k in set_1s:
                nv = _norm_incoming(v)
                if nv is None:
                    continue
                _state_1s[k] = v


def append_plc_wide_row(parsed: dict[str, Any], interval_key: str, timestamp: float) -> None:
    """
    MC 폴링 한 번의 parsed(해당 주기 그룹 변수만 포함)를 반영해 한 행을 쌓는다.
    interval_key: '50ms' | '1s'
    """
    if not is_parquet_write_enabled():
        return
    if not parsed or interval_key not in ("50ms", "1s"):
        return

    col_order, set_50, set_1s, schema = _ensure_meta()
    string_names = {
        f.name
        for f in schema
        if f.name not in ("t_kst", "poll_interval") and f.type == pa.string()
    }

    dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    dt_kst = dt_utc.astimezone(KST)
    date_str = dt_kst.strftime("%Y%m%d")
    t_kst = dt_kst.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+09:00"

    now = time.monotonic()
    with _LOCK:
        if interval_key == "50ms":
            for k, v in parsed.items():
                if k not in set_50:
                    continue
                nv = _norm_incoming(v)
                if nv is None:
                    continue
                _state_50ms[k] = v
        else:
            for k, v in parsed.items():
                if k not in set_1s:
                    continue
                nv = _norm_incoming(v)
                if nv is None:
                    continue
                _state_1s[k] = v

        row: dict[str, Any] = {
            "t_kst": t_kst,
            "poll_interval": interval_key,
        }
        for name in col_order:
            if name in set_50:
                raw = _state_50ms.get(name)
            else:
                raw = _state_1s.get(name)
            row[name] = _cell_value(name, raw, string_names)

        if date_str not in _buffers:
            _buffers[date_str] = []
        _buffers[date_str].append(row)
        if len(_buffers[date_str]) == 1:
            _buffer_first_mono[date_str] = now

        buf = _buffers[date_str]
        bf = _buffer_first_mono.get(date_str, now)
        batch = max(1, _BATCH_SIZE)
        if len(buf) >= batch or (buf and (now - bf) >= _FLUSH_SEC):
            _flush_key_locked(date_str)


atexit.register(_flush_all_buffers)
