#!/usr/bin/env bash
# Inzi Display 백엔드만 설치 (다른 사이트의 plc-backend·nginx 설정 파일은 덮어쓰지 않음)
# 사용: 이 레포 루트에서 sudo bash deploy/install-inzidisplay-backend.sh
#
# 사전 준비:
#   - backend/venv 및 pip install -r requirements.txt
#   - deploy/inzidisplay-backend.service 내 User·경로·PG/Influx 비밀번호 확인
#   - deploy/nginx-inzidisplay-backend.conf 의 ssl_certificate (Let's Encrypt 권장)
#   - 방화벽·공유기: 444/TCP(iptime HTTPS), 6006/TCP(Inzi Nginx·DuckDNS 등), 6005/TCP(Vercel→Gunicorn 직결)
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
echo "=== 2. Nginx: SSL(self-signed) + inzidisplay-backend 활성화 + SIMPAC 5006 중복 제거 ==="
bash "$REPO_ROOT/deploy/server-apply-inzidisplay-nginx.sh"

echo ""
echo "완료."
echo "  상태: sudo systemctl status inzidisplay-backend"
echo "  로그: sudo journalctl -u inzidisplay-backend -f"
echo "  헬스(Nginx): curl -k https://127.0.0.1:444/api/health"
echo "               curl -k https://127.0.0.1:6006/api/health  (Inzi Nginx HTTPS, 공유기 inzi-nginx)"
echo "  헬스(직결):  curl -s http://127.0.0.1:6005/api/health   (Vercel rewrite와 동일 포트)"
echo "기존 다른 웹(plc-backend 등) 서비스는 이 스크립트에서 시작/중지하지 않습니다."
