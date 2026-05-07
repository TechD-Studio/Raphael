#!/usr/bin/env bash
# Raphael 데몬을 PyInstaller --onedir 로 빌드 → Tauri resources 로 번들링.
# --onefile 은 매 실행마다 _MEI 추출(70MB)에 ~3~5초가 들어 콜드 스타트가
# 길어진다. --onedir 은 추출이 없어 ~0.5초로 떨어진다.
# 출력: desktop/src-tauri/binaries/raphaeld/  (raphaeld 바이너리 + _internal/)
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q pyinstaller fastapi uvicorn

OUT_DIR="desktop/src-tauri/binaries"
mkdir -p "$OUT_DIR"
rm -rf "$OUT_DIR/raphaeld"

pyinstaller \
    --onedir \
    --name "raphaeld" \
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

echo "✅ Sidecar built: $OUT_DIR/raphaeld/raphaeld"
