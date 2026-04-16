"""
MC 프로토콜 수집 데이터를 InfluxDB에 저장하는 폴러.
- 알람(M): 1초마다 수신, 값이 1일 때만 InfluxDB 저장
- 데이터(D): 50ms마다 수신·저장 (단, 금형번호/금형이름/다이하이트/바란스에어/생산계획량 등은 1시간마다 저장)
- 경고등/부저(Y): 1초마다 수신·저장
"""
import threading
import time

from mc_mapping import get_mc_entries_by_device, get_mc_entries_hourly_d
from plc_mcprotocol import read_mc_variables
from influxdb_writer import write_plc_batch
from plc_wide_parquet_writer import filter_parsed_to_wide_columns


INTERVAL_M_Y_SEC = 1.0
INTERVAL_D_MS = 0.05
INTERVAL_D_HOURLY_SEC = 3600.0

# 첫 기록 시 한 번만 로그 (과다 로그 방지)
_influx_first_write_logged = {"M": False, "D": False, "Y": False, "D_hourly": False}


def _run_m_poller(host: str, port: int, stop_event: threading.Event):
    """M: 1초마다 읽기, 값이 1인 경우만 InfluxDB 저장."""
    entries = get_mc_entries_by_device("M")
    if not entries:
        print("[InfluxDB] M 항목 없음, 폴러 스킵", flush=True)
        return
    while not stop_event.is_set():
        if stop_event.wait(INTERVAL_M_Y_SEC):
            break
        try:
            parsed = filter_parsed_to_wide_columns(read_mc_variables(host, port, entries))
            records = []
            for name, val in parsed.items():
                if val == 1 or val == "1" or (isinstance(val, (int, float)) and val == 1):
                    records.append((name, 1))
            if records:
                if write_plc_batch(records, interval_key="1s") and not _influx_first_write_logged["M"]:
                    print("[InfluxDB] 첫 기록 (M) %d건" % len(records), flush=True)
                    _influx_first_write_logged["M"] = True
        except Exception as e:
            print("[InfluxDB] M 폴링 오류:", e, flush=True)


def _run_y_poller(host: str, port: int, stop_event: threading.Event):
    """Y: 1초마다 읽기, 모두 InfluxDB 저장."""
    entries = get_mc_entries_by_device("Y")
    if not entries:
        print("[InfluxDB] Y 항목 없음, 폴러 스킵", flush=True)
        return
    while not stop_event.is_set():
        if stop_event.wait(INTERVAL_M_Y_SEC):
            break
        try:
            parsed = filter_parsed_to_wide_columns(read_mc_variables(host, port, entries))
            records = [(name, val) for name, val in parsed.items() if val != "-"]
            if records:
                if write_plc_batch(records, interval_key="1s") and not _influx_first_write_logged["Y"]:
                    print("[InfluxDB] 첫 기록 (Y) %d건" % len(records), flush=True)
                    _influx_first_write_logged["Y"] = True
        except Exception as e:
            print("[InfluxDB] Y 폴링 오류:", e, flush=True)


def _run_d_poller(host: str, port: int, stop_event: threading.Event):
    """D(일반): 50ms마다 읽기·저장 (hourly 제외)."""
    entries = get_mc_entries_by_device("D", exclude_hourly_d=True)
    if not entries:
        print("[InfluxDB] D(일반) 항목 없음, 폴러 스킵", flush=True)
        return
    while not stop_event.is_set():
        if stop_event.wait(INTERVAL_D_MS):
            break
        try:
            parsed = filter_parsed_to_wide_columns(read_mc_variables(host, port, entries))
            records = [(name, val) for name, val in parsed.items() if val != "-"]
            if records:
                if write_plc_batch(records, interval_key="50ms") and not _influx_first_write_logged["D"]:
                    print("[InfluxDB] 첫 기록 (D) %d건" % len(records), flush=True)
                    _influx_first_write_logged["D"] = True
        except Exception as e:
            print("[InfluxDB] D 폴링 오류:", e, flush=True)


def _run_d_hourly_poller(host: str, port: int, stop_event: threading.Event):
    """D(1시간): 1시간마다 읽기·저장 (금형번호/이름/다이하이트/바란스에어/생산계획량)."""
    entries = get_mc_entries_hourly_d()
    if not entries:
        print("[InfluxDB] D(1시간) 항목 없음, 폴러 스킵", flush=True)
        return
    while not stop_event.is_set():
        if stop_event.wait(INTERVAL_D_HOURLY_SEC):
            break
        try:
            parsed = filter_parsed_to_wide_columns(read_mc_variables(host, port, entries))
            records = [(name, val) for name, val in parsed.items() if val != "-"]
            if records:
                if write_plc_batch(records, interval_key="1h") and not _influx_first_write_logged["D_hourly"]:
                    print("[InfluxDB] 첫 기록 (D 1시간) %d건" % len(records), flush=True)
                    _influx_first_write_logged["D_hourly"] = True
        except Exception as e:
            print("[InfluxDB] D(1시간) 폴링 오류:", e, flush=True)


def start(host: str, port: int):
    """
    InfluxDB용 MC 폴러 스레드 시작.
    M 1초/값1만 저장, D 50ms 저장(일부 1시간), Y 1초 저장.
    반환: (stop_event, list of threads). stop_event.set() 후 join 하면 종료.
    """
    stop_event = threading.Event()
    threads = []

    for target, name in [
        (_run_m_poller, "influx_m"),
        (_run_y_poller, "influx_y"),
        (_run_d_poller, "influx_d"),
        (_run_d_hourly_poller, "influx_d_hourly"),
    ]:
        t = threading.Thread(target=target, args=(host, port, stop_event), name=name, daemon=True)
        t.start()
        threads.append(t)

    return stop_event, threads
