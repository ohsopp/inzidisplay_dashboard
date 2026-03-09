"""
대시보드 MC 폴러에서 받은 parsed 데이터를 InfluxDB에 기록.
- 알람(M): 값이 1일 때만 기록
- 경고등/부저(Y): 매 수신 기록
- 데이터(D) 일반: 매 수신 기록
- 데이터(D) 1시간 항목: 1시간마다만 기록
"""
import time

from mc_mapping import get_name_to_device, INFLUX_HOURLY_SAVE_NAMES
from influxdb_writer import write_plc_batch

_last_hourly_write = 0.0
_HOURLY_INTERVAL = 3600.0
_first_write_logged = False
_dash_only_logged = False  # "수신 데이터가 모두 '-'" 한 번만 출력


def write_parsed_to_influx(parsed: dict) -> None:
    """
    MC 폴러에서 받은 parsed {변수명: 값}을 규칙에 따라 InfluxDB에 기록.
    """
    global _first_write_logged, _dash_only_logged
    if not parsed:
        return
    name_to_device = get_name_to_device()
    wrote_any = False

    # M: 값이 1인 경우만
    m_records = []
    for name, val in parsed.items():
        if name_to_device.get(name) != "M":
            continue
        if val == 1 or val == "1" or (isinstance(val, (int, float)) and val == 1):
            m_records.append((name, 1, "M"))
    if m_records:
        ok = write_plc_batch(m_records)
        wrote_any = ok or wrote_any
        if not _first_write_logged and not ok:
            print("[InfluxDB] M 기록 실패 (연결/버킷 확인)", flush=True)

    # Y: 모두 (유효한 값만)
    y_records = [(name, val, "Y") for name, val in parsed.items()
                 if name_to_device.get(name) == "Y" and val != "-"]
    if y_records:
        ok = write_plc_batch(y_records)
        wrote_any = ok or wrote_any
        if not _first_write_logged and not ok:
            print("[InfluxDB] Y 기록 실패 (연결/버킷 확인)", flush=True)

    # D 일반(비-hourly): 매 수신 기록
    d_normal = [(name, val, "D") for name, val in parsed.items()
                if name_to_device.get(name) == "D" and name not in INFLUX_HOURLY_SAVE_NAMES and val != "-"]
    if d_normal:
        ok = write_plc_batch(d_normal)
        wrote_any = ok or wrote_any
        if not _first_write_logged and not ok:
            print("[InfluxDB] D 기록 실패 (연결/버킷 확인)", flush=True)

    # D 1시간 항목: 1시간마다만 기록
    global _last_hourly_write
    now = time.time()
    if now - _last_hourly_write >= _HOURLY_INTERVAL:
        d_hourly = [(name, val, "D") for name, val in parsed.items()
                    if name_to_device.get(name) == "D" and name in INFLUX_HOURLY_SAVE_NAMES and val != "-"]
        if d_hourly:
            wrote_any = write_plc_batch(d_hourly) or wrote_any
            _last_hourly_write = now

    # 첫 수신 시 한 번만 상세 로그 (원인 파악용)
    non_dash = sum(1 for v in parsed.values() if v != "-")
    total_records = len(m_records) + len(y_records) + len(d_normal)
    if not _first_write_logged:
        print("[InfluxDB] 수신 %d건, 유효값 %d건 → M:%d Y:%d D:%d 기록 시도" % (
            len(parsed), non_dash, len(m_records), len(y_records), len(d_normal)), flush=True)
        if wrote_any:
            print("[InfluxDB] MC → InfluxDB 기록 완료 (이후 주기적 기록)", flush=True)
            _first_write_logged = True
        elif non_dash > 0 and total_records == 0:
            print("[InfluxDB] 원인: name_to_device 매칭 안됨 (수신 이름과 mc_fake_values.json name 불일치?)", flush=True)
            _first_write_logged = True  # 한 번만 로그
        elif non_dash == 0 and not _dash_only_logged:
            print("[InfluxDB] 원인: 수신값이 전부 '-' (가짜서버 5002 미동작 또는 연결 실패)", flush=True)
            _dash_only_logged = True
        _first_write_logged = True  # 상세 로그는 첫 1회만
