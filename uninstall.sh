#!/usr/bin/env bash
# Raphael 제거 스크립트 — alias 및 venv 삭제

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SCRIPT_DIR/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

MARKER_BEGIN="# >>> raphael >>>"
MARKER_END="# <<< raphael <<<"

# 셸별 rc 파일 모두 확인
for RC in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.config/fish/config.fish"; do
    if [ -f "$RC" ] && grep -q "$MARKER_BEGIN" "$RC"; then
        awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
            $0 == b { skip=1; next }
            $0 == e { skip=0; next }
            skip != 1 { print }
        ' "$RC" > "$RC.tmp" && mv "$RC.tmp" "$RC"
        info "alias 제거: $RC"
    fi
done

# venv 삭제
if [ -d "$VENV_DIR" ]; then
    read -p "venv 디렉토리($VENV_DIR)도 삭제할까요? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        rm -rf "$VENV_DIR"
        info "venv 삭제 완료"
    else
        warn "venv는 보존했습니다."
    fi
fi

info "제거 완료. 새 터미널을 열면 raphael 명령어가 사라집니다."
