#!/usr/bin/env python3
"""
서버를 띄운 뒤 기본 브라우저로 http://localhost:6005 를 엽니다.
.exe/데스크톱 더블클릭으로 실행하는 진입점입니다.
"""
import os
import sys
import threading
import time
import urllib.request

# backend 폴더를 path에 넣어서 app import 가능하게
_BACKEND = os.path.dirname(os.path.abspath(__file__))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

PORT = 6005
URL = f"http://localhost:{PORT}"


def _server_ready():
    try:
        urllib.request.urlopen(URL, timeout=1)
        return True
    except Exception:
        return False


def open_browser():
    # start.sh에서 브라우저를 열기로 했으면 여기서는 생략
    if os.environ.get("OPEN_BROWSER_FROM_SHELL"):
        return
    import subprocess
    # 서버가 실제로 응답할 때까지 대기
    for _ in range(40):
        time.sleep(0.25)
        if _server_ready():
            break
    time.sleep(0.5)
    env = os.environ.copy()
    if not env.get("DISPLAY") and os.path.exists("/tmp/.X11-unix"):
        env["DISPLAY"] = ":0"
    # xdg-open 먼저 (데스크톱 더블클릭 환경에서 더 잘 동작). Popen으로 기다리지 않고 열기
    for exe in ["xdg-open", "gio open"]:
        try:
            subprocess.Popen(
                [exe, URL],
                env=env,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (FileNotFoundError, Exception):
            continue
    try:
        import webbrowser
        webbrowser.open(URL)
    except Exception:
        pass


def main():
    from app import app
    if not os.environ.get("OPEN_BROWSER_FROM_SHELL"):
        threading.Thread(target=open_browser, daemon=True).start()
    print(f"PLC 모니터 시작 중... 브라우저에서 {URL} 이 열립니다.")
    print(f"  (자동으로 안 열리면 브라우저에서 위 주소를 입력하세요.)")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
