# PLC 백엔드 서버 배포 가이드

## 1. 앱 엔트리·의존성 요약

| 항목 | 값 |
|------|-----|
| **WSGI 엔트리** | `app:app` (모듈 `app`, 객체 `app`) |
| **경로** | `backend/app.py` 에서 `app = Flask(__name__)` |
| **Python** | 3.8+ 권장 |
| **주요 의존성** | Flask, flask-cors, paho-mqtt, pymcprotocol, influxdb-client, psycopg, gunicorn |

가상환경 생성 및 설치:

```bash
cd /opt/plc_test/backend   # 실제 배포 경로로 변경
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

---

## 2. Gunicorn 설정

- **설정 파일**: `backend/gunicorn_config.py`
- **bind**: `127.0.0.1:8000` (Nginx가 이 주소로 프록시). 8000 사용 중이면 `GUNICORN_BIND=127.0.0.1:8001` 등으로 변경.
- **workers/threads**: workers=2, threads=2 (I/O·SSE 고려). `GUNICORN_WORKERS`, `GUNICORN_THREADS` 로 조정 가능.
- **timeout**: 120초 (SSE 장기 연결). `GUNICORN_TIMEOUT` 로 조정 가능.
- **로그**: 기본 `backend/logs/gunicorn_access.log`, `gunicorn_error.log`. `GUNICORN_LOG_DIR` 또는 `GUNICORN_ACCESS_LOG`/`GUNICORN_ERROR_LOG` 로 변경 가능.

로컬 테스트:

```bash
cd backend
./venv/bin/gunicorn -c gunicorn_config.py app:app
# 다른 터미널: curl http://127.0.0.1:8000/api/health  → 200 {"status":"ok"}
```

---

## 3. systemd 서비스 등록

**중요**: `deploy/plc-backend.service` 안의 **WorkingDirectory**, **User/Group**, **ExecStart 경로**, **환경 변수**를 실제 서버에 맞게 수정한 뒤 설치하세요.

```bash
# 경로 예: /opt/plc_test. 프로젝트를 이 경로에 클론/배치했다고 가정.
sudo cp deploy/plc-backend.service /etc/systemd/system/
# 서비스 파일 내부에서 WorkingDirectory, User, ExecStart 경로를 실제 경로로 수정했는지 확인

sudo systemctl daemon-reload
sudo systemctl enable plc-backend
sudo systemctl start plc-backend
sudo systemctl status plc-backend
```

- **User/Group**: 프로젝트 디렉터리 소유자. 예: `ubuntu`, `www-data` 등. `backend/logs`, `backend/poll_logs` 쓰기 권한 필요.
- **환경 변수**: PostgreSQL(`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`), InfluxDB(`INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, `INFLUX_BUCKET`)를 실제 값으로 설정. 비밀번호는 `EnvironmentFile=/path/to/.env` 로 분리 권장.

---

## 4. Nginx 설정 (80/443 → Gunicorn)

**중요**: `deploy/nginx-plc-backend.conf` 의 **server_name**(도메인), **ssl_certificate**/**ssl_certificate_key**(HTTPS 사용 시)를 실제 값으로 바꾸세요.

```bash
sudo cp deploy/nginx-plc-backend.conf /etc/nginx/sites-available/plc-backend
sudo ln -sf /etc/nginx/sites-available/plc-backend /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

- **Gunicorn 포트**: 기본 8000. 변경했다면 Nginx의 `proxy_pass http://127.0.0.1:8000` 도 함께 수정.
- **Vercel 502 (`ROUTER_EXTERNAL_TARGET_CONNECTION_ERROR`)**: Vercel 엣지가 집 서버에 TCP로 못 붙을 때 납니다. `vercel.json` rewrite만으로는 한계가 있을 수 있어, Vercel 프로젝트 환경변수 **`VITE_API_URL`** 에 브라우저가 직접 붙을 **HTTPS 백엔드 베이스**(예: Let’s Encrypt 적용한 `https://uitsolutions.iptime.org:444` 또는 Cloudflare Tunnel URL)를 넣고 재빌드하면 API/SSE가 Vercel 프록시를 거치지 않습니다. CORS는 백엔드 `app.py`에서 이미 허용되어 있습니다.

---

## 5. 환경별 체크리스트

### 경로·권한
- 프로젝트 루트(예: `/opt/plc_test`), `WorkingDirectory`(예: `/opt/plc_test/backend`), `backend/logs`, `backend/poll_logs` 에 대해 systemd 서비스의 User/Group이 읽기·쓰기 가능한지 확인.

### 포트
- Gunicorn bind 포트(기본 8000)가 다른 서비스와 충돌하지 않는지 확인.
- 방화벽(UFW 등)은 80/443만 열고, 8000은 외부에 노출하지 않기.

### 도메인·DNS
- Nginx `server_name`에 쓴 도메인이 해당 서버 공인 IP를 가리키는지 확인.

### SSL
- 인증서 유효 기간, certbot 자동 갱신(cron/타이머) 설정 여부 확인.

### 외부 서비스
- **PostgreSQL**: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD (또는 POSTGRES_DSN).
- **InfluxDB**: INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET.
- **선택**: POLL_LOGS_DIR(NDJSON 수집 경로), MQTT 관련 환경 변수.

### 성능
- 트래픽에 따라 `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` 조정.
- Nginx `proxy_read_timeout`, `client_max_body_size` 등 필요 시 조정.

### 로그·모니터링
- **Gunicorn**: `backend/logs/gunicorn_access.log`, `gunicorn_error.log` (또는 설정에서 지정한 경로).
- **Nginx**: `/var/log/nginx/access.log`, `/var/log/nginx/error.log`.
- 문제 발생 시: `sudo journalctl -u plc-backend -f`, `sudo tail -f backend/logs/gunicorn_error.log` 로 확인.
