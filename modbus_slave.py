#!/usr/bin/env python3
"""
Modbus TCP 슬레이브(서버). iolist.csv 주소 순서대로 Coils(경고/알람) + Holding Registers(데이터) 매핑.
기본값: Boolean 0/1, Word/Dword 유의미 더미, String "hello" 2바이트씩 분할.
"""
import csv
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
IOLIST_PATH = SCRIPT_DIR / "iolist.csv"

# 기본 포트 (502는 권한 필요; 테스트 시 5020 사용 가능). 환경변수 PORT 또는 인자로 변경 가능.
def _get_port():
    if os.environ.get("PORT"):
        return int(os.environ["PORT"])
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        return int(sys.argv[1])
    return 5020

HOST = os.environ.get("MODBUS_HOST", "0.0.0.0")
PORT = _get_port()

# Word/Dword 기본값 (iolist 주소 라벨 → 값). Dword는 32비트, 레지스터에는 상위/하위 워드로 저장.
REG_DEFAULTS = {
    "D140": 42,
    "D711": 3505,
    "D713": 550,
    "D510": 43,
    "D511": 3510,
    "D513": 548,
    "D100": 180,
    "D104": 125,
    "D126": 120,
    "D340": 350,
    "D341": 348,
    "D342": 352,
    "D343": 345,
    "D330": 340,
    "D331": 342,
    "D20": 20,
    "D21": 3,
    "D22": 50,
    "D23": 50,
    "D1820": 125000,
    "D1821": 125000,
    "D1810": 10000,
    "D1811": 10000,
    "D1812": 8500,
    "D1813": 8500,
    "D1814": (-1500) & 0xFFFFFFFF,  # 과부족수량 (각 행이 Dword 1개 = 2레지스터)
    "D1815": (-1500) & 0xFFFFFFFF,
    "D1816": 5000,
    "D1817": 5000,
    "D1818": 0,
    "D1819": 0,
    "D1912": 3200,
    "D1913": 3200,
    "D1914": 480,
}


def parse_iolist():
    """iolist.csv 파싱. 반환: (coil_rows, reg_rows) - 각 (Address, DataType, Length, Description)."""
    coil_rows = []
    reg_rows = []
    with open(IOLIST_PATH, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            addr = (row.get("Address") or "").strip()
            if not addr:
                continue
            length = (row.get("Length") or "0").strip()
            try:
                length = int(length)
            except ValueError:
                length = 0
            dt = (row.get("DataType") or "").strip().lower()
            desc = (row.get("Parameter(Korean)") or row.get("Description") or "").strip()
            if dt == "boolean":
                coil_rows.append((addr, dt, length, desc))
            elif dt in ("word", "dword", "string"):
                reg_rows.append((addr, dt, length, desc))
    return coil_rows, reg_rows


def build_coil_values(coil_rows):
    """Boolean 행에서 Coil 기본값 생성. 운전준비/Green=1, 비상·알람·에러=0."""
    values = []
    for _addr, _dt, _len, desc in coil_rows:
        if "운전준비" in desc or "준비" in desc or "Green" in desc or "녹" in desc:
            values.append(1)
        elif "비상" in desc or "알람" in desc or "에러" in desc or "오류" in desc or "이상" in desc:
            values.append(0)
        else:
            values.append(0)
    return values


def build_register_values(reg_rows):
    """Word/Dword/String 행에서 Holding Register 기본값 생성. 행당 Word=1, Dword=2, String=1 레지스터."""
    values = []
    # 금형 이름: 현재 8워드 = "hello", 다음 8워드 = "hello1" (각 2바이트씩 빅엔디안)
    current_name = (list("hello".encode("ascii")) + [0] * 11)[:16]
    next_name = (list("hello1".encode("ascii")) + [0] * 10)[:16]
    string_row_index = 0
    for addr, dt, length, _ in reg_rows:
        if dt == "word":
            values.append(REG_DEFAULTS.get(addr, 0) & 0xFFFF)
        elif dt == "dword":
            v = REG_DEFAULTS.get(addr, 0) & 0xFFFFFFFF
            values.append((v >> 16) & 0xFFFF)
            values.append(v & 0xFFFF)
        elif dt == "string":
            # 행당 1워드(2바이트). 첫 8행=현재 금형, 다음 8행=다음 금형
            chars = current_name if string_row_index < 8 else next_name
            off = (string_row_index % 8) * 2
            b1 = chars[off] if off < 16 else 0
            b2 = chars[off + 1] if off + 1 < 16 else 0
            values.append((b1 << 8) | b2)
            string_row_index += 1
    return values


def main():
    coil_rows, reg_rows = parse_iolist()
    coil_vals = build_coil_values(coil_rows)
    reg_vals = build_register_values(reg_rows)

    try:
        from pymodbus.datastore import (
            ModbusSequentialDataBlock,
            ModbusServerContext,
            ModbusDeviceContext,
        )
        from pymodbus.server import StartTcpServer
        try:
            from pymodbus.pdu.device import ModbusDeviceIdentification
        except ImportError:
            from pymodbus.device import ModbusDeviceIdentification
        _use_devices = True  # pymodbus 3.12+
    except ImportError:
        try:
            from pymodbus.datastore import ModbusSlaveContext as ModbusDeviceContext
            from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
            from pymodbus.server import StartTcpServer
            from pymodbus.device import ModbusDeviceIdentification
            _use_devices = False  # pymodbus 3.6
        except ImportError:
            print("pymodbus가 필요합니다: pip install pymodbus")
            return

    # pymodbus 컨텍스트가 클라이언트 주소 0을 1로 변환하므로, 블록 시작 주소를 1로 해야 0번이 values[0]에 매핑됨
    di = ModbusSequentialDataBlock(1, [0] * max(1, len(coil_vals)))
    co = ModbusSequentialDataBlock(1, coil_vals)
    hr = ModbusSequentialDataBlock(1, reg_vals)
    ir = ModbusSequentialDataBlock(1, [0] * max(1, len(reg_vals)))

    store = ModbusDeviceContext(di=di, co=co, hr=hr, ir=ir)
    context = ModbusServerContext(devices=store, single=True) if _use_devices else ModbusServerContext(slaves=store, single=True)

    identity = ModbusDeviceIdentification()
    identity.VendorName = "PLC Monitor"
    identity.ProductName = "Modbus Slave (iolist)"

    print(f"Coils: 0~{len(coil_vals)-1} ({len(coil_vals)}개)")
    print(f"Holding Registers: 0~{len(reg_vals)-1} ({len(reg_vals)}개)")
    print(f"Modbus TCP 슬레이브 {HOST}:{PORT} 에서 대기 중... (Ctrl+C 종료)")
    try:
        StartTcpServer(context=context, identity=identity, address=(HOST, PORT))
    except (OSError, RuntimeError) as e:
        err_msg = str(e).lower()
        if getattr(e, "errno", None) == 98 or "address already in use" in err_msg or "could not start listen" in err_msg:
            print(f"\n오류: 포트 {PORT}이(가) 이미 사용 중입니다.")
            print("  기존 슬레이브를 종료한 뒤 다시 실행하거나, 다른 포트를 사용하세요:")
            print(f"    PORT={PORT + 1} ./run-modbus-slave.sh")
            print(f"    또는  ./run-modbus-slave.sh {PORT + 1}")
            print("  사용 중인 프로세스 확인: ss -ltnp | grep " + str(PORT))
        else:
            raise


if __name__ == "__main__":
    main()
