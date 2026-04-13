#!/usr/bin/env bash
# DuckDNS 공인 IP 갱신 (cron 예: */5 * * * * /opt/inzi/duckdns-update-inzi.sh)
#
# 사용:
#   cp deploy/duckdns-update-inzi.example.sh /opt/inzi/duckdns-update-inzi.sh
#   chmod +x /opt/inzi/duckdns-update-inzi.sh
#   printf 'TOKEN=your-duckdns-token\n' > /opt/inzi/.duckdns-inzi.env
#   chmod 600 /opt/inzi/.duckdns-inzi.env
#
# duckdns.org 에서 서브도메인 이름이 예: inzi 이면 domains=inzi

set -euo pipefail
ENV_FILE="${DUCKDNS_ENV_FILE:-/opt/inzi/.duckdns-inzi.env}"
DOMAINS="${DUCKDNS_DOMAINS:-inzi}"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a && . "$ENV_FILE" && set +a
fi

if [ -z "${TOKEN:-}" ]; then
  echo "duckdns: TOKEN 이 없습니다. $ENV_FILE 에 TOKEN=... 를 설정하세요." >&2
  exit 1
fi

# ip 비우면 DuckDNS 가 접속 출발지 IP 로 갱신
curl -fsS "https://www.duckdns.org/update?domains=${DOMAINS}&token=${TOKEN}&ip=" -o /tmp/duckdns-inzi.out
cat /tmp/duckdns-inzi.out
echo
