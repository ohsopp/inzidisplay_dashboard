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
- **bind**: 기본 `127.0.0.1:8001` + `0.0.0.0:6005` (SIMPAC/react_dashboard 의 8000+5005 패턴과 동형; 공유기 포트포워딩은 6005). 단일 주소만 쓰려면 `GUNICORN_BIND=127.0.0.1:8001`.
- **workers/threads**: workers=1 기본, threads 등은 `GUNICORN_WORKERS`, `GUNICORN_THREADS` 로 조정.
- **timeout**: 기본 300초 (SIMPAC 백엔드와 동일 계열). `GUNICORN_TIMEOUT` 로 조정.
- **로그**: 기본 `backend/logs/gunicorn_access.log`, `gunicorn_error.log`. `GUNICORN_LOG_DIR` 또는 `GUNICORN_ACCESS_LOG`/`GUNICORN_ERROR_LOG` 로 변경 가능.

로컬 테스트:

```bash
cd backend
./venv/bin/gunicorn -c gunicorn_config.py app:app
# 다른 터미널: curl http://127.0.0.1:8001/api/health  또는 curl http://127.0.0.1:6005/api/health
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

- **Gunicorn 포트**: 기본 8001. 변경했다면 Nginx `upstream`/ `proxy_pass`와 systemd `GUNICORN_BIND`를 함께 수정.
- **동일 서버 전용 설치**: `sudo bash deploy/install-inzidisplay-backend.sh` — `inzidisplay-backend` 서비스와 `sites-enabled/inzidisplay-backend`만 등록하며, 기존 `plc-backend` 설정은 덮어쓰지 않음.
- **HTTPS**: Let's Encrypt 사용 시 `sudo certbot --nginx -d example.com` 실행 후, certbot이 자동으로 443 블록을 추가/수정합니다. 수동이면 주석 해제 후 인증서 경로만 맞추면 됩니다.

---

## 5. 환경별 체크리스트

### 경로·권한
- 프로젝트 루트(예: `/opt/plc_test`), `WorkingDirectory`(예: `/opt/plc_test/backend`), `backend/logs`, `backend/poll_logs` 에 대해 systemd 서비스의 User/Group이 읽기·쓰기 가능한지 확인.

### 포트 (inzidisplay-backend)
- **8001**: 루프백만(Nginx→Gunicorn). **6005**: Vercel `rewrite` 직결용(SIMPAC의 5005와 같은 역할). **444**: Nginx HTTPS(선택 경로).
- SIMPAC `react_dashboard`의 **8000·5005·5006** 과 겹치지 않게 유지할 것.

### 도메인·DNS
- Nginx `server_name`에 쓴 도메인이 해당 서버 공인 IP를 가리키는지 확인.

### DuckDNS (Inzi)
1. [duckdns.org](https://www.duckdns.org/) 에서 서브도메인(예: `inzi`)을 만들고 토큰을 복사합니다. FQDN은 `inzi.duckdns.org` 형태입니다.
2. **SIMPAC**은 공유기에서 **5005·5006·443** 등을 쓰고, **Inzi**는 **6005·6006·444** 로 두는 구성이 일반적입니다(같은 내부 IP·같은 PC에서 외부 포트가 겹치면 안 됨). Inzi Nginx HTTPS는 **`listen 6006`** 이며, 공유기 규칙 **inzi-nginx: 외부 6006 → 내부 6006** 과 맞춥니다. iptime용 **444** 규칙(inzi-gunicorn)과 함께 씁니다.
3. 공인 IP가 바뀌는 환경이면 `deploy/duckdns-update-inzi.example.sh` 를 서버에 복사해 토큰을 넣고, cron으로 5분마다 실행해 DuckDNS A 레코드를 갱신합니다.
4. Let’s Encrypt (SIMPAC과 동일하게 신뢰 인증서): 공유기에 **외부 80 → 이 서버** 포워딩을 추가한 뒤 `sudo bash deploy/server-apply-inzidisplay-nginx.sh` 로 Nginx(80 ACME 포함)를 적용하고, `export CERTBOT_EMAIL='...'; sudo bash deploy/issue-inzi-letsencrypt.sh` 실행. 인증서는 `/etc/nginx/snippets/inzi-display-ssl.conf` 에 반영됩니다.
5. 브라우저/API URL 예: `https://inzi.duckdns.org:6006/api/...` (DuckDNS가 443이 아니면 포트 번호 필요).

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
