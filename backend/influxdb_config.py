"""
InfluxDB 2.x 연결 설정.
환경변수: INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
"""
import os

# localhost 대신 127.0.0.1 사용 (IPv6 ::1 해석 시 Docker 컨테이너에 연결 안 될 수 있음)
INFLUX_URL = os.environ.get("INFLUX_URL", "http://127.0.0.1:8086")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "plc-influx-admin-token")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "plc")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "plc_data")


def is_configured() -> bool:
    return bool(INFLUX_URL and INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET)
