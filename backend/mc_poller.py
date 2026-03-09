"""
MC 프로토콜(3E) 폴링. 웹 대시보드에서 폴링 시작 시 plc_mcprotocol.py(pymcprotocol)로
host:port(plc_tcp_fake_response 또는 실제 PLC)에 3E 요청을 보내고, 가짜 응답 서버가
응답한 패킷을 pymcprotocol이 파싱해 값을 받아 대시보드·InfluxDB에 전달합니다.
변수마다 TCP 연결 1회라, 개수 제한으로 첫 수신을 수 초 안에 받습니다.
"""
from mc_mapping import get_mc_entries
from plc_mcprotocol import read_mc_variables

POLL_INTERVAL_SEC = 1.0
# 변수마다 연결 1회라, 50개로 제한해 첫 수신 ~10초 이내 완료 (전부 넣으면 수 분 걸림)
POLL_ENTRY_LIMIT = 50


def run_poller(host, port, on_parsed, on_error, stop_event):
    """
    폴링 스레드: host:port에 3E 요청 → 수신값을 대시보드 + InfluxDB에 전달.
    """
    _first_poll_done = [False]

    def do_poll():
        try:
            entries = get_mc_entries()
            if not entries:
                print("[MC] mc_fake_values.json 항목 없음", flush=True)
                return
            # 첫 수신을 빠르게 하기 위해 상위 N개만 폴링
            entries = entries[:POLL_ENTRY_LIMIT]
            if not _first_poll_done[0]:
                print("[MC] 폴링 시작 (%d개 변수) → 수신 후 InfluxDB 기록" % len(entries), flush=True)
            parsed = read_mc_variables(host, port, entries)
            if parsed:
                if not _first_poll_done[0]:
                    non_dash = sum(1 for v in parsed.values() if v != "-")
                    print("[MC] 첫 수신 완료 (유효값 %d건) → InfluxDB 기록" % non_dash, flush=True)
                    _first_poll_done[0] = True
                on_parsed(parsed)
        except Exception as e:
            on_error(str(e))

    try:
        do_poll()
    except Exception as e:
        on_error(str(e))

    while not stop_event.is_set():
        if stop_event.wait(POLL_INTERVAL_SEC):
            break
        try:
            do_poll()
        except Exception as e:
            on_error(str(e))
