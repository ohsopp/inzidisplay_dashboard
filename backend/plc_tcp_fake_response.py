#!/usr/bin/env python3
"""
plc_tcp_send.py / plc_mcprotocol.py 가 보내는 3E 읽기 요청에 대해
mc_fake_values.json에 정의된 값으로 응답 패킷을 돌려주는 TCP 서버.

JSON에서 키(예: M300, D140)와 value를 수정하면 요청 시마다 파일을 다시 읽어
해당 값으로 응답합니다. 대시보드 폴링 시 JSON 값이 그대로 표시됩니다.

사용법:
  1) mc_fake_values.json에 디 바이스+주소 키와 value 추가/수정 (예: "M300": {"dataType":"Boolean","length":1,"value":1})
  2) 이 서버 실행: python3 backend/plc_tcp_fake_response.py
  3) 클라이언트는 PLC 대신 이 PC IP + 5002 로 연결
"""
import json
import socket
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MC_FAKE_VALUES_PATH = SCRIPT_DIR / "mc_fake_values.json"

# 3E 디바이스 코드 (plc_tcp_send와 동일)
DEVICE_CODE_TO_LETTER = {0xA8: "D", 0x9D: "Y", 0x90: "M"}

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5002
RESPONSE_HEADER_LEN = 9
END_CODE_LEN = 2
END_CODE_OK = bytes([0x00, 0x00])


def word_to_le_bytes(value: int) -> bytes:
    """16비트 값을 2바이트 리틀엔디안. pymcprotocol이 LE로 해석함."""
    v = value & 0xFFFF
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def dword_to_read_data_le(value: int) -> bytes:
    """32비트 값을 4바이트 리틀엔디안. pymcprotocol randomread/batchread_wordunits 해석에 맞춤."""
    value = value & 0xFFFFFFFF
    return bytes([
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF,
    ])


def string_to_read_data(s: str, length: int) -> bytes:
    """문자열을 length 바이트로. 워드 단위로 보냄(현재 pymcprotocol string 해석과 맞음)."""
    b = s.encode("ascii", errors="replace")[:length]
    b = b + b"\x00" * (length - len(b))
    # 워드 단위로 빅엔디안: 각 2바이트는 [high, low]
    out = []
    for i in range(0, len(b), 2):
        if i + 1 < len(b):
            out.append(bytes([b[i], b[i + 1]]))
        else:
            out.append(bytes([b[i], 0]))
    return b"".join(out)


def build_3e_response(read_data: bytes) -> bytes:
    """3E 응답: 헤더 9바이트 + End code 2바이트 + Read data."""
    payload_len = END_CODE_LEN + len(read_data)
    subheader = b"\xD0\x00"  # 응답 서브헤더
    header = (
        subheader
        + b"\x00\xFF"
        + (0x03FF).to_bytes(2, "little")
        + b"\x00"
        + payload_len.to_bytes(2, "little")
    )
    return header + END_CODE_OK + read_data


def load_mc_fake_values() -> dict:
    """mc_fake_values.json 로드. 키로 '_' 시작하는 항목 제외."""
    if not MC_FAKE_VALUES_PATH.exists():
        return {}
    try:
        with open(MC_FAKE_VALUES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, dict) and not k.startswith("_")}
    except (OSError, json.JSONDecodeError):
        return {}


def build_read_data_from_entry(entry: dict) -> bytes:
    """entry(dataType, length, value) → pymcprotocol이 기대하는 read_data 바이트."""
    t = (entry.get("dataType") or "").strip().lower()
    length = int(entry.get("length") or 1)
    val = entry.get("value")
    if t == "boolean":
        bit = 1 if val else 0
        return bytes([0x10 if bit else 0x00, 0x00])
    if t == "word":
        return word_to_le_bytes(int(val) if val is not None else 0)
    if t == "dword":
        return dword_to_read_data_le(int(val) if val is not None else 0)
    if t == "string":
        s = str(val) if val is not None else ""
        return string_to_read_data(s, length)
    return word_to_le_bytes(int(val) if val is not None else 0)


