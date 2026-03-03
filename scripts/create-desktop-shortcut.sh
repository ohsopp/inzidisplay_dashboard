#!/usr/bin/env bash
# 바탕화면에 PLC 모니터.desktop 생성 (절대경로, 실행 허용). PLC모니터.sh 실행 시 자동 호출됨.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -x "$REPO_ROOT/dist/PLC모니터" ]; then
  EXEC="$REPO_ROOT/dist/PLC모니터"
else
  EXEC="$REPO_ROOT/PLC모니터.sh"
fi

DESKTOP=""
for candidate in "$XDG_DESKTOP_DIR" "$HOME/Desktop" "$HOME/바탕화면" "$HOME/desktop"; do
  [ -z "$candidate" ] && continue
  if [ -d "$candidate" ]; then
    DESKTOP="$candidate"
    break
  fi
done
[ -z "$DESKTOP" ] && DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
mkdir -p "$DESKTOP"

cat > "$DESKTOP/PLC모니터.desktop" << EOF
[Desktop Entry]
Type=Application
Name=PLC 모니터
Comment=PLC 모니터 실행 (Vite 개발서버 http://localhost:5173 자동 오픈)
Exec=$EXEC
Path=$REPO_ROOT
Terminal=true
Categories=Utility;
EOF
chmod +x "$DESKTOP/PLC모니터.desktop"
gio set "$DESKTOP/PLC모니터.desktop" metadata::trusted true 2>/dev/null || true

echo "바탕화면에 plc 모니터 바로가기 생성"
