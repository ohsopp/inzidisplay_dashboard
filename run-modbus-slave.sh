#!/bin/bash
# Modbus TCP 슬레이브 실행. 프로젝트 venv에 pymodbus 설치됨.
# 포트 502 사용 시: sudo ./run-modbus-slave.sh
cd "$(dirname "$0")"
if [ -d "venv" ]; then
  exec venv/bin/python3 modbus_slave.py "$@"
fi
if [ -d "backend/venv" ]; then
  exec backend/venv/bin/python3 modbus_slave.py "$@"
fi
exec python3 modbus_slave.py "$@"