# 요청 구분: 바디 = timer(2) + cmd(2) + subcmd(2) + ...
# 0401: + addr3(3) + device(1) + points(2)  → 12바이트
# 0403: + word_size(1) + dword_size(1) + devicedata 4바이트씩
def _addr_to_config_key(letter: str, addr: int, config: dict) -> str | None:
    """(device_letter, 3E주소) → config 키. Y/M은 0x01XX(상위바이트 1, 하위 2바이트=번호) 인코딩 사용."""
    # 기본 후보: 10진/16진 표기 모두 허용 (예: Y332, Y14C)
    direct_candidates = (
        f"{letter}{addr}",
        f"{letter}{addr:X}",
    )
    for c in direct_candidates:
        if c in config:
            return c

    # Y/M: 0x0107 → Y107, 0x0109 → Y109 (상위 1바이트=1, 하위=십진 번호처럼 07→7, 09→9 → 1*100+7=107)
    if letter in ("Y", "M") and (addr & 0xFF00) == 0x0100:
        normalized = (addr >> 8) * 100 + (addr & 0xFF)
        for c in (f"{letter}{normalized}", f"{letter}{normalized:X}"):
            if c in config:
                return c
    if letter in ("Y", "M") and addr >= 0x100:
        legacy = addr - 0x100
        for c in (f"{letter}{legacy}", f"{letter}{legacy:X}"):
            if c in config:
                return c
    return None


def _parse_config_addr(key: str) -> tuple[str, int] | None:
    if not key or len(key) < 2:
        return None
    letter = key[0].upper()
    suffix = key[1:].strip().upper()
    if not suffix:
        return None
    try:
        if letter == "Y" or any(ch in "ABCDEF" for ch in suffix):
            return (letter, int(suffix, 16))
        return (letter, int(suffix, 10))
    except ValueError:
        return None


def _string_word_at(letter: str, addr: int, config: dict) -> bytes:
    """
    D 문자열을 워드 단위로 읽을 때, 문자열 시작 주소로부터 오프셋 워드를 반환.
    예) D1560 length=16 인 경우 D1560..D1567 읽기에서 각 주소에 맞는 2바이트를 돌려준다.
    """
    best_base = None
    best_entry = None
    best_nonempty_base = None
    best_nonempty_entry = None
    for key, entry in config.items():
        if not isinstance(entry, dict):
            continue
        if (entry.get("dataType") or "").strip().lower() != "string":
            continue
        parsed = _parse_config_addr(key)
        if not parsed:
            continue
        dev, base = parsed
        if dev != letter:
            continue
        slen = max(1, int(entry.get("length") or 1))
        words = (slen + 1) // 2
        if base <= addr < (base + words):
            value = entry.get("value")
            has_value = bool(str(value)) if value is not None else False
            if has_value:
                # 연속 문자열 슬롯(D1560~D1567)에 빈 엔트리가 있을 때,
                # 실제 문자열이 들어있는 시작 주소(보통 더 낮은 주소)를 우선 사용한다.
                if best_nonempty_base is None or base < best_nonempty_base:
                    best_nonempty_base = base
                    best_nonempty_entry = entry
            if best_base is None or base > best_base:
                best_base = base
                best_entry = entry
    if best_nonempty_entry is not None and best_nonempty_base is not None:
        best_entry = best_nonempty_entry
        best_base = best_nonempty_base
    if best_entry is None or best_base is None:
        return word_to_le_bytes(0)
    raw = build_read_data_from_entry(best_entry)
    off = (addr - best_base) * 2
    if off + 2 <= len(raw):
        return raw[off : off + 2]
    return word_to_le_bytes(0)


def pack_mc_batch_bits_binary(bits: list[int]) -> bytes:
    """pymcprotocol Type3E batchread_bitunits(COMMTYPE_BINARY) 응답과 동일: 2비트/바이트(짝=nibble4, 홀=bit0)."""
    out = bytearray()
    for i in range(0, len(bits), 2):
        b = 0
        if bits[i]:
            b |= 1 << 4
        if i + 1 < len(bits) and bits[i + 1]:
            b |= 1 << 0
        out.append(b)
    return bytes(out)


