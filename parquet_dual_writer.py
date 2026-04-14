"""
Dual-write helper: mirror Influx points to Parquet with buffering.

Path layout:
  default: {INFLUX_PARQUET_DIR}/{bucket}/{measurement}/{YYYYMMDD}.parquet
  with interval_key: {INFLUX_PARQUET_DIR}/{bucket}/{interval_key}/{measurement}/{YYYYMMDD}.parquet

Schema:
  t_utc, t_kst, bucket, measurement, tags_json, fields_json, source
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

_PARQUET_SCHEMA = pa.schema(
    [
        ("t_utc", pa.string()),
        ("t_kst", pa.string()),
        ("bucket", pa.string()),
        ("measurement", pa.string()),
        ("tags_json", pa.string()),
        ("fields_json", pa.string()),
        ("source", pa.string()),
    ]
)

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
) -> tuple[tuple[str, str, str, str], dict[str, str]]:
    if timestamp_ns is None:
        timestamp_ns = time.time_ns()
    dt_utc = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc)
    date_str = dt_utc.strftime("%Y%m%d")
    t_utc = dt_utc.isoformat()
    t_kst = dt_utc.astimezone(KST).isoformat()
    interval_norm = _normalize_name(interval_key) if interval_key else "_default"
    key = (_normalize_name(bucket), interval_norm, _normalize_name(measurement), date_str)
    row = {
        "t_utc": t_utc,
        "t_kst": t_kst,
        "bucket": str(bucket),
        "measurement": str(measurement),
        "tags_json": json.dumps({k: _serialize_value(v) for k, v in (tags or {}).items()}, ensure_ascii=False),
        "fields_json": json.dumps({k: _serialize_value(v) for k, v in (fields or {}).items()}, ensure_ascii=False),
        "source": str(source or ""),
    }
    return key, row


def _rows_to_table(rows: list[dict[str, str]]) -> pa.Table:
    return pa.Table.from_arrays(
        [
            pa.array([r["t_utc"] for r in rows]),
            pa.array([r["t_kst"] for r in rows]),
            pa.array([r["bucket"] for r in rows]),
            pa.array([r["measurement"] for r in rows]),
            pa.array([r["tags_json"] for r in rows]),
            pa.array([r["fields_json"] for r in rows]),
            pa.array([r["source"] for r in rows]),
        ],
        schema=_PARQUET_SCHEMA,
    )


def _merge_write(file_path: str, rows: list[dict[str, str]]) -> None:
    table_new = _rows_to_table(rows)
    if os.path.exists(file_path):
        try:
            old = pq.read_table(file_path)
            table = pa.concat_tables([old, table_new])
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
