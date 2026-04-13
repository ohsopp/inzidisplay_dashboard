#!/usr/bin/env bash
# Inzi Display 백엔드만 설치 (다른 사이트의 plc-backend·nginx 설정 파일은 덮어쓰지 않음)
# 사용: 이 레포 루트에서 sudo bash deploy/install-inzidisplay-backend.sh
#
# 사전 준비:
#   - backend/venv 및 pip install -r requirements.txt
#   - deploy/inzidisplay-backend.service 내 User·경로·PG/Influx 비밀번호 확인
#   - deploy/nginx-inzidisplay-backend.conf 의 ssl_certificate (Let's Encrypt 권장)
#   - 방화벽·공유기: 444/TCP(Nginx HTTPS), 6005/TCP(Vercel→Gunicorn 직결, SIMPAC의 5005와 동일 역할)
#   - SIMPAC/react_dashboard 의 8000·5005·5006 과 겹치지 않음(여기서는 8001·6005·444)

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1. systemd: inzidisplay-backend (Gunicorn 127.0.0.1:8001 + 0.0.0.0:6005) ==="
cp -f deploy/inzidisplay-backend.service /etc/systemd/system/inzidisplay-backend.service
systemctl daemon-reload
systemctl enable inzidisplay-backend
systemctl restart inzidisplay-backend
systemctl status inzidisplay-backend --no-pager || true

echo ""
echo "=== 2. Nginx: sites-available/inzidisplay-backend (HTTPS 444 → 8001) ==="
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/conf.d
cp -f deploy/nginx-inzidisplay-backend.conf /etc/nginx/sites-available/inzidisplay-backend
ln -sf /etc/nginx/sites-available/inzidisplay-backend /etc/nginx/sites-enabled/inzidisplay-backend
if ! grep -rq "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
  cp -f deploy/nginx-inzidisplay-backend.conf /etc/nginx/conf.d/inzidisplay-backend.conf
  echo "(참고) nginx.conf에 sites-enabled 없음 → conf.d/inzidisplay-backend.conf 로도 복사함"
fi

NGINX_BIN=""
for p in /usr/sbin/nginx /usr/bin/nginx; do [ -x "$p" ] && NGINX_BIN="$p" && break; done
[ -z "$NGINX_BIN" ] && NGINX_BIN=$(command -v nginx 2>/dev/null)
if [ -n "$NGINX_BIN" ] && [ -x "$NGINX_BIN" ]; then
  $NGINX_BIN -t
  systemctl reload nginx
else
  echo "Nginx 바이너리를 찾지 못함. 설정만 복사됨."
fi

echo ""
echo "완료."
echo "  상태: sudo systemctl status inzidisplay-backend"
echo "  로그: sudo journalctl -u inzidisplay-backend -f"
echo "  헬스(Nginx): curl -k https://127.0.0.1:444/api/health   (snakeoil이면 -k)"
echo "  헬스(직결):  curl -s http://127.0.0.1:6005/api/health   (Vercel rewrite와 동일 포트)"
echo "기존 다른 웹(plc-backend 등) 서비스는 이 스크립트에서 시작/중지하지 않습니다."
