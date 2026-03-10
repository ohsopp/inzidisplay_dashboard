"""
PLC 수집 데이터를 InfluxDB 2.x에 기록.
measurement: plc, tag: variable=이름, field: value (숫자/문자)
"""
from datetime import datetime, timezone

from influxdb_config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET, is_configured

_client = None
_write_api = None


def _get_client():
    global _client, _write_api
    if _client is not None:
        return _write_api
    if not is_configured():
        print("[InfluxDB] 설정 없음 (INFLUX_URL 등)", flush=True)
        return None
    try:
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.write_api import SYNCHRONOUS
        _client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        # 배치 모드는 버퍼가 쌓여서 즉시 안 갈 수 있음 → 동기 쓰기로 매번 즉시 전송
        _write_api = _client.write_api(write_options=SYNCHRONOUS)
        print("[InfluxDB] 연결됨 %s (동기 쓰기)" % INFLUX_URL, flush=True)
        return _write_api
    except Exception as e:
        print("[InfluxDB] 연결 실패:", e, flush=True)
        return None


def write_plc_point(variable: str, value, device_type: str = ""):
    """
    단일 변수 한 점 기록.
    value: int, float, str (문자열은 field "value_str" 사용)
    """
    api = _get_client()
    if api is None:
        return False
    try:
        from influxdb_client import Point
        p = Point("plc").tag("variable", variable)
        if device_type:
            p = p.tag("device", device_type)
        if isinstance(value, (int, float)):
            p = p.field("value", value)
        else:
            p = p.field("value_str", str(value))
        api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        return True
    except Exception:
        return False


def write_plc_batch(records: list, timestamp: float | None = None):
    """
    records: [(variable, value, device_type?), ...]
    device_type 생략 시 "" 사용.
    timestamp: 폴링 완료 시점(초 단위 float, time.time()). None이면 기록 시점 사용.
               설정 시 UTC datetime으로 변환해 각 Point의 _time에 ms 단위까지 저장.
    """
    api = _get_client()
    if api is None:
        return False
    if not records:
        return False
    try:
        from influxdb_client import Point
        # datetime(UTC)으로 넘겨야 클라이언트가 _time을 초 단위로 잘리지 않고 ms까지 저장함
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp is not None else None
        points = []
        for r in records:
            variable = r[0]
            value = r[1]
            device_type = r[2] if len(r) > 2 else ""
            p = Point("plc").tag("variable", variable)
            if device_type:
                p = p.tag("device", device_type)
            if isinstance(value, (int, float)):
                p = p.field("value", value)
            else:
                p = p.field("value_str", str(value))
            if dt is not None:
                p = p.time(dt)
            points.append(p)
        api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
        return True
    except Exception as e:
        err_parts = [str(e)]
        cause = e
        while getattr(cause, "__cause__", None):
            cause = cause.__cause__
            err_parts.append(str(cause))
        err = " ".join(err_parts).lower()
        if "connection refused" in err or "errno 111" in err or "failed to establish" in err:
            print("\n[InfluxDB] 8086 연결 안됨 → InfluxDB가 꺼져 있습니다. 먼저 실행하세요:\n  cd ~/plc/plc_test && sudo docker-compose -f docker-compose.influxdb.yml up -d\n", flush=True)
        else:
            print("[InfluxDB] write 실패:", e, flush=True)
        return False


def is_connected() -> bool:
    """이미 연결된 클라이언트가 있는지 여부."""
    return _client is not None


def check_connection() -> tuple[bool, str]:
    """
    InfluxDB 연결 가능 여부. (연결 시도함)
    반환: (성공 여부, 메시지)
    """
    api = _get_client()
    if api is not None:
        return True, "연결됨"
    if not is_configured():
        return False, "설정 없음 (INFLUX_URL 등)"
    return False, "연결 실패 (URL/토큰/네트워크 확인)"


def close():
    global _client, _write_api
    if _client:
        try:
            _client.close()
        except Exception:
            pass
        _client = None
        _write_api = None
