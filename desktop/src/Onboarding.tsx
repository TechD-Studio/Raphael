import { useEffect, useRef, useState } from "react";
import { api, BASE } from "./api";

// 첫 실행 시 새 PC 가 모든 기능을 쓸 수 있도록 의존성 자동 설치를 안내/실행하는 모달.
// 단계: Ollama CLI → Ollama 서버 가동 → 기본 모델 pull → (선택) mflux 설치 → 완료.
// 사용자 터미널 작업 없이 GUI 만으로 처리하는 게 목표.

type OllamaState = {
  cli_installed: boolean;
  server_running: boolean;
  host: string;
  models_pulled: string[];
};

const DEFAULT_MODEL = "gemma4:e4b";

export function Onboarding({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<"intro" | "ollama" | "model" | "image" | "done">("intro");
  const [ollama, setOllama] = useState<OllamaState | null>(null);
  const [installing, setInstalling] = useState<string>("");
  const [busyMsg, setBusyMsg] = useState<string>("");
  const [pullProgress, setPullProgress] = useState<{ status: string; pct: number } | null>(null);
  const [error, setError] = useState<string>("");
  const pullCancelRef = useRef<AbortController | null>(null);

  async function refreshOllama() {
    try {
      const s = await api.setupOllamaStatus();
      setOllama(s);
    } catch (e: any) {
      setError(`Ollama 상태 조회 실패: ${e?.message || e}`);
    }
  }

  useEffect(() => {
    refreshOllama();
  }, []);

  async function installOllama() {
    setError("");
    setInstalling("ollama");
    setBusyMsg("Homebrew 로 ollama 설치 중... (수 분 소요)");
    try {
      const r = await api.setupOllamaInstall();
      if (!r.ok && r.method === "manual" && r.url) {
        // brew 미설치 — 공식 다운로드 페이지 열기
        try {
          const { openUrl } = await import("@tauri-apps/plugin-opener");
          await openUrl(r.url);
        } catch {}
        setError(
          (r.message || "") +
            "\n공식 페이지를 열었습니다. 다운로드 → 설치 후 이 창에 다시 돌아와 '상태 새로고침' 을 눌러주세요.",
        );
      } else if (!r.ok) {
        setError(`설치 실패: ${r.error || "원인 불명"}`);
      } else {
        setBusyMsg("설치 완료. 상태 확인 중...");
        await new Promise((r) => setTimeout(r, 1500));
        await refreshOllama();
      }
    } finally {
      setInstalling("");
      setBusyMsg("");
    }
  }

  async function pullModel(model: string = DEFAULT_MODEL) {
    setError("");
    setPullProgress({ status: "starting", pct: 0 });
    pullCancelRef.current = new AbortController();
    try {
      const resp = await fetch(`${BASE}/setup/ollama/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
        signal: pullCancelRef.current.signal,
      });
      if (!resp.body) throw new Error("응답 없음");
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.error) {
              setError(`pull 실패: ${ev.error}`);
              setPullProgress(null);
              return;
            }
            const total = ev.total || 0;
            const completed = ev.completed || 0;
            const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
            setPullProgress({ status: ev.status || "downloading", pct });
            if (ev.status === "done" || ev.status === "success") {
              setPullProgress({ status: "done", pct: 100 });
            }
          } catch {}
        }
      }
      await refreshOllama();
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(`pull 실패: ${e?.message || e}`);
    }
  }

  async function installMflux() {
    setError("");
    setInstalling("mflux");
    setBusyMsg("mflux 자동 설치 중... 첫 설치는 수 분 걸립니다 (300~500MB)");
    try {
      const r = await api.setupMfluxInstall();
      if (!r.ok) {
        setError(`mflux 설치 실패: ${r.error || "원인 불명"}`);
      } else {
        setBusyMsg("mflux 설치 완료!");
        await new Promise((r) => setTimeout(r, 1500));
        setStep("done");
      }
    } finally {
      setInstalling("");
      setTimeout(() => setBusyMsg(""), 2000);
    }
  }

  async function finish() {
    try {
      await api.setupMarkDone();
    } catch {}
    onClose();
  }

  const ollamaReady = ollama?.cli_installed && ollama?.server_running;
  const modelReady = ollama?.models_pulled?.some((m) => m.startsWith("gemma4")) ?? false;

  return (
    <div className="approval-overlay">
      <div className="approval-dialog" style={{ maxWidth: 580, width: "92%" }}>
        <div style={{ padding: 20 }}>
          <h2 style={{ marginTop: 0 }}>Raphael 첫 실행 설정</h2>
          <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
            새 컴퓨터에서 모든 기능을 쓸 수 있도록 필요한 외부 도구를 자동으로
            설치/설정합니다. 터미널 작업이 필요 없습니다.
          </p>

          {error && (
            <div className="err" style={{ whiteSpace: "pre-wrap", marginBottom: 12 }}>
              {error}
            </div>
          )}
          {busyMsg && (
            <div className="info-box" style={{ borderRadius: 6, padding: 10, marginBottom: 12, fontSize: 13 }}>
              {busyMsg}
            </div>
          )}

          {step === "intro" && (
            <div>
              <div style={{ marginBottom: 16, fontSize: 14 }}>
                다음 항목을 단계적으로 확인합니다:
                <ul style={{ marginTop: 8, paddingLeft: 20 }}>
                  <li>로컬 LLM (Ollama) — 필수</li>
                  <li>기본 모델 (gemma4:e4b, ~5GB) — 필수</li>
                  <li>이미지 생성 (mflux) — 선택</li>
                </ul>
              </div>
              <button className="primary" onClick={() => setStep("ollama")}>
                시작
              </button>
              <button style={{ marginLeft: 8 }} onClick={finish}>
                건너뛰기
              </button>
            </div>
          )}

          {step === "ollama" && (
            <div>
              <h3 style={{ marginTop: 0 }}>1. Ollama 설치 + 실행</h3>
              {ollama ? (
                <div style={{ fontSize: 13, marginBottom: 12 }}>
                  <div>
                    CLI 설치:{" "}
                    {ollama.cli_installed ? (
                      <span style={{ color: "#16a34a" }}>✓ 완료</span>
                    ) : (
                      <span style={{ color: "#dc2626" }}>✗ 미설치</span>
                    )}
                  </div>
                  <div>
                    서버 실행 ({ollama.host}):{" "}
                    {ollama.server_running ? (
                      <span style={{ color: "#16a34a" }}>✓ 동작 중</span>
                    ) : (
                      <span style={{ color: "#dc2626" }}>✗ 미실행</span>
                    )}
                  </div>
                </div>
              ) : (
                <div className="muted">상태 조회 중...</div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {!ollama?.cli_installed && (
                  <button className="primary" disabled={!!installing} onClick={installOllama}>
                    {installing === "ollama" ? "설치 중..." : "Ollama 자동 설치"}
                  </button>
                )}
                {ollama?.cli_installed && !ollama.server_running && (
                  <button
                    className="primary"
                    onClick={async () => {
                      try {
                        const { openUrl } = await import("@tauri-apps/plugin-opener");
                        await openUrl("ollama://");
                      } catch {}
                      setBusyMsg("Ollama 앱이 시작되도록 잠시 기다립니다...");
                      await new Promise((r) => setTimeout(r, 3500));
                      setBusyMsg("");
                      await refreshOllama();
                    }}
                  >
                    Ollama 시작
                  </button>
                )}
                <button onClick={refreshOllama}>상태 새로고침</button>
                {ollamaReady && (
                  <button className="primary" onClick={() => setStep("model")}>
                    다음 →
                  </button>
                )}
              </div>
            </div>
          )}

          {step === "model" && (
            <div>
              <h3 style={{ marginTop: 0 }}>2. 기본 모델 다운로드</h3>
              <div style={{ fontSize: 13, marginBottom: 12 }}>
                <div>
                  gemma4:e4b 모델 (~5GB):{" "}
                  {modelReady ? (
                    <span style={{ color: "#16a34a" }}>✓ 다운로드됨</span>
                  ) : (
                    <span style={{ color: "#dc2626" }}>✗ 미다운로드</span>
                  )}
                </div>
                {ollama?.models_pulled && ollama.models_pulled.length > 0 && (
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    설치된 모델: {ollama.models_pulled.join(", ")}
                  </div>
                )}
              </div>
              {pullProgress && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12 }}>
                    {pullProgress.status} — {pullProgress.pct}%
                  </div>
                  <div style={{ height: 6, background: "var(--surface)", borderRadius: 3, overflow: "hidden" }}>
                    <div
                      style={{
                        width: `${pullProgress.pct}%`,
                        height: "100%",
                        background: "var(--primary)",
                        transition: "width .2s",
                      }}
                    />
                  </div>
                </div>
              )}
              <div style={{ display: "flex", gap: 8 }}>
                {!modelReady && (
                  <button
                    className="primary"
                    disabled={!!pullProgress && pullProgress.status !== "done"}
                    onClick={() => pullModel(DEFAULT_MODEL)}
                  >
                    gemma4:e4b 다운로드
                  </button>
                )}
                <button onClick={refreshOllama}>새로고침</button>
                {modelReady && (
                  <button className="primary" onClick={() => setStep("image")}>
                    다음 →
                  </button>
                )}
              </div>
            </div>
          )}

          {step === "image" && (
            <div>
              <h3 style={{ marginTop: 0 }}>3. 이미지 생성 (선택)</h3>
              <p style={{ fontSize: 13, marginBottom: 12 }}>
                FLUX.1-schnell 로컬 이미지 생성을 쓰고 싶다면 mflux 를 자동 설치합니다.
                Settings 에서 HUGGINGFACE_TOKEN 을 추가로 입력해야 모델 다운로드가 됩니다.
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="primary"
                  disabled={!!installing}
                  onClick={installMflux}
                >
                  {installing === "mflux" ? "설치 중..." : "mflux 자동 설치"}
                </button>
                <button onClick={() => setStep("done")}>건너뛰기</button>
              </div>
            </div>
          )}

          {step === "done" && (
            <div>
              <h3 style={{ marginTop: 0 }}>완료</h3>
              <p style={{ fontSize: 13, marginBottom: 16 }}>
                기본 설정이 끝났습니다. 추가 설정(API 키, 원격 Ollama 호스트, MCP
                서버 등)은 우측 상단 ⚙ 에서 언제든 변경할 수 있습니다.
              </p>
              <button className="primary" onClick={finish}>
                Raphael 시작하기
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
