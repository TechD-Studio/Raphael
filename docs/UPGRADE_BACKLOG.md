# Raphael 업그레이드 백로그

> 보류 중인 기능 목록. 우선순위 재평가 후 진행.

---

## 검색 강화 — 3단계 (쇼핑/가격 전문 검색)

상세: `docs/SEARCH_UPGRADE.md` 참조

| 항목 | 설명 | 공수 |
|---|---|---|
| 네이버 쇼핑 API | 최저가 직접 반환, 무료 25,000건/일 | 2~3h |
| Serper 쇼핑 탭 | 기존 키 활용, `"type": "shopping"` | 1~2h |
| 다나와 직접 파싱 | API 키 불필요, HTML 구조 변경 리스크 | 3~4h |

---

## LoRA 파인튜닝 파이프라인

옵시디언 노트로 gemma4를 도메인 특화 학습.

### 파이프라인 개요

```
옵시디언 볼트 → Q&A 쌍 자동 변환 → QLoRA 학습 (mlx-lm) → 모델 병합 → GGUF → Ollama 등록
```

### 단계별 계획

| # | 항목 | 설명 | 공수 |
|---|---|---|---|
| F1 | **Modelfile 시스템 프롬프트 최적화** | 페르소나/어조 즉시 개선, `ollama create` | 10분 |
| F2 | **옵시디언→JSONL 변환기** | 노트를 섹션별 Q&A 쌍으로 자동 변환 (`raphael finetune prepare`) | 3~4h |
| F3 | **QLoRA 학습 자동화** | `mlx_lm.lora` 래퍼, gemma4-e2b 대상, ~5분 학습 | 2~3h |
| F4 | **모델 병합+등록** | fuse → GGUF → `ollama create` 자동화 (`raphael finetune build`) | 2~3h |
| F5 | **데스크톱 UI** | 설정에서 볼트 경로→학습→등록 원클릭 | 4~6h |

### 기술 세부사항

- **도구**: `mlx-lm` (Apple Silicon 네이티브, gemma4 아키텍처 지원 확인됨)
- **하드웨어**: M5 16GB — gemma4-e2b(5.1B) 여유, e4b(9B) 빡빡
- **학습 데이터**: 300~500 Q&A 쌍 권장 (200개 노트 × 3섹션)
- **학습 설정**: rank=8, alpha=8, batch=2, iters=600, lr=1e-4
- **실효성**: 도메인 용어/스타일/추론 패턴에 효과적. 사실 검색은 RAG가 우위.
- **권장 조합**: LoRA(행동) + RAG(지식) 하이브리드

### 전제 조건

- `pip install mlx-lm` (Apple Silicon 전용)
- `llama.cpp` (GGUF 변환용)
- 옵시디언 볼트 설정 완료 (RAG와 동일 경로)

### 참고 자료

- [mlx-lm LoRA 문서](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)
- [Gemma 4 파인튜닝 가이드 (Unsloth)](https://unsloth.ai/docs/models/gemma-4/train)
- [Doc-to-LoRA (Sakana AI)](https://pub.sakana.ai/doc-to-lora/) — 미래 대안 (문서→LoRA 1초 생성)

---

## Xcode/iOS 자동화 (맥미니 M4 32GB 전용)

> 전제: 맥미니 M4 32GB에서 gemma4-26b를 원격 Ollama로 운용

### 파이프라인

```
Swift/Xcode 에러 패턴 학습 데이터 생성 → gemma4-26b QLoRA 학습 (M4 32GB)
→ Xcode 전용 도구 (xcodebuild/simctl 래퍼) → 자동 빌드-에러분석-수정 루프
```

| # | 항목 | 설명 | 공수 |
|---|---|---|---|
| X1 | Swift/Xcode 에러 학습 데이터셋 | 빌드 에러 500쌍 + 프로젝트 구조 300쌍 자동 생성 | 4~6h |
| X2 | gemma4-26b QLoRA 학습 | M4 32GB에서 ~60분 학습, Ollama 등록 | 2~3h |
| X3 | Xcode 자동화 도구 | `xcode_build`, `xcode_run_sim` 전용 도구 등록 | 3~4h |
| X4 | 빌드→에러→수정 자동 루프 | 빌드 실패 시 에러 파싱→재수정 반복 (최대 5회) | 3~4h |

### 현실적 기대치

- 기본 26B: Swift 에러 분석 ~40% 성공률
- 파인튜닝 26B + 전용 도구: **~70-80% 성공률**
- 현재 결정: **보류** — iOS 개발은 Claude Code가 담당, Raphael은 웹/Python에 집중

---

## 영상 생성

### 로컬 (맥미니 M4 32GB 전용)

| # | 모델 | 요구사항 | 결과 |
|---|---|---|---|
| V1 | CogVideoX | 24GB+ | 저해상도 2-4초 클립, ~30분 |
| V2 | Wan2.1 | 24GB+ | 고품질 5초, 느림 |

### API (유료)

| # | 서비스 | 비용 | 품질 |
|---|---|---|---|
| V3 | Runway Gen-3 | ~$0.25/5초 | 최상 |
| V4 | Luma Dream Machine | ~$0.20/5초 | 상 |
| V5 | Kling AI | 무료 티어 있음 | 상 |

통합 구조: `generate_video` 도구 + 설정에 백엔드 선택 (이미지 생성과 동일 패턴)

---

## 데스크톱 Phase C 이후 (저우선)

| 항목 | 설명 |
|---|---|
| 캘린더 관리 뷰 | 일정 목록/추가/삭제 + 리마인더 알림 |
| 이메일 뷰어 | 받은편지함 리스트 + 요약 + 회신 |
| 플러그인 설치 관리자 | pip install/uninstall UI |
| Prometheus 메트릭 그래프 | 호출/latency 시각화 (현재 엔드포인트만) |
