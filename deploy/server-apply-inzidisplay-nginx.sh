#!/usr/bin/env bash
# uit-ai-server 에서 Inzi Nginx 를 올바르게 적용 (sudo 필수)
# - SIMPAC: sites-enabled/backend-api 가 simpac-api 와 5006+동일 server_name 중복 → backend-api 비활성화
# - Inzi: sites-available/inzidisplay-backend 를 sites-enabled 에 연결 (6006·444 listen)
# - inzi.duckdns.org + uitsolutions.iptime.org 용 self-signed SSL (브라우저는 경고, curl -k)
#
# 사용: cd 레포 루트에서
#   sudo bash deploy/server-apply-inzidisplay-nginx.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ "$(id -u)" -ne 0 ]; then
  echo "root 로 실행하세요: sudo bash deploy/server-apply-inzidisplay-nginx.sh" >&2
  exit 1
fi

echo "=== 1. Self-signed SSL (inzi.duckdns.org, SAN: uitsolutions.iptime.org) ==="
install -d -m 0755 /etc/ssl/certs
install -d -m 0750 /etc/ssl/private
TMP_CNF="$(mktemp)"
trap 'rm -f "$TMP_CNF"' EXIT
cat >"$TMP_CNF" <<'EOF'
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = inzi.duckdns.org

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment

[alt_names]
DNS.1 = inzi.duckdns.org
DNS.2 = uitsolutions.iptime.org
EOF

openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout /etc/ssl/private/inzi-duckdns.key \
  -out /etc/ssl/certs/inzi-duckdns.crt \
  -config "$TMP_CNF" -extensions v3_req
chmod 640 /etc/ssl/private/inzi-duckdns.key
chmod 644 /etc/ssl/certs/inzi-duckdns.crt

echo "=== 2. Nginx 설정 복사 + Inzi 활성화 ==="
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
cp -f "$REPO_ROOT/deploy/nginx-inzidisplay-backend.conf" /etc/nginx/sites-available/inzidisplay-backend
ln -sf /etc/nginx/sites-available/inzidisplay-backend /etc/nginx/sites-enabled/inzidisplay-backend

if ! grep -rq "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
  cp -f "$REPO_ROOT/deploy/nginx-inzidisplay-backend.conf" /etc/nginx/conf.d/inzidisplay-backend.conf
  echo "(참고) nginx.conf에 sites-enabled 없음 → conf.d/inzidisplay-backend.conf 로도 복사함"
fi

if [ -L /etc/nginx/sites-enabled/backend-api ]; then
  echo "=== 3. 중복 제거: backend-api 비활성화 (simpac-api 가 5006 담당) ==="
  rm -f /etc/nginx/sites-enabled/backend-api
fi

echo "=== 4. nginx 검사 및 reload ==="
nginx -t
systemctl reload nginx

REPO_OWNER="$(stat -c '%U' "$REPO_ROOT" 2>/dev/null || echo root)"
if ! id "$REPO_OWNER" &>/dev/null; then
  REPO_OWNER=root
fi

echo "=== 5. Gunicorn (inzidisplay-backend) — 502 방지 ==="
if [ ! -x "$REPO_ROOT/backend/venv/bin/gunicorn" ]; then
  echo "  venv 없음 → $REPO_OWNER 로 backend 에서 venv 생성 및 pip install (시간 소요)"
  sudo -u "$REPO_OWNER" bash -c "cd \"$REPO_ROOT/backend\" && python3 -m venv venv && ./venv/bin/pip install -q -r requirements.txt"
fi

cp -f "$REPO_ROOT/deploy/inzidisplay-backend.service" /etc/systemd/system/inzidisplay-backend.service
systemctl daemon-reload
systemctl enable inzidisplay-backend
if ! systemctl restart inzidisplay-backend; then
  echo "inzidisplay-backend restart 실패 (로그):" >&2
  journalctl -u inzidisplay-backend -n 30 --no-pager >&2
fi
sleep 2
if systemctl -q is-active inzidisplay-backend; then
  echo "  inzidisplay-backend: active"
else
  echo "  경고: inzidisplay-backend 기동 실패 — journalctl -u inzidisplay-backend -n 40" >&2
fi

echo ""
echo "완료."
echo "  백엔드 직접: curl -s http://127.0.0.1:8001/api/health"
echo "  Nginx 경유: curl -k https://127.0.0.1:6006/api/health"
echo "  외부:        curl -k https://inzi.duckdns.org:6006/api/health"
