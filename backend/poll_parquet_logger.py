"""
폴링 스레드별·날짜별 Parquet 수집 (NDJSON 대체).
경로: {POLL_LOGS_DIR}/{thread_name}/{YYYYMMDD}.parquet

스키마: t_kst (KST ISO 문자열), interval_key, data_json (변수 맵 JSON 문자열)
NDJSON과 동일한 정보를 보존하며, 행 단위 append 대신 버퍼 후 배치 플러시.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from parquet_control import is_parquet_write_enabled

KST = timezone(timedelta(hours=9))

_DEFAULT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poll_logs")
_LOCK = threading.Lock()
_THREAD_FOLDER_BY_INTERVAL = {
    "50ms": "실시간_공정값",
    "1s": "경고_부저_입출력",
    "1min": "SPM／CPM_요약",
    "1h": "금형_셋업",
}

# 버퍼가 이 개수 이상이면 즉시 플러시
POLL_LOG_BATCH_SIZE = int(os.environ.get("POLL_LOG_BATCH_SIZE", "200") or "200")
# 마지막 플러시 이후 이 초가 지나면 버퍼가 비어 있지 않을 때 플러시
POLL_LOG_FLUSH_SEC = float(os.environ.get("POLL_LOG_FLUSH_SEC", "5.0") or "5.0")
_COMPRESSION = (os.environ.get("POLL_LOG_PARQUET_COMPRESSION", "snappy") or "snappy").strip().lower()

# (thread_folder, date_str) -> list[dict]
_buffers: dict[tuple[str, str], list[dict[str, Any]]] = {}
# 현재 버퍼가 비어 있지 않을 때, 첫 행이 들어온 monotonic 시각 (플러시 주기 판단용)
_buffer_first_mono: dict[tuple[str, str], float] = {}

_PARQUET_SCHEMA = pa.schema(
    [
        ("t_kst", pa.string()),
        ("interval_key", pa.string()),
        ("data_json", pa.string()),
    ]
)


def _get_base_dir() -> str:
    return os.environ.get("POLL_LOGS_DIR", "").strip() or _DEFAULT_BASE


def _serialize_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _resolve_thread_folder(interval_key: str) -> str:
    return _THREAD_FOLDER_BY_INTERVAL.get(str(interval_key or "").strip(), "실시간_공정값")


def _normalize_legacy_file_name(name: str) -> str:
    if not name.endswith(".ndjson"):
        return name
    stem = name[:-7]
    if len(stem) == 10 and stem.count("-") == 2:
        y, m, d = stem.split("-")
        if len(y) == 4 and len(m) == 2 and len(d) == 2 and y.isdigit() and m.isdigit() and d.isdigit():
            return f"{y}{m}{d}.ndjson"
    return name


def _migrate_legacy_interval_dirs(base_dir: str) -> None:
    """레거시 poll_logs/<interval_key>/ → 스레드 폴더명으로 이전 (기존 NDJSON 로거와 동일)."""
    for interval_key, thread_folder in _THREAD_FOLDER_BY_INTERVAL.items():
        legacy_dir = os.path.join(base_dir, interval_key)
        if not os.path.isdir(legacy_dir):
            continue
        target_dir = os.path.join(base_dir, thread_folder)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError:
            continue
        try:
            file_names = [n for n in os.listdir(legacy_dir) if n.endswith(".ndjson")]
        except OSError:
            continue
        for name in file_names:
            src = os.path.join(legacy_dir, name)
            dst_name = _normalize_legacy_file_name(name)
            dst = os.path.join(target_dir, dst_name)
            try:
                if os.path.exists(dst):
                    with open(src, "r", encoding="utf-8") as rf, open(dst, "a", encoding="utf-8") as wf:
                        shutil.copyfileobj(rf, wf)
                    os.remove(src)
                else:
                    os.replace(src, dst)
            except OSError:
                continue
        try:
            os.rmdir(legacy_dir)
        except OSError:
            pass


def _rows_to_table(rows: list[dict[str, Any]]) -> pa.Table:
    t_kst = [r["t_kst"] for r in rows]
    interval_key = [r["interval_key"] for r in rows]
    data_json = [r["data_json"] for r in rows]
    return pa.Table.from_arrays(
        [pa.array(t_kst), pa.array(interval_key), pa.array(data_json)],
        schema=_PARQUET_SCHEMA,
    )


def _merge_write_parquet(file_path: str, new_rows: list[dict[str, Any]]) -> None:
    table_new = _rows_to_table(new_rows)
    if os.path.exists(file_path):
        try:
            old = pq.read_table(file_path)
            table = pa.concat_tables([old, table_new])
        except Exception:
            table = table_new
    else:
        table = table_new
    tmp = file_path + ".tmp"
    # schema= 는 table에 이미 있음; PyArrow 23+ 에서 schema를 중복 지정하면 TypeError 발생
    pq.write_table(
        table,
        tmp,
        compression=None if _COMPRESSION in ("none", "uncompressed") else _COMPRESSION,
    )
    os.replace(tmp, file_path)


def _flush_key_locked(key: tuple[str, str]) -> None:
    rows = _buffers.get(key)
    if not rows:
        return
    chunk = rows[:]
    rows.clear()
    if key in _buffer_first_mono:
        del _buffer_first_mono[key]
    base = _get_base_dir()
    thread_folder, date_str = key
    dir_path = os.path.join(base, thread_folder)
    try:
        os.makedirs(dir_path, exist_ok=True)
    except OSError:
        _buffers[key].extend(chunk)
        if chunk:
            _buffer_first_mono[key] = time.monotonic()
        return
    _migrate_legacy_interval_dirs(base)
    file_path = os.path.join(dir_path, date_str + ".parquet")
    try:
        _merge_write_parquet(file_path, chunk)
    except Exception:
        _buffers[key].extend(chunk)
        if chunk:
            _buffer_first_mono[key] = time.monotonic()
        return


def _flush_all_buffers() -> None:
    with _LOCK:
        keys = list(_buffers.keys())
        for key in keys:
            _flush_key_locked(key)


def append_parsed_to_parquet(parsed: dict, interval_key: str, timestamp: float) -> None:
    """
    parsed: { variable_name: value, ... }
    interval_key: "50ms" | "1s" | "1min" | "1h"
    """
    if not is_parquet_write_enabled():
        return
    if not parsed or not interval_key:
        return
    base = _get_base_dir()
    date_str = datetime.fromtimestamp(timestamp).strftime("%Y%m%d")
    thread_folder = _resolve_thread_folder(interval_key)
    key = (thread_folder, date_str)

    data = {k: _serialize_value(v) for k, v in parsed.items()}
    dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    t_kst = dt_utc.astimezone(KST).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+09:00"
    row = {
        "t_kst": t_kst,
        "interval_key": str(interval_key),
        "data_json": json.dumps(data, ensure_ascii=False),
    }

    now = time.monotonic()
    with _LOCK:
        if key not in _buffers:
            _buffers[key] = []
        _buffers[key].append(row)
        if len(_buffers[key]) == 1:
            _buffer_first_mono[key] = now

        buf = _buffers[key]
        bf = _buffer_first_mono.get(key, now)
        batch = max(1, POLL_LOG_BATCH_SIZE)
        should_flush = len(buf) >= batch or (buf and (now - bf) >= POLL_LOG_FLUSH_SEC)
        if should_flush:
            _flush_key_locked(key)


atexit.register(_flush_all_buffers)
