"""
PLC 수집 데이터를 InfluxDB 2.x에 기록.
- PLC MC 경로: measurement = 폴링 주기 이름(50ms | 1s | 1h), tag variable, field value
  (D/M/Y 디바이스로 measurement를 나누지 않음. 구버전 measurement는 조회 호환용으로 Flux에만 포함)
"""
from datetime import datetime, timezone

from influxdb_config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET, is_configured

# 테스트·수동 기록 등 주기 없을 때만 사용
PLC_INFLUX_MEASUREMENT = "plc_data"

_INTERVAL_MEASUREMENTS = frozenset({"50ms", "1s", "1h"})

_LEGACY_PLC_MEASUREMENTS = frozenset(
    {"50ms", "1s", "1h", "plc_data", "plc", "M", "Y", "D"}
)


def _resolve_batch_measurement(measurement: str | None, interval_key: str | None) -> str:
    """호출부가 measurement를 안 넘기면 interval_key(50ms|1s|1h)를 measurement 이름으로 쓴다."""
    if measurement is not None:
        return measurement
    if interval_key in _INTERVAL_MEASUREMENTS:
        return interval_key
    return PLC_INFLUX_MEASUREMENT


def _plc_measurement_flux_set() -> str:
    return ", ".join(f'"{m}"' for m in sorted(_LEGACY_PLC_MEASUREMENTS))


_client = None
_write_api = None


