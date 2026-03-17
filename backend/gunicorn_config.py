"""
Gunicorn 설정 — 실제 서버 배포용.
- bind: 127.0.0.1:8000 (Nginx가 이 주소로 프록시. 8000 사용 중이면 8001 등으로 변경)
- workers: 2 (CPU 코어 적을 때 적당. I/O·SSE 많으면 2~4)
- timeout: 120 (SSE 장기 연결 허용)
- chdir: backend 디렉터리
- wsgi_app: app:app
"""
import multiprocessing
import os

# 프로젝트 백엔드 루트 (이 설정 파일이 있는 디렉터리)
_chdir = os.path.dirname(os.path.abspath(__file__))

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")
chdir = _chdir
wsgi_app = "app:app"

workers = int(os.environ.get("GUNICORN_WORKERS", 2))
threads = int(os.environ.get("GUNICORN_THREADS", 2))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 120))
keepalive = 5

# 로그: 프로젝트 내 logs 또는 /var/log
_log_dir = os.environ.get("GUNICORN_LOG_DIR", os.path.join(_chdir, "logs"))
os.makedirs(_log_dir, exist_ok=True)
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", os.path.join(_log_dir, "gunicorn_access.log"))
errorlog = os.environ.get("GUNICORN_ERROR_LOG", os.path.join(_log_dir, "gunicorn_error.log"))
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True

# 프로세스 이름
proc_name = "plc-backend"