def build_read_data_batch_0401(body: bytes, config: dict) -> bytes | None:
    """
    0x0401 배치 읽기: points(비트 또는 워드)만큼 read_data 길이를 채운다.
    (블록 읽기 최적화 전에는 요청 1점=응답 1점이었으나, 실제 PLC·pymcprotocol은 readsize 전체를 기대한다.)
    """
    if len(body) < 12:
        return None
    subcmd = body[4] | (body[5] << 8)
    start_addr = body[6] | (body[7] << 8) | (body[8] << 16)
    device = body[9]
    points = body[10] | (body[11] << 8)
    letter = DEVICE_CODE_TO_LETTER.get(device)
    if letter is None or points <= 0 or points > 65535:
        return None

    # 비트 배치: Q/L 0x0001, iQ-R 0x0003
    if subcmd in (0x0001, 0x0003):
        bits: list[int] = []
        for i in range(points):
            key = _addr_to_config_key(letter, start_addr + i, config)
            if key and key in config:
                val = config[key].get("value")
                bits.append(1 if val else 0)
            else:
                bits.append(0)
        return pack_mc_batch_bits_binary(bits)

    # 워드 배치: Q 0x0000, iQ-R 0x0002
    if subcmd in (0x0000, 0x0002):
        out = bytearray()
        for i in range(points):
            cur_addr = start_addr + i
            key = _addr_to_config_key(letter, cur_addr, config)
            if key and key in config:
                raw = build_read_data_from_entry(config[key])
                t = (config[key].get("dataType") or "").strip().lower()
                if t == "dword":
                    out.extend(raw[:2])
                elif t == "string":
                    out.extend(_string_word_at(letter, cur_addr, config))
                else:
                    out.extend(raw[:2] if len(raw) >= 2 else word_to_le_bytes(0))
            else:
                out.extend(_string_word_at(letter, cur_addr, config))
        return bytes(out)

    return None


def build_read_data_batch_0403(body: bytes, config: dict) -> bytes | None:
    """0x0403 랜덤 읽기: word 개×2바이트 + dword 개×4바이트 순서로 이어 붙인다."""
    if len(body) < 8:
        return None
    word_size = body[6]
    dword_size = body[7]
    need = 8 + (word_size + dword_size) * 4
    if len(body) < need:
        return None

    out = bytearray()
    offset = 8
    for _ in range(word_size):
        addr = body[offset] | (body[offset + 1] << 8) | (body[offset + 2] << 16)
        device = body[offset + 3]
        offset += 4
        letter = DEVICE_CODE_TO_LETTER.get(device)
        key = _addr_to_config_key(letter, addr, config) if letter else None
        if key and key in config:
            raw = build_read_data_from_entry(config[key])
            t = (config[key].get("dataType") or "").strip().lower()
            if t == "string" and letter:
                out.extend(_string_word_at(letter, addr, config))
            else:
                out.extend(raw[:2] if len(raw) >= 2 else word_to_le_bytes(0))
        else:
            if letter:
                out.extend(_string_word_at(letter, addr, config))
            else:
                out.extend(word_to_le_bytes(0))

    for _ in range(dword_size):
        addr = body[offset] | (body[offset + 1] << 8) | (body[offset + 2] << 16)
        device = body[offset + 3]
        offset += 4
        letter = DEVICE_CODE_TO_LETTER.get(device)
        key = _addr_to_config_key(letter, addr, config) if letter else None
        if key and key in config:
            raw = build_read_data_from_entry(config[key])
            out.extend(raw[:4] if len(raw) >= 4 else dword_to_read_data_le(0))
        else:
            out.extend(dword_to_read_data_le(0))

    return bytes(out)


def match_request(body: bytes, config: dict) -> str | None:
    """단일 키만 필요할 때(레거시 폴백). 배치 요청은 build_read_data_batch_* 사용."""
    if len(body) < 8:
        return None
    cmd = body[2] | (body[3] << 8)
    if cmd == 0x0401 and len(body) >= 12:
        addr = body[6] | (body[7] << 8) | (body[8] << 16)
        device = body[9]
        letter = DEVICE_CODE_TO_LETTER.get(device)
        if letter is not None:
            key = _addr_to_config_key(letter, addr, config)
            if key is not None:
                return key
    elif cmd == 0x0403 and len(body) >= 12:
        word_size, dword_size = body[6], body[7]
        total_devices = word_size + dword_size
        expected_len = 8 + total_devices * 4
        if total_devices > 0 and len(body) >= expected_len:
            # devicedata 4바이트: addr(3) + device(1)
            # 먼저 word 목록, 다음 dword 목록 순서.
            offset = 8
            for _ in range(total_devices):
                addr = body[offset] | (body[offset + 1] << 8) | (body[offset + 2] << 16)
                device = body[offset + 3]
                letter = DEVICE_CODE_TO_LETTER.get(device)
                if letter is not None:
                    key = _addr_to_config_key(letter, addr, config)
                    if key is not None:
                        return key
                offset += 4
    return None