def _field_value_for_influx(value):
    """
    measurement plc의 field 'value'는 버킷에서 타입이 한 번 정해지면 바꿀 수 없다.
    정수/실수/불리언이 섞이면 422 field type conflict가 나므로 숫자는 항상 float로 통일한다.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return value


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
        print(
            "[InfluxDB] 연결됨 %s 버킷=%s (동기 쓰기)"
            % (INFLUX_URL, INFLUX_BUCKET),
            flush=True,
        )
        return _write_api
    except Exception as e:
        print("[InfluxDB] 연결 실패:", e, flush=True)
        return None


def _get_client_obj():
    """쓰기용이 아닌 query_api 등에 쓸 InfluxDBClient 인스턴스 반환."""
    _get_client()
    return _client


def write_plc_point(variable: str, value, device_type: str = "", measurement: str = PLC_INFLUX_MEASUREMENT):
    """
    단일 변수 한 점 기록.
    value: int, float, str (문자열은 field "value_str" 사용)
    """
    api = _get_client()
    if api is None:
        return False
    try:
        from influxdb_client import Point
        p = Point(measurement).tag("variable", variable)
        if device_type:
            p = p.tag("device", device_type)
        if isinstance(value, (int, float, bool)):
            p = p.field("value", _field_value_for_influx(value))
            fields = {"value": _field_value_for_influx(value)}
        else:
            p = p.field("value_str", str(value))
            fields = {"value_str": str(value)}
        api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        # Parquet: PLC는 plc_wide_parquet_writer만 사용 (plc_data/YYYYMMDD.parquet 단일 파일).
        # append_point_to_parquet를 쓰면 plc_data/M·D·Y 등으로 디렉터리가 나뉜다.
        return True
    except Exception:
        return False


def write_plc_batch(
    records: list,
    timestamp: float | None = None,
    measurement: str | None = None,
    interval_key: str | None = None,
):
    """
    records: [(variable, value, device_type?), ...]
    device_type 생략 시 "" 사용.
    timestamp: 폴링 완료 시점(초 단위 float, time.time()). None이면 기록 시점 사용.
               설정 시 UTC datetime으로 변환해 각 Point의 _time에 ms 단위까지 저장.
    measurement: None이면 interval_key(50ms|1s|1h)를 measurement 이름으로 사용, 없으면 plc_data.
    interval_key: 주기가 measurement와 같을 때는 중복이므로 interval 태그를 붙이지 않음.
    """
    resolved = _resolve_batch_measurement(measurement, interval_key)
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
            p = Point(resolved).tag("variable", variable)
            if interval_key and resolved == PLC_INFLUX_MEASUREMENT:
                p = p.tag("interval", interval_key)
            if device_type:
                p = p.tag("device", device_type)
            if isinstance(value, (int, float, bool)):
                fv = _field_value_for_influx(value)
                p = p.field("value", fv)
            else:
                fv = str(value)
                p = p.field("value_str", fv)
            if dt is not None:
                p = p.time(dt)
            points.append(p)
        api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
        # Parquet: plc_wide_parquet_writer(일별 와이드)에서 influxdb_from_mc 경로로만 기록.
        return True
    except Exception as e:
        err_parts = [str(e)]
        cause = e
        while getattr(cause, "__cause__", None):
            cause = cause.__cause__
            err_parts.append(str(cause))
        err = " ".join(err_parts).lower()
        if "connection refused" in err or "errno 111" in err or "failed to establish" in err:
            print(
                "\n[InfluxDB] 연결 안됨 (%s) → InfluxDB 주소/포트·실행 여부를 확인하세요.\n"
                "  예: cd Inzi/inzidisplay_dashboard && docker compose -f docker-compose.influxdb.yml up -d\n"
                % (INFLUX_URL,),
                flush=True,
            )
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


def export_plc_csv(start_iso: str, end_iso: str) -> tuple[str | None, str | None]:
    """
    지정 구간(시작/종료 ISO8601)의 plc measurement 데이터를 Flux로 조회해 CSV 문자열 반환.
    반환: (csv_string, None) 성공 시, (None, error_message) 실패 시.
    """
    import csv
    import io
    client = _get_client_obj()
    if client is None or not is_configured():
        return None, "InfluxDB 연결이 없습니다."
    start_ = start_iso.strip().replace(" ", "T", 1)
    end_ = end_iso.strip().replace(" ", "T", 1)
    if not start_ or not end_:
        return None, "시작/종료 시간을 입력하세요."
    if not start_.endswith("Z") and "+" not in start_:
        start_ = start_ + "Z"
    if not end_.endswith("Z") and "+" not in end_:
        end_ = end_ + "Z"
    ms = _plc_measurement_flux_set()
    query = (
        f'from(bucket: "{INFLUX_BUCKET}") '
        f'|> range(start: time(v: "{start_}"), stop: time(v: "{end_}")) '
        f'|> filter(fn: (r) => contains(value: r._measurement, set: [{ms}])) '
        '|> sort(columns: ["_time", "variable"])'
    )
    try:
        query_api = client.query_api()
        tables = query_api.query(query, org=INFLUX_ORG)
    except Exception as e:
        return None, str(e)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["time", "variable", "field", "value"])
    row_count = 0
    for table in tables or []:
        for record in getattr(table, "records", []) or []:
            vals = getattr(record, "values", {}) or {}
            t = vals.get("_time", "")
            var = vals.get("variable", "")
            field = vals.get("_field", "")
            val = vals.get("_value", "")
            if isinstance(val, (int, float)):
                val = str(val)
            writer.writerow([t, var, field, val])
            row_count += 1
    if row_count == 0:
        writer.writerow([])
        return out.getvalue(), None  # 헤더만 있는 CSV도 반환
    return out.getvalue(), None


def export_plc_csv_pivot(start_iso: str, end_iso: str, group_key: str) -> tuple[str | None, str | None]:
    """
    지정 구간·폴링 그룹(50ms|1s)의 plc 데이터를 조회해
    행=변수명, 열=타임스탬프, 셀=value 인 CSV 반환.
    반환: (csv_string, None) 성공 시, (None, error_message) 실패 시.
    """
    import csv
    import io

    from mc_mapping import POLL_INTERVAL_KEYS
    from plc_wide_parquet_writer import get_wide_column_names_for_export_interval

    if group_key not in POLL_INTERVAL_KEYS:
        return None, f"지원하지 않는 그룹입니다. 사용 가능: {', '.join(POLL_INTERVAL_KEYS)}"
    client = _get_client_obj()
    if client is None or not is_configured():
        return None, "InfluxDB 연결이 없습니다."
    start_ = start_iso.strip().replace(" ", "T", 1)
    end_ = end_iso.strip().replace(" ", "T", 1)
    if not start_ or not end_:
        return None, "시작/종료 시간을 입력하세요."
    if not start_.endswith("Z") and "+" not in start_:
        start_ = start_ + "Z"
    if not end_.endswith("Z") and "+" not in end_:
        end_ = end_ + "Z"
    ms = _plc_measurement_flux_set()
    query = (
        f'from(bucket: "{INFLUX_BUCKET}") '
        f'|> range(start: time(v: "{start_}"), stop: time(v: "{end_}")) '
        f'|> filter(fn: (r) => contains(value: r._measurement, set: [{ms}])) '
        '|> sort(columns: ["_time", "variable"])'
    )
    try:
        query_api = client.query_api()
        tables = query_api.query(query, org=INFLUX_ORG)
    except Exception as e:
        return None, str(e)
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))

    def _time_to_utc_key(raw) -> str | None:
        """InfluxDB _time(문자열 또는 datetime) → UTC 기준 정규화 키 문자열."""
        if raw is None:
            return None
        if hasattr(raw, "year"):  # datetime
            dt = raw
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        s = str(raw).strip()
        if not s:
            return None
        try:
            s = s.replace("Z", "+00:00").replace(" ", "T")
            if "+00:00" not in s and s[-6:] != "-00:00":
                s = s + "+00:00"
            if "." in s and "+" in s:
                i, j = s.index("."), s.index("+")
                if j - i > 7:
                    s = s[: i + 7] + s[j:]
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            return None

    def _utc_key_to_kst_display(utc_iso: str) -> str:
        """UTC iso 키 → KST 표시 (YYYY-MM-DD HH:MM:SS)."""
        if not utc_iso:
            return utc_iso
        try:
            s = utc_iso.replace("Z", "+00:00").replace(" ", "T")
            if "+00:00" not in s and s[-6:] != "-00:00":
                s = s + "+00:00"
            if "." in s and "+" in s:
                i, j = s.index("."), s.index("+")
                if j - i > 7:
                    s = s[: i + 7] + s[j:]
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return utc_iso

    # (variable, time_utc_key) -> value
    data: dict[tuple[str, str], str] = {}
    for table in tables or []:
        for record in getattr(table, "records", []) or []:
            vals = getattr(record, "values", {}) or {}
            t_key = _time_to_utc_key(vals.get("_time"))
            var = vals.get("variable", "")
            meas = str(vals.get("_measurement", "") or "")
            row_iv = vals.get("interval")
            if meas == group_key:
                pass
            elif meas == PLC_INFLUX_MEASUREMENT and str(row_iv or "") == group_key:
                pass
            else:
                continue
            val = vals.get("_value", "")
            if isinstance(val, (int, float)):
                val = str(val)
            else:
                val = str(val) if val is not None else ""
            if var and t_key:
                data[(var, t_key)] = val
    var_names = get_wide_column_names_for_export_interval(group_key)
    if not var_names:
        return None, f"해당 그룹({group_key})에 변수가 없습니다."
    allowed = frozenset(var_names)
    data_filtered = {k: v for k, v in data.items() if k[0] in allowed}
    ordered_vars = list(var_names)
    timestamps_with_data = sorted({t for (v, t) in data_filtered})
    # CSV 열 헤더: 모든 타임스탬프를 KST로 표시
    kst_headers = [_utc_key_to_kst_display(t) for t in timestamps_with_data]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["variable"] + kst_headers)
    for var in ordered_vars:
        row = [var] + [data_filtered.get((var, t), "") for t in timestamps_with_data]
        writer.writerow(row)
    return out.getvalue(), None
