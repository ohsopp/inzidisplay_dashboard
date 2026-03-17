#!/usr/bin/env bash
# 한 번에 적용: systemd 서비스 + Nginx. 반드시 sudo로 실행하세요.
# 사용: sudo bash deploy/apply-now.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1. systemd plc-backend ==="
cp -f deploy/plc-backend.service /etc/systemd/system/plc-backend.service
systemctl daemon-reload
systemctl enable plc-backend
systemctl start plc-backend
systemctl status plc-backend --no-pager

echo ""
echo "=== 2. Nginx (6006, 443 → Gunicorn 8000) ==="
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/conf.d
cp -f deploy/nginx-plc-backend.conf /etc/nginx/sites-available/plc-backend
ln -sf /etc/nginx/sites-available/plc-backend /etc/nginx/sites-enabled/plc-backend
# nginx.conf에 include sites-enabled 없으면 conf.d에도 복사
if ! grep -rq "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
  cp -f deploy/nginx-plc-backend.conf /etc/nginx/conf.d/plc-backend.conf
  echo "sites-enabled 미사용 → conf.d/plc-backend.conf 로도 복사함"
fi
NGINX_BIN=""
for p in /usr/sbin/nginx /usr/bin/nginx; do [ -x "$p" ] && NGINX_BIN="$p" && break; done
[ -z "$NGINX_BIN" ] && NGINX_BIN=$(command -v nginx 2>/dev/null)
if [ -n "$NGINX_BIN" ] && [ -x "$NGINX_BIN" ]; then
  ($NGINX_BIN -t && systemctl reload nginx) || echo "nginx -t 또는 reload 실패"
else
  echo "Nginx 미설치 또는 실행 불가. 설정만 복사됨."
  echo "  Nginx 설치: sudo apt install nginx   이후  sudo nginx -t && sudo systemctl reload nginx"
fi

echo ""
echo "배포 완료. 확인: curl -k https://localhost:443/api/health 또는 http://localhost:6006/api/health"
