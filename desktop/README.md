# Raphael Desktop (Tauri + React)

**MVP**: 채팅 + 세션 사이드바. 데이터는 `~/.raphael/` (CLI/Web 공유).

## 구조

```
desktop/
├── src/                    # React UI (Vite + TS)
│   ├── App.tsx             # 메인 컴포넌트 (사이드바 + 채팅)
│   ├── api.ts              # raphaeld 클라이언트 (SSE 스트리밍)
│   └── App.css             # 스타일
├── src-tauri/
│   ├── src/lib.rs          # Tauri 셸 + sidecar spawn/kill
│   ├── tauri.conf.json     # Tauri 설정 (sidecar 등록)
│   ├── capabilities/       # 권한
│   └── binaries/
│       └── raphaeld-<triple>   # PyInstaller로 빌드된 Python 데몬
├── build_sidecar.sh        # PyInstaller 빌드 스크립트
└── package.json
```

## 개발 실행

```bash
# 1. 백엔드 데몬 빌드 (PyInstaller, ~75MB)
cd /Users/dh/Raphael
bash desktop/build_sidecar.sh

# 2. 프론트엔드 의존성
cd desktop
pnpm install

# 3. 개발 모드 (Vite + Tauri 함께)
pnpm tauri dev
```

첫 실행은 Rust 크레이트 다운로드/컴파일 때문에 5~10분 소요됩니다.

## 프로덕션 빌드

```bash
cd desktop
pnpm tauri build
# 출력: src-tauri/target/release/bundle/{dmg,msi}
```

## 데이터 위치 (CLI/Web/Desktop 공유)

- 세션: `~/.raphael/sessions/<id>.json`
- 에이전트: `~/.raphael/agents/<name>.md`
- 실패 케이스: `~/.raphael/failures/`

## 자동 업데이트

`src-tauri/Cargo.toml`에 `tauri-plugin-updater` 추가됨.
GitHub Release + `latest.json` 매니페스트 배포 시 자동 작동.
공개 키 생성 + `tauri.conf.json` 설정 필요 (다음 단계).

## 상태

- [x] GitHub Actions 워크플로우 (`.github/workflows/release.yml`) — Mac arm64 + Win x64
- [x] `tauri-plugin-updater` 설치 — 공개키 등록은 `desktop/SIGNING.md` 참고
- [x] 시스템 트레이 + 글로벌 단축키 (`Cmd+Shift+R` / `Ctrl+Shift+R`)
- [x] 마크다운 렌더링 (`react-markdown` + GFM + highlight.js)
- [ ] 에이전트/모델 설정 GUI
- [ ] Code signing (Apple Developer ID, 추후)

## 첫 릴리스 절차

1. `desktop/SIGNING.md` 읽고 키 페어 생성 + GitHub Secrets 등록
2. `desktop/src-tauri/tauri.conf.json` 의 `pubkey`/`endpoints` 갱신
3. `git tag v0.1.0 && git push origin v0.1.0`
4. GitHub Actions가 빌드 → Release(draft) 생성 → 검토 후 publish
