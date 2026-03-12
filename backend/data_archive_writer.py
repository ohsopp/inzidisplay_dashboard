"""
PLC 수집 데이터를 data/<poll_group>/ 에 저장.
- NDJSON: snapshot append-only 로그 (타임스탬프당 1행)
- Parquet: AI/분석용 컬럼 파일(가능한 경우)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_DATA_ROOT = _PROJECT_ROOT / "data"
_GROUPS = ("50ms", "1s", "1min", "1h")
_locks = {g: threading.Lock() for g in _GROUPS}
_parquet_import_error_logged = False


def _ensure_group_dirs(group_key: str) -> Path:
    if group_key not in _GROUPS:
        group_key = "1s"
    group_dir = _DATA_ROOT / group_key
    group_dir.mkdir(parents=True, exist_ok=True)
    return group_dir


def _to_iso_utc(timestamp: float | None) -> str:
    if timestamp is None:
        dt = datetime.now(timezone.utc)
    else:
        dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    return dt.isoformat()


def _to_epoch_ms(iso_utc: str) -> int:
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _normalize_value(value):
    if value is None or value == "-":
        return None, ""
    if isinstance(value, bool):
        return float(int(value)), ""
    if isinstance(value, (int, float)):
        return float(value), ""
    text = str(value)
    try:
        return float(text), ""
    except (TypeError, ValueError):
        return None, text


def _build_rows(parsed: dict, group_key: str, ts_iso: str) -> list[dict]:
    ts_ms = _to_epoch_ms(ts_iso)
    rows = []
    for variable, raw_value in (parsed or {}).items():
        value_num, value_str = _normalize_value(raw_value)
        if value_num is None and not value_str:
            continue
        rows.append(
            {
                "ts": ts_iso,
                "ts_epoch_ms": ts_ms,
                "thread": group_key,
                "variable": str(variable),
                "value_num": value_num,
                "value_str": value_str,
            }
        )
    return rows


def _build_snapshot_values(parsed: dict) -> dict:
    values = {}
    for variable, raw_value in (parsed or {}).items():
        value_num, value_str = _normalize_value(raw_value)
        if value_num is not None:
            values[str(variable)] = value_num
        elif value_str:
            values[str(variable)] = value_str
    return values


def _append_ndjson(group_dir: Path, snapshot: dict, ts_iso: str) -> None:
    if not snapshot:
        return
    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    file_path = group_dir / f"{dt.strftime('%Y%m%d-%H')}.ndjson"
    with file_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=True) + "\n")


def _write_parquet_chunk(group_dir: Path, rows: list[dict], ts_iso: str) -> None:
    global _parquet_import_error_logged
    if not rows:
        return
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception as e:
        if not _parquet_import_error_logged:
            print(f"[DataArchive] Parquet 비활성 (pyarrow 없음): {e}", flush=True)
            _parquet_import_error_logged = True
        return

    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    file_name = f"{dt.strftime('%Y%m%d-%H%M%S')}-{dt.microsecond:06d}.parquet"
    file_path = group_dir / file_name

    schema = pa.schema(
        [
            ("ts", pa.string()),
            ("ts_epoch_ms", pa.int64()),
            ("thread", pa.string()),
            ("variable", pa.string()),
            ("value_num", pa.float64()),
            ("value_str", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, file_path)


def write_poll_batch_to_data(parsed: dict, group_key: str, timestamp: float | None = None) -> bool:
    """
    폴링 스레드별로 NDJSON/Parquet 저장.
    group_key: 50ms | 1s | 1min | 1h
    """
    if group_key not in _GROUPS:
        group_key = "1s"
    if not parsed:
        return False

    group_dir = _ensure_group_dirs(group_key)
    ts_iso = _to_iso_utc(timestamp)
    values = _build_snapshot_values(parsed)
    if not values:
        return False
    snapshot = {
        "ts": ts_iso,
        "ts_epoch_ms": _to_epoch_ms(ts_iso),
        "thread": group_key,
        "values": values,
    }
    rows = _build_rows(parsed, group_key, ts_iso)

    lock = _locks[group_key]
    with lock:
        _append_ndjson(group_dir, snapshot, ts_iso)
        _write_parquet_chunk(group_dir, rows, ts_iso)
    return True

