#!/usr/bin/env bash
# 실제 서버에서 실행: systemd 서비스·Nginx 설정 복사 및 활성화
# 사용법: sudo bash deploy/install-on-server.sh
# 주의: plc-backend.service, nginx-plc-backend.conf 내부 경로·도메인·환경변수를 먼저 수정하세요.

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== systemd ==="
cp -f deploy/plc-backend.service /etc/systemd/system/plc-backend.service
systemctl daemon-reload
systemctl enable plc-backend
systemctl start plc-backend
systemctl status plc-backend --no-pager || true

echo ""
echo "=== Nginx ==="
cp -f deploy/nginx-plc-backend.conf /etc/nginx/sites-available/plc-backend
ln -sf /etc/nginx/sites-available/plc-backend /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

echo ""
echo "설치 완료. 백엔드: systemctl status plc-backend, Nginx: nginx -t && systemctl status nginx"
