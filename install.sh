#!/usr/bin/env bash
# Raphael 설치 스크립트 — Mac / Linux 호환
# 사용: bash install.sh

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SCRIPT_DIR/.venv"
RAPHAEL_BIN="$VENV_DIR/bin/raphael"

# ── 색상 ──────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ── OS 감지 ───────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Darwin*) PLATFORM="mac" ;;
    Linux*)  PLATFORM="linux" ;;
    *)
        error "지원하지 않는 OS입니다: $OS (Mac/Linux만 지원)"
        exit 1
        ;;
esac
info "플랫폼 감지: $PLATFORM"

# ── Python 감지 ───────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    error "Python3를 찾을 수 없습니다. 먼저 설치해주세요."
    if [ "$PLATFORM" = "mac" ]; then
        echo "  brew install python@3.11"
    else
        echo "  sudo apt install python3 python3-venv  (Debian/Ubuntu)"
        echo "  sudo dnf install python3                (Fedora)"
    fi
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python 버전: $PY_VERSION"

# 3.11 이상 확인
PY_OK=$($PYTHON -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)')
if [ "$PY_OK" != "1" ]; then
    error "Python 3.11+ 이 필요합니다. 현재: $PY_VERSION"
    exit 1
fi

# ── venv 생성 ─────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    info "venv 생성 중..."
    $PYTHON -m venv "$VENV_DIR"
else
    info "기존 venv 재사용: $VENV_DIR"
fi

# ── 의존성 설치 ───────────────────────────────────────
info "의존성 설치 중..."
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null 2>&1
"$VENV_DIR/bin/pip" install -e "$SCRIPT_DIR" >/dev/null

if [ ! -f "$RAPHAEL_BIN" ]; then
    error "raphael 바이너리 생성 실패: $RAPHAEL_BIN"
    exit 1
fi
info "raphael 바이너리: $RAPHAEL_BIN"

# ── 셸 감지 ───────────────────────────────────────────
detect_shell_rc() {
    local shell_name
    shell_name=$(basename "${SHELL:-/bin/bash}")

    case "$shell_name" in
        zsh)  echo "$HOME/.zshrc" ;;
        bash)
            # Mac은 보통 .bash_profile, Linux는 .bashrc
            if [ "$PLATFORM" = "mac" ] && [ -f "$HOME/.bash_profile" ]; then
                echo "$HOME/.bash_profile"
            elif [ -f "$HOME/.bashrc" ]; then
                echo "$HOME/.bashrc"
            else
                echo "$HOME/.bash_profile"
            fi
            ;;
        fish) echo "$HOME/.config/fish/config.fish" ;;
        *)    echo "" ;;
    esac
}

RC_FILE=$(detect_shell_rc)
SHELL_NAME=$(basename "${SHELL:-/bin/bash}")

if [ -z "$RC_FILE" ]; then
    warn "셸($SHELL_NAME)을 인식하지 못했습니다. 수동으로 alias를 등록해주세요:"
    echo "  alias raphael='$RAPHAEL_BIN'"
    exit 0
fi

info "셸 감지: $SHELL_NAME ($RC_FILE)"

# ── alias 등록 ────────────────────────────────────────
MARKER_BEGIN="# >>> raphael >>>"
MARKER_END="# <<< raphael <<<"

# 기존 블록 제거
if [ -f "$RC_FILE" ] && grep -q "$MARKER_BEGIN" "$RC_FILE"; then
    info "기존 raphael 설정 제거 후 재등록"
    # portable sed: Mac/Linux 모두 동작하도록 임시 파일 사용
    awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
        $0 == b { skip=1; next }
        $0 == e { skip=0; next }
        skip != 1 { print }
    ' "$RC_FILE" > "$RC_FILE.tmp" && mv "$RC_FILE.tmp" "$RC_FILE"
fi

if [ "$SHELL_NAME" = "fish" ]; then
    mkdir -p "$(dirname "$RC_FILE")"
    {
        echo ""
        echo "$MARKER_BEGIN"
        echo "alias raphael '$RAPHAEL_BIN'"
        echo "$MARKER_END"
    } >> "$RC_FILE"
else
    {
        echo ""
        echo "$MARKER_BEGIN"
        echo "alias raphael=\"$RAPHAEL_BIN\""
        echo "$MARKER_END"
    } >> "$RC_FILE"
fi

info "alias 등록 완료: $RC_FILE"

# ── 완료 ──────────────────────────────────────────────
echo ""
echo -e "${GREEN}설치 완료!${NC}"
echo ""
echo "다음 중 하나를 실행하세요:"
echo ""
echo "  1. 새 터미널을 열고:"
echo "       raphael onboard"
echo ""
echo "  2. 또는 현재 터미널에서:"
echo "       source $RC_FILE"
echo "       raphael onboard"
echo ""
