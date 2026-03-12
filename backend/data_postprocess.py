"""
NDJSON 원본을 변수별 집계 파일로 후처리.

입력:
- data/<group>/*.ndjson (snapshot 포맷 + legacy row 포맷 모두 지원)

출력:
- data/<group>/by_variable/<safe_name>.ndjson
- data/<group>/by_variable/index.json (원래 변수명 -> 파일명 매핑)
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone


_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_DATA_ROOT = _PROJECT_ROOT / "data"
_GROUPS = ("50ms", "1s", "1min", "1h")


def _iter_group_source_files(group_dir: Path, date_yyyymmdd: str | None = None) -> list[Path]:
    files = []
    for p in group_dir.glob("*.ndjson"):
        if p.is_file():
            if date_yyyymmdd and not p.name.startswith(f"{date_yyyymmdd}-"):
                continue
            files.append(p)
    files.sort(key=lambda p: p.name)
    return files


def _to_scalar_value(entry: dict):
    if "value_num" in entry and entry.get("value_num") is not None:
        return entry.get("value_num")
    v_str = entry.get("value_str")
    if v_str not in (None, ""):
        return v_str
    return None


def _iter_points_from_line(row: dict):
    ts = row.get("ts")
    ts_epoch_ms = row.get("ts_epoch_ms")
    if not ts:
        return

    # snapshot format
    values = row.get("values")
    if isinstance(values, dict):
        for variable, value in values.items():
            if value is None or value == "":
                continue
            yield {
                "variable": str(variable),
                "point": {"ts": ts, "ts_epoch_ms": ts_epoch_ms, "value": value},
            }
        return

    # legacy row format
    variable = row.get("variable")
    if not variable:
        return
    value = _to_scalar_value(row)
    if value is None:
        return
    yield {
        "variable": str(variable),
        "point": {"ts": ts, "ts_epoch_ms": ts_epoch_ms, "value": value},
    }


def _safe_file_name(variable: str) -> str:
    # 파일시스템 안전하고 역매핑 가능한 이름
    return quote(variable, safe="") + ".ndjson"


def _normalize_date_yyyymmdd(date_text: str | None) -> str | None:
    if not date_text:
        return None
    s = str(date_text).strip()
    if not s:
        return None
    if len(s) == 8 and s.isdigit():
        return s
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        raise ValueError("date는 YYYY-MM-DD 형식이어야 합니다.")


def _to_mmddyy(yyyymmdd: str) -> str:
    dt = datetime.strptime(yyyymmdd, "%Y%m%d")
    return dt.strftime("%m%d%y")


def _extract_ts_date_yyyymmdd(ts) -> str | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y%m%d")
    except Exception:
        return None


def rebuild_group_variable_aggregates(group_key: str, date_text: str | None = None) -> dict:
    """
    그룹 단위로 변수별 집계파일(by_variable[/MMDDYY]) 재생성.
    """
    if group_key not in _GROUPS:
        raise ValueError(f"unsupported group: {group_key}")
    date_yyyymmdd = _normalize_date_yyyymmdd(date_text)

    group_dir = _DATA_ROOT / group_key
    group_dir.mkdir(parents=True, exist_ok=True)

    by_var_dir = group_dir / "by_variable"
    by_var_dir.mkdir(parents=True, exist_ok=True)
    target_dir = by_var_dir / _to_mmddyy(date_yyyymmdd) if date_yyyymmdd else by_var_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    # 재생성: 기존 집계 파일 정리
    for p in target_dir.glob("*.ndjson"):
        if p.is_file():
            p.unlink()
    index_file = target_dir / "index.json"
    if index_file.exists():
        index_file.unlink()

    files = _iter_group_source_files(group_dir, date_yyyymmdd=date_yyyymmdd)
    handles: dict[str, object] = {}
    index_map: dict[str, str] = {}
    points = 0
    variables = 0
    try:
        for source in files:
            with source.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if date_yyyymmdd:
                        ts_date = _extract_ts_date_yyyymmdd(row.get("ts"))
                        if ts_date != date_yyyymmdd:
                            continue
                    for item in _iter_points_from_line(row) or []:
                        var = item["variable"]
                        point = item["point"]
                        out_name = _safe_file_name(var)
                        if var not in index_map:
                            index_map[var] = out_name
                        if out_name not in handles:
                            out_path = target_dir / out_name
                            handles[out_name] = out_path.open("a", encoding="utf-8")
                        h = handles[out_name]
                        h.write(json.dumps(point, ensure_ascii=True) + "\n")
                        points += 1
        variables = len(index_map)
    finally:
        for h in handles.values():
            try:
                h.close()
            except Exception:
                pass

    with index_file.open("w", encoding="utf-8") as f:
        json.dump(index_map, f, ensure_ascii=True, indent=2, sort_keys=True)

    return {
        "group": group_key,
        "date": date_yyyymmdd or "",
        "folder": target_dir.name,
        "source_files": len(files),
        "variables": variables,
        "points": points,
        "output_dir": str(target_dir),
    }


def rebuild_variable_aggregates(groups: list[str] | None = None, date_text: str | None = None) -> dict:
    target = groups or list(_GROUPS)
    for g in target:
        if g not in _GROUPS:
            raise ValueError(f"unsupported group: {g}")
    results = [rebuild_group_variable_aggregates(g, date_text=date_text) for g in target]
    return {"ok": True, "results": results}

