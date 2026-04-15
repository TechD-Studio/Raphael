# Tauri Updater 서명 키 셋업 (1회성)

## 1. 키 페어 생성

```bash
cd desktop
pnpm tauri signer generate -w ~/.tauri/raphael.key
```

출력:
- 개인키: `~/.tauri/raphael.key` (절대 공개 금지)
- 공개키: 터미널에 표시됨 (긴 base64 문자열)

## 2. 공개키 등록

`desktop/src-tauri/tauri.conf.json` 의 `plugins.updater.pubkey`에 공개키 붙여넣기.
endpoints의 `YOUR_USER`를 GitHub 사용자명으로 변경.

## 3. GitHub Secrets 등록

GitHub 리포지토리 → Settings → Secrets and variables → Actions → New repository secret:

- `TAURI_SIGNING_PRIVATE_KEY`: `~/.tauri/raphael.key` 파일 내용 전체
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: 키 생성 시 입력한 패스워드 (없으면 빈 값)

## 4. 첫 릴리스

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions가:
1. macOS arm64 + Windows x64 빌드
2. 사이드카 + 앱 번들 생성
3. 서명된 `.dmg`/`.msi` + `.sig` 파일을 GitHub Release(draft)에 업로드
4. `latest.json` 매니페스트 업로드

Draft Release를 검토 후 publish하면 사용자에게 자동 업데이트 알림 표시.

## 5. 코드 서명 (배포 시작 시)

**MVP는 무서명 OK** — 사용자가 경고 화면 우회 필요:
- macOS: 우클릭 → 열기 (Gatekeeper 1회 우회)
- Windows: SmartScreen "추가 정보" → "실행"

**배포 본격화 시**:
- macOS: Apple Developer Program $99/yr → Developer ID Application 인증서 → notarization
- Windows: EV Code Sign Cert $300+/yr (또는 일반 OV $80~)
