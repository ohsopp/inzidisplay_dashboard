"""
Dual-write helper: mirror Influx points to Parquet with buffering.

Path layout:
  default: {INFLUX_PARQUET_DIR}/{bucket}/{measurement}/{YYYYMMDD}.parquet
  with interval_key: {INFLUX_PARQUET_DIR}/{bucket}/{interval_key}/{measurement}/{YYYYMMDD}.parquet

PLC 버킷 이름이 plc_data 인 경우 이 모듈은 아무 것도 쓰지 않는다.
(PLC Parquet는 backend/plc_wide_parquet_writer.py → parquet_logs/plc_data/YYYYMMDD.parquet 단일 파일만 사용.)

Schema:
  - temperature: t_kst, value
  - vibration: t_kst, V-rms, a-peak, a-rms, temperature, crest
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
try:
    from parquet_control import is_parquet_write_enabled
except Exception:
    import sys
    _BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    from parquet_control import is_parquet_write_enabled

KST = timezone(timedelta(hours=9))
_LOCK = threading.Lock()
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_BASE = os.path.join(_ROOT_DIR, "parquet_logs")
_BATCH_SIZE = int(os.environ.get("INFLUX_PARQUET_BATCH_SIZE", "200") or "200")
_FLUSH_SEC = float(os.environ.get("INFLUX_PARQUET_FLUSH_SEC", "2.0") or "2.0")
_COMPRESSION = (os.environ.get("INFLUX_PARQUET_COMPRESSION", "snappy") or "snappy").strip().lower()

_SCHEMA_TEMPERATURE = pa.schema(
    [
        ("t_kst", pa.string()),
        ("value", pa.float64()),
    ]
)

_SCHEMA_VIBRATION = pa.schema(
    [
        ("t_kst", pa.string()),
        ("V-rms(A)", pa.float64()),
        ("a-peak(A)", pa.float64()),
        ("a-rms(A)", pa.float64()),
        ("temperature(A)", pa.float64()),
        ("crest(A)", pa.float64()),
        ("V-rms(B)", pa.float64()),
        ("a-peak(B)", pa.float64()),
        ("a-rms(B)", pa.float64()),
        ("temperature(B)", pa.float64()),
        ("crest(B)", pa.float64()),
    ]
)


def _schema_for_measurement(measurement: str) -> pa.Schema:
    if str(measurement or "").strip().lower() == "temperature":
        return _SCHEMA_TEMPERATURE
    return _SCHEMA_VIBRATION

# key: (bucket, interval_key, measurement, yyyymmdd) -> rows
_buffers: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
_buffer_first_mono: dict[tuple[str, str, str, str], float] = {}
_write_error_logged = False


def _base_dir() -> str:
    return os.environ.get("INFLUX_PARQUET_DIR", "").strip() or _DEFAULT_BASE


def _serialize_value(v: Any) -> Any:
    if isinstance(v, (int, float, bool, str)) or v is None:
        return v
    return str(v)


def _normalize_name(s: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in str(s or ""))
    return out or "_"


def _row_for_point(
    bucket: str,
    measurement: str,
    tags: dict[str, Any],
    fields: dict[str, Any],
    timestamp_ns: int | None,
    source: str,
    interval_key: str | None = None,
) -> tuple[tuple[str, str, str, str], dict[str, float | str | None]]:
    if timestamp_ns is None:
        timestamp_ns = time.time_ns()
    dt_utc = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc)
    dt_kst = dt_utc.astimezone(KST)
    # 파일명은 t_kst 날짜와 맞춤 (UTC 날짜면 KST 자정 전후에 하루 어긋남)
    date_str = dt_kst.strftime("%Y%m%d")
    t_kst = dt_kst.isoformat()
    interval_norm = _normalize_name(interval_key) if interval_key else "_default"
    key = (_normalize_name(bucket), interval_norm, _normalize_name(measurement), date_str)
    row: dict[str, float | str | None] = {"t_kst": t_kst}
    measurement_norm = str(measurement or "").strip().lower()
    if measurement_norm == "temperature":
        try:
            row["value"] = (
                float((fields or {}).get("value")) if (fields or {}).get("value") is not None else None
            )
        except (TypeError, ValueError):
            row["value"] = None
    elif measurement_norm == "vibration":
        sensor_type = str((tags or {}).get("sensor_type") or "").strip().upper()
        suffix = ""
        if sensor_type in ("VVB001-A", "VVB001(A)", "A"):
            suffix = "(A)"
        elif sensor_type in ("VVB001-B", "VVB001(B)", "B"):
            suffix = "(B)"

        field_map = {
            "V-rms": "v_rms",
            "a-peak": "a_peak",
            "a-rms": "a_rms",
            "temperature": "temperature",
            "crest": "crest",
        }
        for metric_name, src_name in field_map.items():
            try:
                v = (fields or {}).get(src_name)
                if suffix:
                    row[f"{metric_name}{suffix}"] = float(v) if v is not None else None
            except (TypeError, ValueError):
                if suffix:
                    row[f"{metric_name}{suffix}"] = None
    return key, row


def _rows_to_table(rows: list[dict[str, float | str | None]], schema: pa.Schema) -> pa.Table:
    arrays = []
    for field in schema:
        arrays.append(pa.array([r.get(field.name) for r in rows], type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _merge_write(file_path: str, rows: list[dict[str, str]]) -> None:
    measurement = os.path.basename(os.path.dirname(file_path))
    schema = _schema_for_measurement(measurement)
    table_new = _rows_to_table(rows, schema)
    if os.path.exists(file_path):
        try:
            old = pq.read_table(file_path)
            cols = []
            for field in schema:
                name = field.name
                if name in old.column_names:
                    col = old[name]
                    if col.type == field.type:
                        cols.append(col)
                    else:
                        try:
                            cols.append(col.cast(field.type))
                        except Exception:
                            cols.append(pa.array([None] * old.num_rows, type=field.type))
                else:
                    cols.append(pa.array([None] * old.num_rows, type=field.type))
            old_aligned = pa.Table.from_arrays(cols, schema=schema)
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
        # Some environments miss snappy/zstd codec support.
        pq.write_table(table, tmp, compression=None)
    os.replace(tmp, file_path)


def _flush_key_locked(key: tuple[str, str, str, str]) -> None:
    global _write_error_logged
    rows = _buffers.get(key)
    if not rows:
        return
    chunk = rows[:]
    rows.clear()
    _buffer_first_mono.pop(key, None)
    base = _base_dir()
    bucket, interval_key, measurement, date_str = key
    if interval_key == "_default":
        dir_path = os.path.join(base, bucket, measurement)
    else:
        dir_path = os.path.join(base, bucket, interval_key, measurement)
    try:
        os.makedirs(dir_path, exist_ok=True)
    except OSError:
        _buffers[key].extend(chunk)
        if chunk:
            _buffer_first_mono[key] = time.monotonic()
        return
    file_path = os.path.join(dir_path, date_str + ".parquet")
    try:
        _merge_write(file_path, chunk)
    except Exception as e:
        if not _write_error_logged:
            print(f"[ParquetDualWrite] flush 실패: {e}", flush=True)
            _write_error_logged = True
        _buffers[key].extend(chunk)
        if chunk:
            _buffer_first_mono[key] = time.monotonic()


def _flush_all_buffers() -> None:
    with _LOCK:
        for key in list(_buffers.keys()):
            _flush_key_locked(key)


def append_point_to_parquet(
    *,
    bucket: str,
    measurement: str,
    tags: dict[str, Any] | None,
    fields: dict[str, Any] | None,
    timestamp_ns: int | None = None,
    source: str = "",
    interval_key: str | None = None,
) -> None:
    if not is_parquet_write_enabled():
        return
    # plc_data 버킷은 M/D/Y·50ms/1s 등으로 디렉터리가 나뉘지 않게, dual-write 경로를 사용하지 않는다.
    if _normalize_name(str(bucket)) == "plc_data":
        return
    key, row = _row_for_point(
        bucket=bucket,
        measurement=measurement,
        tags=tags or {},
        fields=fields or {},
        timestamp_ns=timestamp_ns,
        source=source,
        interval_key=interval_key,
    )
    now = time.monotonic()
    with _LOCK:
        if key not in _buffers:
            _buffers[key] = []
        _buffers[key].append(row)
        if len(_buffers[key]) == 1:
            _buffer_first_mono[key] = now
        buf = _buffers[key]
        bf = _buffer_first_mono.get(key, now)
        if len(buf) >= max(1, _BATCH_SIZE) or (buf and (now - bf) >= _FLUSH_SEC):
            _flush_key_locked(key)


atexit.register(_flush_all_buffers)
