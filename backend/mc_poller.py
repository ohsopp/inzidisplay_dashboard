"""
MC 프로토콜(3E) 폴링. 웹 대시보드에서 폴링 시작 시 host:port(가짜/실제 PLC)에 3E 요청을 보내
수신값을 대시보드·InfluxDB에 전달합니다.
주기별 4개 스레드: 50ms / 1s / 1min / 1h. 같은 주기 내에서는 100개씩 청크·2스레드 병렬 읽기.

연결 직후: 전체 변수를 단일 TCP 세션·순차 읽기로 1회 스냅샷(MC_BOOTSTRAP_SEQUENTIAL_LOAD, 기본 on).
이후 주기 폴링은 각 스레드가 담당하며, 부트스트랩이 성공하면 첫 주기 폴링은 생략한다.

접속 경합 완화: read_mc_variables 호출을 전역 락으로 직렬화(MC_SERIALIZE_PLC_READS, 기본 on).
  - 트레이드오프: 동시 다발 연결은 줄지만, 한 번에 하나의 PLC 읽기만 진행된다.
  - 더 나은 확장: 단일 워커 큐 + 연결 재사용(장시간 연결 유지)은 plc_mcprotocol 쪽 리팩터가 필요하다.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from mc_mapping import get_mc_entries_by_poll_interval
from plc_mcprotocol import read_mc_variables

# 폴링할 변수 개수 제한. 0이면 제한 없음. 적용 시 50ms 그룹만 제한 (나머지 그룹은 고정 개수).
POLL_ENTRY_LIMIT = int(os.environ.get("MC_POLL_ENTRY_LIMIT", "0") or "0")
CHUNK_SIZE = int(os.environ.get("MC_POLL_CHUNK_SIZE", "100") or "100")
MAX_WORKERS = int(os.environ.get("MC_POLL_MAX_WORKERS", "2") or "2")
FAILED_POLL_RETRY_SEC = float(os.environ.get("MC_FAILED_POLL_RETRY_SEC", "1.0") or "1.0")

def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")

# 부트스트랩: 연결 직후 전체 엔트리 1회 순차 로드 (기본 True)
BOOTSTRAP_SEQUENTIAL_LOAD = _env_bool("MC_BOOTSTRAP_SEQUENTIAL_LOAD", True)
# PLC 읽기 직렬화 — 동시 연결·요청 경합 완화 (기본 True)
SERIALIZE_PLC_READS = _env_bool("MC_SERIALIZE_PLC_READS", True)

_plc_io_lock = threading.Lock()

INTERVAL_50MS = 0.05
INTERVAL_1S = 1.0
INTERVAL_1MIN = 60.0
INTERVAL_1H = 3600.0
MIN_INTERVAL_SEC = 0.05
MAX_INTERVAL_SEC = 12 * 3600.0

_interval_lock = threading.Lock()
_interval_by_key = {
    "50ms": INTERVAL_50MS,
    "1s": INTERVAL_1S,
    "1min": INTERVAL_1MIN,
    "1h": INTERVAL_1H,
}


def _poll_chunk(host, port, chunk):
    """한 청크에 대해 read_mc_variables 호출. SERIALIZE_PLC_READS 시 전역 락으로 직렬화."""
    if SERIALIZE_PLC_READS:
        with _plc_io_lock:
            return read_mc_variables(host, port, chunk)
    return read_mc_variables(host, port, chunk)


def _bootstrap_sequential_load(host, port, all_entries, on_parsed, on_error):
    """
    전체 엔트리를 한 번의 연결로 순차 읽기. on_parsed(merged, None) — ndjson/주기 태그 없음.
    성공 시 True (전부 '-'면 False).
    """
    if not all_entries:
        return False
    try:
        merged = _poll_chunk(host, port, all_entries)
        if not merged:
            return False
        if all(v == "-" for v in merged.values()):
            return False
        on_parsed(merged, None)
        return True
    except Exception as e:
        on_error(str(e))
        return False


def _do_poll_entries(host, port, entries, on_parsed, on_error, interval_key=None):
    """엔트리 리스트를 청크로 나누어 병렬 폴링 후 on_parsed(merged, interval_key) 호출."""
    if not entries:
        return False
    chunks = [entries[i : i + CHUNK_SIZE] for i in range(0, len(entries), CHUNK_SIZE)]
    merged = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_poll_chunk, host, port, c) for c in chunks]
        for future in as_completed(futures):
            try:
                parsed = future.result()
                if parsed:
                    merged.update(parsed)
            except Exception as e:
                on_error(str(e))
    if merged:
        # 타임아웃/일시 오류로 전체 값이 '-'인 경우는 기존 정상값 유지를 위해 전달하지 않는다.
        if all(v == "-" for v in merged.values()):
            return False
        on_parsed(merged, interval_key)
        return True
    return False


def get_interval_seconds(key):
    with _interval_lock:
        return _interval_by_key.get(key)


def normalize_poll_intervals(interval_map_sec):
    """
    입력값 검증/정규화 후 {key: sec(float)} 반환. (메모리 변경 없음)
    """
    valid_keys = ("50ms", "1s", "1min", "1h")
    normalized = {}
    for key in valid_keys:
        if key not in interval_map_sec:
            continue
        value = float(interval_map_sec[key])
        if value < MIN_INTERVAL_SEC or value > MAX_INTERVAL_SEC:
            raise ValueError("폴링레이트는 50ms 이상 12시간 이하로 설정해야 합니다.")
        normalized[key] = value
    return normalized


def set_poll_intervals(interval_map_sec):
    """
    interval_map_sec: {"50ms": sec, "1s": sec, "1min": sec, "1h": sec}
    """
    normalized = normalize_poll_intervals(interval_map_sec)
    with _interval_lock:
        for key, value in normalized.items():
            _interval_by_key[key] = value


def get_poll_intervals():
    with _interval_lock:
        return dict(_interval_by_key)


def get_poll_thread_entries():
    e_50ms, e_1s, e_1min, e_1h = get_mc_entries_by_poll_interval()
    if POLL_ENTRY_LIMIT > 0 and len(e_50ms) > POLL_ENTRY_LIMIT:
        e_50ms = e_50ms[:POLL_ENTRY_LIMIT]
    return {
        "50ms": e_50ms,
        "1s": e_1s,
        "1min": e_1min,
        "1h": e_1h,
    }


def _run_interval_loop(host, port, entries, interval_key, on_parsed, on_error, stop_event, label, skip_initial=False):
    """한 주기 스레드: 첫 폴링 1회 후(또는 skip_initial 시 생략), interval_sec마다 폴링."""
    if not entries:
        return
    interval_sec = get_interval_seconds(interval_key) or MIN_INTERVAL_SEC
    retry_sec = max(MIN_INTERVAL_SEC, min(FAILED_POLL_RETRY_SEC, interval_sec))
    next_wait_sec = interval_sec
    last_polled_at = time.monotonic()
    if not skip_initial:
        try:
            ok = _do_poll_entries(host, port, entries, on_parsed, on_error, interval_key=interval_key)
            next_wait_sec = interval_sec if ok else retry_sec
        except Exception as e:
            on_error(str(e))
            next_wait_sec = retry_sec
        last_polled_at = time.monotonic()
    while not stop_event.is_set():
        # 고정 wait(interval_sec)을 쓰면 긴 주기 대기 중 주기 변경이 즉시 반영되지 않는다.
        # 짧은 tick으로 남은 시간을 재계산해, 1h -> 1s 변경도 빠르게 반영한다.
        while not stop_event.is_set():
            interval_sec = get_interval_seconds(interval_key) or MIN_INTERVAL_SEC
            retry_sec = max(MIN_INTERVAL_SEC, min(FAILED_POLL_RETRY_SEC, interval_sec))
            due_at = last_polled_at + next_wait_sec
            now = time.monotonic()
            remaining = due_at - now
            if remaining <= 0:
                break
            if stop_event.wait(min(remaining, 0.2)):
                break
        if stop_event.is_set():
            break
        try:
            ok = _do_poll_entries(host, port, entries, on_parsed, on_error, interval_key=interval_key)
            next_wait_sec = interval_sec if ok else retry_sec
            last_polled_at = time.monotonic()
        except Exception as e:
            on_error(str(e))
            next_wait_sec = retry_sec


def run_poller(host, port, on_parsed, on_error, stop_event):
    """
    주기별 4스레드로 폴링 실행.
    - 50ms: 나머지 전부 (온도·압력·각종 Word/Dword 등)
    - 1s: Boolean 전체 + 토탈카운터, 현재생산량, 과부족수량, 카운트수량, 금일가동수량, 금일 가동시간
    - 1min: C.P.M, S.P.M
    - 1h: 현재/다음 금형번호·금형이름·다이하이트·바란스에어, 생산계획량, 목표 타발수
    """
    grouped = get_poll_thread_entries()
    e_50ms = grouped["50ms"]
    e_1s = grouped["1s"]
    e_1min = grouped["1min"]
    e_1h = grouped["1h"]
    total = len(e_50ms) + len(e_1s) + len(e_1min) + len(e_1h)
    if total == 0:
        print("[MC] mc_fake_values.json 항목 없음", flush=True)
        return
    print("[MC] 폴링 시작 (총 %d개) 50ms=%d, 1s=%d, 1min=%d, 1h=%d"
          % (total, len(e_50ms), len(e_1s), len(e_1min), len(e_1h)), flush=True)

    all_ordered = e_50ms + e_1s + e_1min + e_1h
    skip_initial_after_bootstrap = False
    if BOOTSTRAP_SEQUENTIAL_LOAD and all_ordered:
        t_boot = time.perf_counter()
        boot_ok = _bootstrap_sequential_load(host, port, all_ordered, on_parsed, on_error)
        skip_initial_after_bootstrap = boot_ok
        print(
            "[MC] 초기 순차 로드 %s (%.2fs, %d개)"
            % ("완료" if boot_ok else "실패·미전송(주기 폴링에서 재시도)", time.perf_counter() - t_boot, len(all_ordered)),
            flush=True,
        )

    threads = []
    for entries, interval_key, label in [
        (e_50ms, "50ms", "50ms"),
        (e_1s, "1s", "1s"),
        (e_1min, "1min", "1min"),
        (e_1h, "1h", "1h"),
    ]:
        if not entries:
            continue
        t = threading.Thread(
            target=_run_interval_loop,
            args=(
                host,
                port,
                entries,
                interval_key,
                on_parsed,
                on_error,
                stop_event,
                label,
                skip_initial_after_bootstrap,
            ),
            name="mc_poll_%s" % label,
            daemon=True,
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
