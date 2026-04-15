#!/usr/bin/env bash
# Raphael 데몬을 PyInstaller로 단일 바이너리화 → Tauri sidecar로 사용.
# 출력: desktop/src-tauri/binaries/raphaeld-<target-triple>
set -euo pipefail

cd "$(dirname "$0")/.."

# venv 준비 + pyinstaller 설치
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q pyinstaller fastapi uvicorn

# 타깃 트리플 자동 감지
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)  TRIPLE="aarch64-apple-darwin" ;;
    Darwin-x86_64) TRIPLE="x86_64-apple-darwin" ;;
    Linux-x86_64)  TRIPLE="x86_64-unknown-linux-gnu" ;;
    *) echo "Unsupported platform: $(uname -sm)"; exit 1 ;;
esac

OUT_DIR="desktop/src-tauri/binaries"
mkdir -p "$OUT_DIR"

# PyInstaller — 단일 파일 + Raphael 모든 모듈/데이터 포함
pyinstaller \
    --onefile \
    --name "raphaeld-${TRIPLE}" \
    --distpath "$OUT_DIR" \
    --workpath "build/pyinstaller" \
    --specpath "build/pyinstaller" \
    --add-data "$(pwd)/config/settings.yaml:config" \
    --hidden-import=core --hidden-import=tools --hidden-import=interfaces \
    --hidden-import=uvicorn.lifespan.on \
    --hidden-import=uvicorn.lifespan.off \
    --hidden-import=uvicorn.protocols.http.h11_impl \
    --hidden-import=uvicorn.protocols.websockets.wsproto_impl \
    --collect-submodules core --collect-submodules tools \
    interfaces/daemon.py

echo "✅ Sidecar built: $OUT_DIR/raphaeld-${TRIPLE}"
