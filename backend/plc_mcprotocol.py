#!/usr/bin/env python3
"""
pymcprotocol(Type3E) 읽기 + 요청/응답 HEX 덤프
- 라이브러리 재해석 레이어 제거
- Boolean, Word, Dword, String 처리
- 패킷 캡처 가능
"""
import argparse
import os
import sys

try:
    import pymcprotocol
except ImportError:
    print("오류: pymcprotocol 필요. pip install pymcprotocol", file=sys.stderr)
    sys.exit(1)

PLC_HOST = "192.168.0.5"
PLC_PORT = 5002
DEBUG_ERRORS = (os.environ.get("MC_POLL_DEBUG_ERRORS", "").strip().lower() in ("1", "true", "yes", "on"))
# 블록 읽기 상한(PLC/프레임 제한 완화). 구간이 크면 여러 번 나눠 읽고 이어 붙인다.
_MAX_BIT_READSIZE = max(1, int(os.environ.get("MC_MAX_BIT_READSIZE", "2048") or "2048"))
_MAX_WORD_READSIZE = max(1, int(os.environ.get("MC_MAX_WORD_READSIZE", "960") or "960"))
# dword 랜덤읽기: 한 프레임에 넣을 최대 개수(과대 시 청크)
_MAX_DWORD_RANDOMREAD = max(1, int(os.environ.get("MC_MAX_DWORD_RANDOMREAD", "64") or "64"))

def parse_address(s: str) -> int:
    """주소 문자열 해석. 0x 접두사 있으면 16진수, 없으면 10진수."""
    s = (s or "").strip()
    if not s:
        raise ValueError("주소가 비어 있음")
    return int(s, 16) if s.lower().startswith("0x") else int(s, 10)

def device_to_headdevice(device: str, address: int) -> str:
    """(device, address) → pymcprotocol 헤드 디바이스 문자열."""
    d = device.upper()
    # Mitsubishi Y는 주소를 16진 문자열로 넘겨야 한다. (예: 0x14C -> Y14C)
    if d == "Y":
        return f"{d}{address:X}"
    return f"{d}{address}"


