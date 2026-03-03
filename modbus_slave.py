#!/usr/bin/env python3
"""
Modbus TCP 슬레이브(서버). iolist.csv 주소 순서대로 Coils(경고/알람) + Holding Registers(데이터) 매핑.
기본값: Boolean 0/1, Word/Dword 유의미 더미, String "hello" 2바이트씩 분할.
"""
import csv
import os
import random
import sys
import threading
import time
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


def _dword_addr_number(addr):
    """D1820 -> 1820. 앱과 동일하게 짝수 D=하위워드만 2레지스터 사용."""
    if not addr or len(addr) < 2:
        return None
    try:
        return int(addr[1:].strip(), 10)
    except ValueError:
        return None


def build_register_values(reg_rows):
    """Word/Dword/String 행에서 Holding Register 생성. 앱(io_variables)과 동일하게 Dword는 논리당 2레지스터만."""
    values = []
    current_name = (list("hello".encode("ascii")) + [0] * 11)[:16]
    next_name = (list("hello1".encode("ascii")) + [0] * 10)[:16]
    string_row_index = 0
    for addr, dt, length, _ in reg_rows:
        if dt == "word":
            values.append(REG_DEFAULTS.get(addr, 0) & 0xFFFF)
        elif dt == "dword":
            num = _dword_addr_number(addr)
            if num is not None and (num & 1) == 1:
                continue  # 상위 워드 행(D1821 등) 스킵 → 논리당 2레지스터만 (앱과 동일)
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


# 시뮬레이션: 경고등 자주 랜덤 점등. 타발수만 200ms마다 +1, 나머지 카운터/기동시간은 1초마다.
COIL_FLASH_INTERVAL = 0.25
COIL_FLASH_DURATION = 0.15
STROKE_PULSE_INTERVAL = 0.2   # 타발수(totalCounter)만 200ms마다 +1
REG_PULSE_INTERVAL = 1.0      # 그 외 카운터/기동시간 +1 주기 1초
REG_PULSE_CAP = 150

# 타발수: 인덱스 35,36 (totalCounter_D1820). 나머지는 REG_PULSE_SPECS로 1초마다.
STROKE_PULSE_SPEC = (35, 2)
REG_PULSE_SPECS = [
    (37, 2),   # productionCounter_D1810
    (39, 2),   # currentProduction_D1812
    (41, 2),   # defficiencyQuantity_D1814
    (43, 2),   # presetCounter_D1816
    (45, 2),   # production_D1818
    (47, 2),   # todayStrokeCount_D1912
    (49, 1),   # todayRunningTime_D1914 (기동시간)
]


def _simulation_loop(co_block, hr_block, coil_base, reg_base_snapshot, stop_event):
    """코일: 랜덤 점등 후 복귀. 타발수만 200ms마다 +1, 나머지 레지스터는 1초마다 +1."""
    coil_vals = co_block.values
    reg_vals = hr_block.values
    last_coil_flash = 0.0
    last_stroke_pulse = 0.0
    last_reg_pulse = 0.0
    flashed_coil_idx = None
    flashed_coil_restore_at = 0.0
    n_coils = len(coil_vals)
    while not stop_event.is_set():
        now = time.monotonic()
        if flashed_coil_idx is not None and now >= flashed_coil_restore_at:
            coil_vals[flashed_coil_idx] = coil_base[flashed_coil_idx]
            flashed_coil_idx = None
        if flashed_coil_idx is None and n_coils and (now - last_coil_flash) >= COIL_FLASH_INTERVAL:
            last_coil_flash = now
            idx = random.randint(0, n_coils - 1)
            coil_vals[idx] = 1
            flashed_coil_idx = idx
            flashed_coil_restore_at = now + COIL_FLASH_DURATION
        # 타발수(totalCounter)만 200ms마다 +1 (블록 주소 = 1부터이므로 start+1)
        if (now - last_stroke_pulse) >= STROKE_PULSE_INTERVAL:
            last_stroke_pulse = now
            start, count = STROKE_PULSE_SPEC
            if start + count <= len(reg_vals):
                base_hi = reg_base_snapshot[start]
                base_lo = reg_base_snapshot[start + 1]
                v = (reg_vals[start] << 16) | (reg_vals[start + 1] & 0xFFFF)
                base_v = (base_hi << 16) | (base_lo & 0xFFFF)
                v = (v + 1) & 0xFFFFFFFF
                if v >= base_v + REG_PULSE_CAP:
                    v = base_v
                hi, lo = (v >> 16) & 0xFFFF, v & 0xFFFF
                reg_vals[start] = hi
                reg_vals[start + 1] = lo
                # pymodbus 블록이 주소 1부터이므로 setValues(start+1, ...)로도 반영
                try:
                    hr_block.setValues(start + 1, [hi, lo])
                except Exception:
                    pass
        # 그 외 카운터/기동시간은 1초마다 +1
        if (now - last_reg_pulse) >= REG_PULSE_INTERVAL:
            last_reg_pulse = now
            for start, count in REG_PULSE_SPECS:
                if start + count > len(reg_vals):
                    continue
                base_hi = reg_base_snapshot[start]
                base_lo = reg_base_snapshot[start + 1] if count == 2 else 0
                if count == 2:
                    v = (reg_vals[start] << 16) | (reg_vals[start + 1] & 0xFFFF)
                    base_v = (base_hi << 16) | (base_lo & 0xFFFF)
                    v = (v + 1) & 0xFFFFFFFF
                    if v >= base_v + REG_PULSE_CAP:
                        v = base_v
                    reg_vals[start] = (v >> 16) & 0xFFFF
                    reg_vals[start + 1] = v & 0xFFFF
                else:
                    v = (reg_vals[start] + 1) & 0xFFFF
                    if v >= (base_hi + REG_PULSE_CAP) & 0xFFFF:
                        v = base_hi
                    reg_vals[start] = v
        time.sleep(0.02)  # 20ms 주기로 체크해 200ms 타발수 타이밍 정확히


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

    # 시뮬레이션: 블록의 .values를 직접 수정 (블록이 list 복사본을 갖기 때문)
    coil_base = list(co.values)
    reg_base_snapshot = list(hr.values)
    sim_stop = threading.Event()
    sim_thread = threading.Thread(
        target=_simulation_loop,
        args=(co, hr, coil_base, reg_base_snapshot, sim_stop),
        daemon=True,
    )
    sim_thread.start()

    store = ModbusDeviceContext(di=di, co=co, hr=hr, ir=ir)
    context = ModbusServerContext(devices=store, single=True) if _use_devices else ModbusServerContext(slaves=store, single=True)

    identity = ModbusDeviceIdentification()
    identity.VendorName = "PLC Monitor"
    identity.ProductName = "Modbus Slave (iolist)"

    print(f"Coils: 0~{len(coil_vals)-1} ({len(coil_vals)}개)")
    print(f"Holding Registers: 0~{len(reg_vals)-1} ({len(reg_vals)}개)")
    print("시뮬레이션: 경고등 랜덤 점등, 타발/카운터 +1 후 복귀")
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
