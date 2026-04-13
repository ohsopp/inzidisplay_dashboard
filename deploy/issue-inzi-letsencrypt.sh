#!/usr/bin/env bash
# Inzi Nginx용 Let's Encrypt 발급 (HTTP-01 webroot)
#
# 사전 조건:
#   - sudo bash deploy/server-apply-inzidisplay-nginx.sh 를 한 번 실행해 nginx·80 ACME·snippet 이 있을 것
#   - 공유기: 외부 80/TCP → 이 PC (Let's Encrypt 가 http://도메인/.well-known/ 로 검증)
#
# 사용:
#   export CERTBOT_EMAIL='you@example.com'   # 권장
#   sudo bash deploy/issue-inzi-letsencrypt.sh
#
# 이메일 없이(비권장):
#   sudo bash deploy/issue-inzi-letsencrypt.sh
#
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "root 로 실행: sudo bash deploy/issue-inzi-letsencrypt.sh" >&2
  exit 1
fi

WEBROOT=/var/www/certbot
mkdir -p "$WEBROOT" /etc/nginx/snippets

if ! command -v certbot >/dev/null 2>&1; then
  echo "certbot 설치: apt-get update && apt-get install -y certbot" >&2
  exit 1
fi

EMAIL_ARGS=()
if [ -n "${CERTBOT_EMAIL:-}" ]; then
  EMAIL_ARGS=(--email "$CERTBOT_EMAIL")
else
  echo "경고: CERTBOT_EMAIL 없음 — --register-unsafely-without-email 사용" >&2
  EMAIL_ARGS=(--register-unsafely-without-email)
fi

nginx -t
systemctl reload nginx 2>/dev/null || true

certbot certonly \
  --webroot -w "$WEBROOT" \
  -d inzi.duckdns.org \
  -d uitsolutions.iptime.org \
  --non-interactive \
  --agree-tos \
  "${EMAIL_ARGS[@]}" \
  --keep-until-expiring

cat >/etc/nginx/snippets/inzi-display-ssl.conf <<'EOF'
ssl_certificate     /etc/letsencrypt/live/inzi.duckdns.org/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/inzi.duckdns.org/privkey.pem;
EOF

nginx -t
systemctl reload nginx

echo ""
echo "Let's Encrypt 적용 완료."
echo "  curl -sS https://inzi.duckdns.org:6006/api/health"
echo "  갱신: certbot renew --webroot -w $WEBROOT --deploy-hook 'systemctl reload nginx'"