def _merge_half_open_intervals(items: list[tuple[int, int, tuple]]) -> list[tuple[int, int, list]]:
    """
    items: (start, end_exclusive, payload) 구간들을 정렬 후 겹치거나 맞닿는 구간끼리 병합.
    반환: (merged_start, merged_end, payloads_in_order)
    """
    if not items:
        return []
    items = sorted(items, key=lambda x: x[0])
    out = []
    cur_s, cur_e, payloads = items[0][0], items[0][1], [items[0][2]]
    for s, e, p in items[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
            payloads.append(p)
        else:
            out.append((cur_s, cur_e, payloads))
            cur_s, cur_e, payloads = s, e, [p]
    out.append((cur_s, cur_e, payloads))
    return out


def _read_bits_span(plc, device: str, bs: int, be: int) -> list:
    """[bs, be) 비트 구간을 상한 단위로 나눠 읽고 한 리스트로 이어 붙인다."""
    vals: list = []
    pos = bs
    while pos < be:
        chunk_end = min(be, pos + _MAX_BIT_READSIZE)
        hd = device_to_headdevice(device, pos)
        vals.extend(plc.batchread_bitunits(hd, readsize=chunk_end - pos))
        pos = chunk_end
    return vals


def _read_words_span(plc, device: str, bs: int, be: int) -> list:
    """[bs, be) 워드 구간을 상한 단위로 나눠 읽고 한 리스트로 이어 붙인다."""
    vals: list = []
    pos = bs
    while pos < be:
        chunk_end = min(be, pos + _MAX_WORD_READSIZE)
        hd = device_to_headdevice(device, pos)
        vals.extend(plc.batchread_wordunits(hd, readsize=chunk_end - pos))
        pos = chunk_end
    return vals


def _words_for_string(length: int) -> int:
    return max(1, (int(length) + 1) // 2)


def read_mc_variables(host: str, port: int, entries: list) -> dict:
    """
    host:port에 pymcprotocol(Type3E) TCP로 읽기. 반환: {변수명: 값}. 실패 시 '-'.

    테스트 시에는 가짜 PLC(mc_fake 서버)에 붙고, 현장에서는 동일 코드로 실제 PLC에 붙는다.
    폴링 대상 목록은 mc_fake_values.json(매핑)에서 오며, 읽기 경로는 항상 pymcprotocol이다.

    같은 디바이스·같은 타입에서 주소가 이어지면 batchread_*로 묶어 MC 왕복 횟수를 줄인다.
    dword는 randomread로 가능한 한 한 프레임에 묶는다.
    """
    result = {name: "-" for name, *_ in entries}
    if not entries:
        return result

    plc = pymcprotocol.Type3E()
    connected = False

    def _connect() -> bool:
        nonlocal connected
        if connected:
            return True
        try:
            plc.connect(host, port)
            connected = True
            return True
        except Exception as e:
            if DEBUG_ERRORS:
                print(f"[MC] connect 실패 {host}:{port}: {e}", flush=True)
            connected = False
            return False

    def _reconnect() -> bool:
        nonlocal connected
        try:
            plc.close()
        except Exception:
            pass
        connected = False
        return _connect()

    def _run_read(label: str, op):
        """한 번 시도, 실패 시 재연결 후 1회 재시도. 실패 시 예외 전파."""
        tried = False
        while True:
            try:
                return op()
            except Exception as e:
                if tried:
                    if DEBUG_ERRORS:
                        print(f"[MC] read 실패 {label}: {e}", flush=True)
                    raise
                tried = True
                if not _reconnect():
                    if DEBUG_ERRORS:
                        print(f"[MC] reconnect 실패 후 read 중단: {label}", flush=True)
                    raise
                continue

    if not _connect():
        return result

    grouped: dict[str, list] = {}
    for row in entries:
        name, _device, _addr, data_type, _length = row
        t = (data_type or "").strip().lower()
        if t not in grouped:
            grouped[t] = []
        grouped[t].append(row)

    try:
        # --- boolean: 디바이스별 연속 비트 구간 병합 ---
        bool_rows = grouped.get("boolean", [])
        by_dev: dict[str, list] = {}
        for name, device, address, data_type, length in bool_rows:
            ln = max(1, int(length or 1))
            by_dev.setdefault(device, []).append((name, int(address), ln))

        for device, rows in by_dev.items():
            intervals = []
            for name, addr, ln in rows:
                intervals.append((addr, addr + ln, (name, addr, ln)))
            for bs, be, payloads in _merge_half_open_intervals(intervals):
                try:
                    vals = _run_read(
                        f"boolean {device}[{bs},{be})",
                        lambda: _read_bits_span(plc, device, bs, be),
                    )
                except Exception:
                    for name, addr, ln in payloads:
                        result[name] = "-"
                    continue
                for name, addr, ln in payloads:
                    off = addr - bs
                    if off + ln <= len(vals) and off >= 0:
                        result[name] = vals[off] if ln == 1 else vals[off]
                    else:
                        result[name] = "-"

        # --- word: 디바이스별 연속 워드 구간 병합 ---
        word_rows = grouped.get("word", [])
        by_dev_w: dict[str, list] = {}
        for name, device, address, data_type, length in word_rows:
            ln = max(1, int(length or 1))
            by_dev_w.setdefault(device, []).append((name, int(address), ln))

        for device, rows in by_dev_w.items():
            intervals = []
            for name, addr, ln in rows:
                intervals.append((addr, addr + ln, (name, addr, ln)))
            for bs, be, payloads in _merge_half_open_intervals(intervals):
                try:
                    vals = _run_read(
                        f"word {device}[{bs},{be})",
                        lambda bs=bs, be=be, dev=device: _read_words_span(plc, dev, bs, be),
                    )
                except Exception:
                    for name, addr, ln in payloads:
                        result[name] = "-"
                    continue
                for name, addr, ln in payloads:
                    off = addr - bs
                    if off + ln <= len(vals) and off >= 0:
                        result[name] = vals[off] if ln == 1 else vals[off : off + ln][0]
                    else:
                        result[name] = "-"

        # --- string: 워드 구간 병합 후 디코드 ---
        str_rows = grouped.get("string", [])
        by_dev_s: dict[str, list] = {}
        for name, device, address, data_type, length in str_rows:
            slen = max(1, int(length or 1))
            nw = _words_for_string(slen)
            by_dev_s.setdefault(device, []).append((name, int(address), slen, nw))

        for device, rows in by_dev_s.items():
            intervals = []
            for name, addr, slen, nw in rows:
                intervals.append((addr, addr + nw, (name, addr, slen, nw)))
            for bs, be, payloads in _merge_half_open_intervals(intervals):
                try:
                    vals = _run_read(
                        f"string {device}[{bs},{be})",
                        lambda bs=bs, be=be, dev=device: _read_words_span(plc, dev, bs, be),
                    )
                except Exception:
                    for name, addr, slen, nw in payloads:
                        result[name] = "-"
                    continue
                for name, addr, slen, nw in payloads:
                    off = addr - bs
                    if off + nw <= len(vals) and off >= 0:
                        chunk = vals[off : off + nw]
                        b = b"".join(bytes([w & 0xFF, (w >> 8) & 0xFF]) for w in chunk)
                        s = b[:slen].decode("ascii", errors="replace").rstrip("\x00")
                        result[name] = s or "-"
                    else:
                        result[name] = "-"

        # --- dword: randomread로 한 프레임에 묶기(청크) ---
        dword_rows = grouped.get("dword", [])
        if dword_rows:
            heads_order: list[str] = []
            order_names: list[str] = []
            for name, device, address, data_type, length in dword_rows:
                heads_order.append(device_to_headdevice(device, int(address)))
                order_names.append(name)
            for i in range(0, len(heads_order), _MAX_DWORD_RANDOMREAD):
                chunk_h = heads_order[i : i + _MAX_DWORD_RANDOMREAD]
                chunk_n = order_names[i : i + _MAX_DWORD_RANDOMREAD]
                try:
                    _wv, dword_vals = _run_read(
                        f"dword randomread x{len(chunk_h)}",
                        lambda h=chunk_h: plc.randomread(word_devices=[], dword_devices=h),
                    )
                except Exception:
                    for n in chunk_n:
                        result[n] = "-"
                    continue
                if len(dword_vals) != len(chunk_n):
                    for n in chunk_n:
                        result[n] = "-"
                    continue
                for n, dv in zip(chunk_n, dword_vals):
                    result[n] = dv

        # --- 기타 타입: word와 동일하게 워드 블록 병합 ---
        other_rows = []
        for t, rows in grouped.items():
            if t in ("boolean", "word", "dword", "string"):
                continue
            other_rows.extend(rows)

        by_dev_o: dict[str, list] = {}
        for name, device, address, data_type, length in other_rows:
            ln = max(1, int(length or 1))
            by_dev_o.setdefault(device, []).append((name, int(address), ln))

        for device, rows in by_dev_o.items():
            intervals = []
            for name, addr, ln in rows:
                intervals.append((addr, addr + ln, (name, addr, ln)))
            for bs, be, payloads in _merge_half_open_intervals(intervals):
                try:
                    vals = _run_read(
                        f"fallback-word {device}[{bs},{be})",
                        lambda bs=bs, be=be, dev=device: _read_words_span(plc, dev, bs, be),
                    )
                except Exception:
                    for name, addr, ln in payloads:
                        result[name] = "-"
                    continue
                for name, addr, ln in payloads:
                    off = addr - bs
                    if off + ln <= len(vals) and off >= 0:
                        result[name] = vals[off] if ln == 1 else vals[off : off + ln][0]
                    else:
                        result[name] = "-"

    finally:
        try:
            plc.close()
        except Exception:
            pass

    return result


def hex_dump(data: bytes, bytes_per_line: int = 16) -> str:
    """간단 HEX 덤프"""
    lines = []
    for i in range(0, len(data), bytes_per_line):
        chunk = data[i : i + bytes_per_line]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        lines.append(f"{i:04x}   {hex_part}")
    return "\n".join(lines) if lines else ""

# socket 패치로 패킷 캡처
class PacketCaptureSocket:
    _real_socket_class = None

    def __init__(self, family, type_, proto=-1):
        cls = PacketCaptureSocket._real_socket_class or __import__("socket").socket
        self._sock = cls(family, type_, proto)
        self._last_sent = b""
        self._last_received = b""

    def __getattr__(self, name):
        return getattr(self._sock, name)

    def sendall(self, data, *args, **kwargs):
        self._last_sent = data
        return self._sock.sendall(data, *args, **kwargs)

    def send(self, data, *args, **kwargs):
        self._last_sent = data if isinstance(data, bytes) else self._last_sent + (data or b"")
        return self._sock.send(data, *args, **kwargs)

    def recv(self, bufsize, *args, **kwargs):
        data = self._sock.recv(bufsize, *args, **kwargs)
        if data:
            self._last_received += data
        return data

def main():
    parser = argparse.ArgumentParser(description="pymcprotocol Type3E 읽기 + HEX 덤프")
    parser.add_argument("--device", required=True, choices=["Y", "M", "D"], help="디바이스 (Y, M, D)")
    parser.add_argument("--address", type=parse_address, required=True, help="시작 주소")
    parser.add_argument("--type", dest="data_type", required=True,
                        choices=["boolean", "word", "dword", "string"], help="데이터 타입")
    parser.add_argument("--length", type=int, required=True, help="읽을 개수 / 문자열 길이")
    parser.add_argument("--host", default=PLC_HOST, help="PLC IP")
    parser.add_argument("--port", type=int, default=PLC_PORT, help="PLC 포트")
    args = parser.parse_args()

    headdevice = device_to_headdevice(args.device, args.address)

    # 패킷 캡처 소켓 패치
    import socket
    real_socket = socket.socket
    PacketCaptureSocket._real_socket_class = real_socket
    capture_sock = None
    def capturing_socket(family, type_, proto=-1):
        nonlocal capture_sock
        capture_sock = PacketCaptureSocket(family, type_, proto)
        return capture_sock
    socket.socket = capturing_socket

    plc = pymcprotocol.Type3E()
    try:
        plc.connect(args.host, args.port)
    except Exception as e:
        print(f"PLC 연결 실패: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        socket.socket = real_socket

    vals = None
    try:
        t = args.data_type.lower()
        if t == "boolean":
            vals = plc.batchread_bitunits(headdevice, readsize=args.length)
        elif t == "word":
            vals = plc.batchread_wordunits(headdevice, readsize=args.length)
        elif t == "dword":
            _, dword_vals = plc.randomread(word_devices=[], dword_devices=[headdevice])
            vals = dword_vals
        elif t == "string":
            words = plc.batchread_wordunits(headdevice, readsize=(args.length + 1) // 2)
            b = b"".join(bytes([w & 0xFF, (w >> 8) & 0xFF]) for w in words)
            vals = [b[:args.length].decode("ascii", errors="replace").rstrip("\x00")]
    except Exception as e:
        print(f"읽기 실패: {e}", file=sys.stderr)
        vals = None
    finally:
        try:
            plc.close()
        except Exception:
            pass

    # 패킷 출력
    if capture_sock:
        print(f"[요청 패킷] ({len(capture_sock._last_sent)} bytes)")
        print(hex_dump(capture_sock._last_sent))
        print(f"[응답 패킷] ({len(capture_sock._last_received)} bytes)")
        print(hex_dump(capture_sock._last_received))

    print(f"{args.device}{args.address} ({args.data_type}) = {vals}")

if __name__ == "__main__":
    main()