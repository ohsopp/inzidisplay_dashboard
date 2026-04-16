"""
대시보드 MC 폴러에서 받은 parsed 데이터를 InfluxDB에 기록.
- measurement = 폴링 주기(50ms | 1s), tag variable (D/M/Y로 measurement 분리하지 않음)
- Parquet 와이드와 동일한 변수만 기록(dword/string 중복 stem은 최소 주소 1개)
- Parquet(와이드·일별 단일 파일)는 plc_wide_parquet_writer에서 처리
"""
import time

from influxdb_writer import _resolve_batch_measurement, write_plc_batch
from plc_wide_parquet_writer import filter_parsed_to_wide_columns

_first_write_logged = False


def write_parsed_to_influx(
    parsed: dict, timestamp: float | None = None, interval_key: str | None = None
) -> None:
    """
    MC 폴러에서 받은 parsed {변수명: 값}을 규칙에 따라 InfluxDB에 기록.
    timestamp: 폴링 완료 시점(초 단위 float, time.time()). None이면 기록 시점 사용.
    interval_key: 폴링 스레드 키(50ms|1s) → Influx measurement 이름으로 사용.
    """
    global _first_write_logged
    if not parsed:
        return
    ts = timestamp if timestamp is not None else time.time()
    if interval_key in ("50ms", "1s"):
        try:
            from plc_wide_parquet_writer import append_plc_wide_row

            append_plc_wide_row(parsed, interval_key, ts)
        except Exception as e:
            print("[PLC Wide Parquet] 기록 오류:", e, flush=True)

    filtered = filter_parsed_to_wide_columns(parsed)
    if not filtered:
        return

    records = [(name, val) for name, val in filtered.items()]
    ok = write_plc_batch(records, timestamp=ts, interval_key=interval_key)
    meas = _resolve_batch_measurement(None, interval_key)

    if not _first_write_logged:
        print(
            "[InfluxDB] %s → measurement=%s %d건 기록 %s"
            % (
                interval_key or "?",
                meas,
                len(records),
                "ok" if ok else "실패",
            ),
            flush=True,
        )
        _first_write_logged = True
