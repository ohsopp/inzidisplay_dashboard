"""
대시보드 MC 폴러에서 받은 parsed 데이터를 InfluxDB에 기록.
- measurement를 디바이스 타입(M/Y/D)으로 분리
- 모든 변수·모든 값(숫자/문자 포함) 저장
"""
from mc_mapping import get_name_to_device
from influxdb_writer import write_plc_batch

_first_write_logged = False


def write_parsed_to_influx(
    parsed: dict, timestamp: float | None = None, interval_key: str | None = None
) -> None:
    """
    MC 폴러에서 받은 parsed {변수명: 값}을 규칙에 따라 InfluxDB에 기록.
    timestamp: 폴링 완료 시점(초 단위 float, time.time()). None이면 기록 시점 사용.
    interval_key: 폴링 스레드 키(50ms|1s|1min|1h). 로깅용.
    """
    global _first_write_logged
    if not parsed:
        return
    name_to_device = get_name_to_device()
    wrote_any = False

    grouped_records = {"M": [], "Y": [], "D": []}
    unknown_records = []
    for name, val in parsed.items():
        device = str(name_to_device.get(name) or "").strip().upper()
        if device in grouped_records:
            # 0/False/"0" 포함, 수신된 값을 그대로 저장한다.
            grouped_records[device].append((name, val, device))
        else:
            unknown_records.append((name, val, ""))

    for device in ("M", "Y", "D"):
        records = grouped_records[device]
        if not records:
            continue
        ok = write_plc_batch(records, timestamp=timestamp, measurement=device)
        wrote_any = ok or wrote_any
        if not _first_write_logged and not ok:
            print(f"[InfluxDB] {device} 기록 실패 (연결/버킷 확인)", flush=True)

    # 매핑되지 않은 변수는 호환성을 위해 plc measurement에 저장.
    if unknown_records:
        wrote_any = write_plc_batch(unknown_records, timestamp=timestamp, measurement="plc") or wrote_any

    # 첫 수신 시 한 번만 상세 로그 (원인 파악용)
    if not _first_write_logged:
        print(
            "[InfluxDB] 수신 %d건(%s) → M:%d Y:%d D:%d unknown:%d 기록 시도"
            % (
                len(parsed),
                interval_key or "unknown",
                len(grouped_records["M"]),
                len(grouped_records["Y"]),
                len(grouped_records["D"]),
                len(unknown_records),
            ),
            flush=True,
        )
        if wrote_any:
            print("[InfluxDB] MC → InfluxDB 기록 완료 (이후 주기적 기록)", flush=True)
            _first_write_logged = True
        elif len(parsed) > 0 and not any(grouped_records.values()):
            print("[InfluxDB] 원인: name_to_device 매칭 안됨 (수신 이름과 mc_fake_values.json name 불일치?)", flush=True)
            _first_write_logged = True  # 한 번만 로그
        _first_write_logged = True  # 상세 로그는 첫 1회만