def _recv_exact(conn: socket.socket, size: int) -> bytes | None:
    """요청 프레임 파싱용 고정 길이 수신. 연결 종료 시 None."""
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def handle_client(conn: socket.socket):
    """
    한 TCP 연결에서 여러 3E 요청을 연속 처리한다.
    실제 pymcprotocol은 연결을 유지한 채 연속 요청을 보내므로,
    요청 1건 처리 후 연결을 닫으면 일부 값이 0/'-'로 깨질 수 있다.
    """
    while True:
        header = _recv_exact(conn, RESPONSE_HEADER_LEN)
        if header is None:
            return
        if len(header) < RESPONSE_HEADER_LEN:
            return
        req_body_len = int.from_bytes(header[7:9], "little")
        if req_body_len <= 0:
            return
        body = _recv_exact(conn, req_body_len)
        if body is None:
            return
        if len(body) < 12:
            print(f"  → 바디 부족: {len(body)} bytes, hex={body.hex()}")
            continue

        config = load_mc_fake_values()
        cmd = body[2] | (body[3] << 8)
        read_data: bytes
        log_key: str | None = None

        if cmd == 0x0401:
            built = build_read_data_batch_0401(body, config)
            if built is not None:
                read_data = built
                log_key = f"0401_batch({len(read_data)}B)"
            else:
                log_key = match_request(body, config)
                if log_key and log_key in config:
                    read_data = build_read_data_from_entry(config[log_key])
                else:
                    read_data = word_to_le_bytes(0)
                    if log_key is None and len(body) >= 12:
                        addr = body[6] | (body[7] << 8) | (body[8] << 16)
                        device = body[9]
                        points = body[10] | (body[11] << 8)
                        print(f"  → 미매칭(0401): body(hex)={body.hex()}, addr=0x{addr:X} device=0x{device:X} points={points}")
        elif cmd == 0x0403:
            built = build_read_data_batch_0403(body, config)
            if built is not None:
                read_data = built
                log_key = f"0403_random({len(read_data)}B)"
            else:
                log_key = match_request(body, config)
                if log_key and log_key in config:
                    read_data = build_read_data_from_entry(config[log_key])
                else:
                    read_data = word_to_le_bytes(0)
                    if log_key is None:
                        print(f"  → 미매칭(0403): body(hex)={body.hex()}")
        else:
            log_key = match_request(body, config)
            if log_key and log_key in config:
                read_data = build_read_data_from_entry(config[log_key])
            else:
                read_data = word_to_le_bytes(0)
                if log_key is None:
                    print(f"  → 미매칭: cmd=0x{cmd:X} body(hex)={body.hex()}")

        resp = build_3e_response(read_data)
        conn.sendall(resp)
        if log_key:
            print(f"  → {log_key}, read_data={read_data.hex()}, 응답 {len(resp)} bytes")


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((LISTEN_HOST, LISTEN_PORT))
    except OSError as e:
        print(f"오류: 바인드 실패 {LISTEN_HOST}:{LISTEN_PORT} - {e}", file=sys.stderr)
        sys.exit(1)
    server.listen(5)
    config = load_mc_fake_values()
    keys = ", ".join(sorted(config.keys())) if config else "(없음)"
    print(f"3E 가짜 응답 서버 대기 중: {LISTEN_HOST}:{LISTEN_PORT}")
    print(f"  설정: {MC_FAKE_VALUES_PATH}")
    print(f"  항목: {keys}")
    while True:
        conn, addr = server.accept()
        print(f"연결: {addr}")
        try:
            handle_client(conn)
        except Exception as e:
            print(f"  오류: {e}", file=sys.stderr)
        finally:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()


if __name__ == "__main__":
    main()
