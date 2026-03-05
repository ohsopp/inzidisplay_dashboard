# PyInstaller spec: 단일 실행파일(Windows .exe / Linux binary)
# 빌드 전에 frontend 빌드 후 backend/frontend_dist 복사 필요. 절차는 scripts/BUILD_EXE.md 참고.

import os
import sys

# 스펙 파일 경로 기준 (PyInstaller가 SPEC 에 스펙 경로 넣음)
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO = os.path.dirname(_SPEC_DIR)   # backend 상위 = 프로젝트 루트
BACKEND = _SPEC_DIR
FRONTEND_DIST = os.path.join(BACKEND, 'frontend_dist')

# 데이터: 프론트 빌드물, 설정 JSON (exe 실행 시 같은 폴더에서 로드)
datas = []
if os.path.isdir(FRONTEND_DIST):
    datas.append((FRONTEND_DIST, 'frontend_dist'))
else:
    print('Warning: backend/frontend_dist 없음. 먼저 프론트 빌드 후 복사하세요.', file=sys.stderr)

# io_variables.json 은 _MEIPASS에 두고 로드
if os.path.isfile(os.path.join(REPO, 'io_variables.json')):
    datas.append((os.path.join(REPO, 'io_variables.json'), '.'))

# 숨김 import (런타임에 로드되는 모듈)
hiddenimports = [
    'flask',
    'flask_cors',
    'paho.mqtt.client',
    'engineio',
    'mqtt_subscriber',
]

a = Analysis(
    [os.path.join(BACKEND, 'launcher.py')],
    pathex=[BACKEND, REPO],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PLC모니터',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # 더블클릭 시 콘솔 창 안 띄움
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
