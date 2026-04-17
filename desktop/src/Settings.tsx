import { useEffect, useState } from "react";
import {
  api,
  type AgentDetail,
  type AgentInfo,
  type AgentUpsert,
  type ModelsInfo,
  type PoolServer,
  type ProfileFact,
  type SkillDetail,
  type SkillInfo,
  type SkillUpsert,
} from "./api";
import { confirmDialog } from "./confirm";

type Tab =
  | "agents"
  | "skills"
  | "models"
  | "server"
  | "rag";

export default function Settings({ onBack, onOllamaChange }: { onBack: () => void; onOllamaChange?: () => void }) {
  const [tab, setTab] = useState<Tab>("agents");
  const [modelsInfo, setModelsInfo] = useState<ModelsInfo | null>(null);

  useEffect(() => {
    api.models().then(setModelsInfo).catch(() => {});
  }, []);

  return (
    <div className="settings-root">
      <header className="settings-header">
        <button className="back-btn" onClick={onBack}>
          ← 돌아가기
        </button>
        <h2>설정</h2>
        <nav className="settings-tabs">
          <button
            className={tab === "agents" ? "active" : ""}
            onClick={() => setTab("agents")}
          >
            에이전트
          </button>
          <button
            className={tab === "skills" ? "active" : ""}
            onClick={() => setTab("skills")}
          >
            스킬
          </button>
          <button
            className={tab === "models" ? "active" : ""}
            onClick={() => setTab("models")}
          >
            모델
          </button>
          <button
            className={tab === "server" ? "active" : ""}
            onClick={() => setTab("server")}
          >
            서버
          </button>
          <button
            className={tab === "rag" ? "active" : ""}
            onClick={() => setTab("rag")}
          >
            RAG
          </button>
        </nav>
      </header>
      <main className="settings-body">
        {tab === "agents" && (
          <>
            <CustomInstructionsPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <MemoryPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <AgentsPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <ProfilePanel />
          </>
        )}
        {tab === "skills" && <SkillsPanel />}
        {tab === "models" && (
          <>
            <ModelsPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <RoutingPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <EscalationEditor available={modelsInfo?.available || []} />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <FineTunePanel />
          </>
        )}
        {tab === "server" && (
          <>
            <ServerPanel onSaved={onOllamaChange} />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #e7e9ef" }} />
            <PoolPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #e7e9ef" }} />
            <SecurityPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid var(--border)" }} />
            <ImageGenPanel />
          </>
        )}
        {tab === "rag" && <RagPanel />}
      </main>
    </div>
  );
}

function MemoryPanel() {
  const [context, setContext] = useState("");
  const [log, setLog] = useState("");
  const [patterns, setPatterns] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"context" | "log" | "patterns">("context");

  useEffect(() => {
    (async () => {
      try {
        const [c, l, p] = await Promise.all([
          api.projectContext(),
          api.dailyLog(),
          api.successPatterns(),
        ]);
        setContext(c.text);
        setLog(l.today || l.recent || "(기록 없음)");
        setPatterns(p.text || "(피드백 +1 기록 없음)");
      } catch {}
    })();
  }, []);

  async function saveContext() {
    setSaving(true);
    try {
      await api.saveProjectContext(context);
      setMsg("프로젝트 컨텍스트 저장됨");
    } catch {}
    finally { setSaving(false); }
  }

  return (
    <div className="agent-editor">
      <h3>기억 시스템</h3>
      <p className="muted">
        대화 내용에서 자동으로 작업 일지, 결정 사항, 성공 패턴을 추출하여
        다음 대화에 활용합니다.
      </p>
      {msg && <div className="ok-msg">{msg}</div>}

      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {(["context", "log", "patterns"] as const).map((t) => (
          <button
            key={t}
            className={tab === t ? "primary" : ""}
            onClick={() => setTab(t)}
            style={tab !== t ? { background: "var(--bg-card)", color: "var(--text-sub)", border: "1px solid var(--input-border)" } : {}}
          >
            {t === "context" ? "프로젝트 컨텍스트" : t === "log" ? "오늘 작업 일지" : "성공 패턴"}
          </button>
        ))}
      </div>

      {tab === "context" && (
        <>
          <textarea
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder={"# 프로젝트 컨텍스트\n\n- 목적: ...\n- 서버: ...\n- 현재 버전: ...\n\n## 주요 결정\n- [날짜] 결정 내용"}
            rows={10}
            style={{ width: "100%" }}
          />
          <div className="row">
            <button className="primary" onClick={saveContext} disabled={saving}>
              {saving ? "저장 중..." : "저장"}
            </button>
          </div>
          <p className="muted" style={{ marginTop: 6 }}>
            대화 중 결정 사항("~로 하겠습니다", "보류합니다" 등)은 자동 추출됩니다.
          </p>
        </>
      )}

      {tab === "log" && (
        <pre style={{
          background: "var(--panel-bg)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          padding: 12,
          fontSize: 12,
          whiteSpace: "pre-wrap",
          maxHeight: 400,
          overflowY: "auto",
        }}>
          {log}
        </pre>
      )}

      {tab === "patterns" && (
        <>
          <pre style={{
            background: "var(--panel-bg)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: 12,
            fontSize: 12,
            whiteSpace: "pre-wrap",
            maxHeight: 400,
            overflowY: "auto",
          }}>
            {patterns}
          </pre>
          <p className="muted" style={{ marginTop: 6 }}>
            채팅에서 👍 피드백을 주면 해당 응답 패턴이 자동 학습됩니다.
          </p>
        </>
      )}
    </div>
  );
}

function CustomInstructionsPanel() {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    let retries = 0;
    const load = () => {
      api.customInstructions().then((d) => setText(d.text)).catch(() => {
        if (retries++ < 5) setTimeout(load, 2000);
      });
    };
    load();
  }, []);

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      await api.saveCustomInstructions(text);
      setMsg("저장됨 — 다음 메시지부터 적용됩니다.");
    } catch {}
    finally { setSaving(false); }
  }

  return (
    <div className="agent-editor">
      <h3>글로벌 커스텀 지시문</h3>
      <p className="muted">
        모든 에이전트에 공통으로 적용되는 지시문입니다. 여기에 작성한 내용은
        시스템 프롬프트에 "최우선 준수" 태그와 함께 주입됩니다.
      </p>
      {msg && <div className="ok-msg">{msg}</div>}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"예시:\n- 항상 한국어로 답하라\n- 이미지 요청 시 generate_image를 반드시 호출하라\n- 답변은 500자 이내로 간결하게"}
        rows={6}
        style={{ width: "100%" }}
      />
      <div className="row">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "저장 중..." : "저장"}
        </button>
      </div>
    </div>
  );
}

function AgentsPanel() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string>("");
  const [recs, setRecs] = useState<{ name: string; reason: string }[]>([]);

  async function refresh() {
    try {
      setAgents(await api.agents());
      try {
        setRecs(await api.agentRecommendations(3));
      } catch {
        setRecs([]);
      }
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function enableRec(name: string) {
    try {
      await api.toggleAgent(name, true);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function toggle(name: string, active: boolean) {
    try {
      await api.toggleAgent(name, active);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function remove(name: string) {
    if (!(await confirmDialog(`"${name}" 에이전트를 삭제하시겠습니까?`, { danger: true, okLabel: "삭제" }))) return;
    try {
      await api.deleteAgent(name);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (editing !== null || creating) {
    return (
      <AgentEditor
        name={editing}
        onSaved={async () => {
          setEditing(null);
          setCreating(false);
          await refresh();
        }}
        onCancel={() => {
          setEditing(null);
          setCreating(false);
        }}
      />
    );
  }

  return (
    <div>
      <div className="panel-toolbar">
        <button className="primary" onClick={() => setCreating(true)}>
          + 새 에이전트
        </button>
      </div>
      {err && <div className="err">{err}</div>}
      {recs.length > 0 && (
        <div className="rec-box">
          <div className="rec-title">추천 (사용 이력 기반)</div>
          {recs.map((r) => (
            <div key={r.name} className="rec-item">
              <div>
                <code>{r.name}</code>{" "}
                <span className="muted">{r.reason}</span>
              </div>
              <button onClick={() => enableRec(r.name)}>활성화</button>
            </div>
          ))}
        </div>
      )}
      <table className="agent-table">
        <thead>
          <tr>
            <th>활성</th>
            <th>이름</th>
            <th>설명</th>
            <th>모델</th>
            <th>도구</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <tr key={a.name}>
              <td>
                <input
                  type="checkbox"
                  checked={a.active}
                  disabled={a.name === "main"}
                  onChange={(e) => toggle(a.name, e.target.checked)}
                />
              </td>
              <td>
                <code>{a.name}</code>
              </td>
              <td>{a.description}</td>
              <td>{a.model || <span className="muted">기본</span>}</td>
              <td>
                {Array.isArray(a.tools)
                  ? a.tools.length
                    ? a.tools.join(", ")
                    : "ALL"
                  : a.tools}
              </td>
              <td className="actions">
                <button onClick={() => setEditing(a.name)}>편집</button>
                <button
                  onClick={() => remove(a.name)}
                  disabled={a.name === "main"}
                >
                  삭제
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AgentEditor({
  name,
  onSaved,
  onCancel,
}: {
  name: string | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<AgentUpsert>({
    name: "",
    description: "",
    model: "",
    tools: [],
    system_prompt: "",
    default_enabled: false,
    active: true,
  });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (name === null) return;
    (async () => {
      try {
        const d: AgentDetail = await api.agent(name);
        setForm({
          name: d.name,
          description: d.description,
          model: d.model || "",
          tools: d.tools,
          system_prompt: d.system_prompt,
          default_enabled: d.default_enabled,
          active: d.active,
        });
      } catch (e: any) {
        setErr(e.message);
      }
    })();
  }, [name]);

  async function save() {
    setLoading(true);
    setErr("");
    try {
      await api.upsertAgent({
        ...form,
        model: form.model?.trim() || null,
      });
      onSaved();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  const isNew = name === null;
  const isMain = form.name === "main";

  return (
    <div className="agent-editor">
      <h3>{isNew ? "새 에이전트" : `${form.name} 편집`}</h3>
      {err && <div className="err">{err}</div>}
      <label>
        이름
        <input
          value={form.name}
          disabled={!isNew}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="예: translator"
        />
      </label>
      <label>
        설명
        <input
          value={form.description || ""}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="한 줄 설명"
        />
      </label>
      <label>
        모델 오버라이드 <span className="muted">(비워두면 라우터 기본)</span>
        <input
          value={form.model || ""}
          onChange={(e) => setForm({ ...form, model: e.target.value })}
          placeholder="예: gemma4-e4b"
        />
      </label>
      <label>
        도구 제한 <span className="muted">(쉼표 구분, 비워두면 전체 허용)</span>
        <input
          value={(form.tools || []).join(", ")}
          onChange={(e) =>
            setForm({
              ...form,
              tools: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
          placeholder="fetch_tool, web_search"
        />
      </label>
      <label>
        시스템 프롬프트
        <textarea
          value={form.system_prompt || ""}
          onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
          rows={14}
          placeholder="이 페르소나의 역할, 스타일, 규칙을 기술"
        />
      </label>
      <div className="row">
        <label className="inline">
          <input
            type="checkbox"
            checked={!!form.active}
            disabled={isMain}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
          />
          활성화
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={!!form.default_enabled}
            onChange={(e) =>
              setForm({ ...form, default_enabled: e.target.checked })
            }
          />
          기본 활성 (신규 사용자)
        </label>
      </div>
      <div className="row">
        <button className="primary" onClick={save} disabled={loading}>
          {loading ? "저장 중..." : "저장"}
        </button>
        <button onClick={onCancel} disabled={loading}>
          취소
        </button>
      </div>
    </div>
  );
}

function ModelsPanel() {
  const [info, setInfo] = useState<ModelsInfo | null>(null);
  const [installed, setInstalled] = useState<{
    host: string;
    models: string[];
    error?: string;
  } | null>(null);
  const [ollamaOk, setOllamaOk] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [pullName, setPullName] = useState("");
  const [pullMsg, setPullMsg] = useState("");

  async function refresh() {
    try {
      setInfo(await api.models());
      try {
        setInstalled(await api.installedModels());
      } catch {}
      try {
        const h = await api.healthPanel();
        setOllamaOk(h.ok);
      } catch {
        setOllamaOk(false);
      }
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function pull() {
    if (!pullName.trim()) return;
    setBusy(true);
    setPullMsg("");
    try {
      await api.pullModel(pullName);
      setPullMsg(`${pullName} pull 완료.`);
      setPullName("");
      await refresh();
    } catch (e: any) {
      setPullMsg(`실패: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function choose(key: string) {
    setBusy(true);
    setErr("");
    try {
      await api.useModel(key);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!info)
    return <div className="muted">{err || "모델 정보 불러오는 중..."}</div>;

  return (
    <div>
      <p>
        현재 모델: <code>{info.current}</code>
      </p>
      {err && <div className="err">{err}</div>}
      {!ollamaOk && (
        <div className="err" style={{ marginBottom: 12 }}>
          Ollama 서버에 연결할 수 없습니다. Ollama 모델은 사용 불가 상태입니다.
        </div>
      )}
      <ul className="model-list">
        {info.available.map((k) => {
          const isClaude = k.startsWith("claude");
          const isAvailable = isClaude || ollamaOk;
          return (
            <li key={k} style={{ opacity: isAvailable ? 1 : 0.4 }}>
              <code>{k}</code>
              {!isAvailable && (
                <span className="badge" style={{ background: "var(--err-bg)", color: "var(--err-text)" }}>
                  연결 실패
                </span>
              )}
              {isAvailable && k === info.current && (
                <span className="badge">활성</span>
              )}
              {isAvailable && k !== info.current && (
                <button disabled={busy} onClick={() => choose(k)}>
                  사용
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <h4 style={{ marginTop: 24, marginBottom: 8 }}>
        Ollama 서버 설치 모델
      </h4>
      {installed?.error && <div className="err">{installed.error}</div>}
      {installed && installed.models.length === 0 && !installed.error && (
        <div className="muted">설치된 모델 없음 ({installed.host})</div>
      )}
      {installed && installed.models.length > 0 && (
        <div className="muted" style={{ marginBottom: 8 }}>
          {installed.host} —{" "}
          {installed.models.map((m) => (
            <code key={m} style={{ marginRight: 6, fontSize: 11 }}>
              {m}
            </code>
          ))}
        </div>
      )}
      <div className="row">
        <input
          placeholder="새 모델 pull (예: gemma3:vision)"
          value={pullName}
          onChange={(e) => setPullName(e.target.value)}
          style={{
            flex: 1,
            border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)",
            borderRadius: 6,
            padding: "6px 10px",
          }}
        />
        <button onClick={pull} disabled={busy || !pullName.trim()}>
          {busy ? "Pull 중..." : "Pull"}
        </button>
      </div>
      {pullMsg && (
        <div
          className={pullMsg.startsWith("실패") ? "err" : "ok-msg"}
          style={{ marginTop: 8 }}
        >
          {pullMsg}
        </div>
      )}
    </div>
  );
}

function FineTunePanel() {
  const [deps, setDeps] = useState<{ mlx_lm: boolean; llama_cpp: boolean; ollama: boolean } | null>(null);
  const [models, setModels] = useState<{ name: string; base_model: string; iters: number; created: string }[]>([]);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [prepResult, setPrepResult] = useState<{ total_pairs: number; train: number; valid: number } | null>(null);
  const [trainResult, setTrainResult] = useState<{ adapter_name: string } | null>(null);
  const [vaultPath, setVaultPath] = useState("");
  const [baseModel, setBaseModel] = useState("mlx-community/gemma-4-E2B-it-4bit");
  const [iters, setIters] = useState(600);

  useEffect(() => {
    (async () => {
      try {
        const [d, m] = await Promise.all([api.finetuneCheck(), api.finetuneModels()]);
        setDeps(d);
        setModels(m);
        const ragCfg = await api.ragStatus().catch(() => null);
        if (ragCfg?.vault_path) setVaultPath(ragCfg.vault_path);
      } catch {}
    })();
  }, []);

  async function prepare() {
    if (!vaultPath.trim()) { setErr("볼트 경로를 입력하세요"); return; }
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await api.finetunePrepare(vaultPath);
      if (r.ok) {
        setPrepResult({ total_pairs: r.total_pairs!, train: r.train!, valid: r.valid! });
        setMsg(`${r.total_pairs}쌍 변환 완료 (train: ${r.train}, valid: ${r.valid})`);
        setStep(2);
      } else { setErr(r.error || "변환 실패"); }
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function train() {
    setBusy(true); setErr(""); setMsg("학습 중... (수 분 ~ 수십 분 소요)");
    try {
      const r = await api.finetuneTrain({ base_model: baseModel, iters, batch_size: 2, lora_layers: 16 });
      if (r.ok) {
        setTrainResult({ adapter_name: r.adapter_name! });
        setMsg(`학습 완료: ${r.adapter_name}`);
        setStep(3);
      } else { setErr(r.error || "학습 실패"); setMsg(""); }
    } catch (e: any) { setErr(e.message); setMsg(""); }
    finally { setBusy(false); }
  }

  async function build() {
    if (!trainResult) return;
    setBusy(true); setErr(""); setMsg("모델 빌드 중...");
    try {
      const r = await api.finetuneBuild(trainResult.adapter_name);
      if (r.ok) {
        setMsg(`Ollama에 '${r.model_name}' 등록 완료!`);
        setModels(await api.finetuneModels());
        setStep(1); setTrainResult(null); setPrepResult(null);
      } else { setErr(`${r.stage || ""} 실패: ${r.error}`); setMsg(""); }
    } catch (e: any) { setErr(e.message); setMsg(""); }
    finally { setBusy(false); }
  }

  async function remove(name: string) {
    if (!(await confirmDialog(`${name} 어댑터를 삭제하시겠습니까?`, { danger: true, okLabel: "삭제" }))) return;
    try {
      await api.finetuneDelete(name);
      setModels(await api.finetuneModels());
    } catch (e: any) { setErr(e.message); }
  }

  return (
    <div className="agent-editor">
      <h3>파인튜닝 (QLoRA)</h3>
      <p className="muted">
        옵시디언 노트로 gemma4를 도메인 특화 학습합니다. mlx-lm 필요.
      </p>

      {deps && (
        <div className="info-box" style={{ borderRadius: 6, padding: 10, marginBottom: 12, fontSize: 12 }}>
          <span style={{ color: deps.mlx_lm ? "#16a34a" : "#dc2626" }}>
            {deps.mlx_lm ? "✓" : "✗"} mlx-lm
          </span>{" · "}
          <span style={{ color: deps.llama_cpp ? "#16a34a" : "#dc2626" }}>
            {deps.llama_cpp ? "✓" : "✗"} llama.cpp
          </span>{" · "}
          <span style={{ color: deps.ollama ? "#16a34a" : "#dc2626" }}>
            {deps.ollama ? "✓" : "✗"} ollama
          </span>
        </div>
      )}

      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {[1, 2, 3].map((s) => (
          <div
            key={s}
            style={{
              flex: 1,
              textAlign: "center",
              padding: "6px 0",
              borderBottom: `2px solid ${step >= s ? "var(--primary)" : "var(--border)"}`,
              color: step >= s ? "var(--text)" : "var(--text-muted)",
              fontSize: 12,
              fontWeight: step === s ? 600 : 400,
            }}
          >
            {s === 1 ? "데이터 변환" : s === 2 ? "QLoRA 학습" : "모델 빌드"}
          </div>
        ))}
      </div>

      {step === 1 && (
        <>
          <label>
            옵시디언 볼트 경로
            <input
              value={vaultPath}
              onChange={(e) => setVaultPath(e.target.value)}
              placeholder="/Users/.../Obsidian Vault"
            />
          </label>
          <div className="row">
            <button className="primary" onClick={prepare} disabled={busy}>
              {busy ? "변환 중..." : "데이터 변환"}
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          {prepResult && (
            <div className="muted" style={{ marginBottom: 8 }}>
              학습 데이터: {prepResult.total_pairs}쌍 (train: {prepResult.train}, valid: {prepResult.valid})
            </div>
          )}
          <label>
            베이스 모델
            <select value={baseModel} onChange={(e) => setBaseModel(e.target.value)}>
              <option value="mlx-community/gemma-4-E2B-it-4bit">gemma4-e2b (5B, 추천)</option>
              <option value="mlx-community/gemma-4-E4B-it-4bit">gemma4-e4b (9B, 메모리 주의)</option>
            </select>
          </label>
          <label>
            반복 횟수
            <input type="number" value={iters} onChange={(e) => setIters(parseInt(e.target.value) || 600)} />
          </label>
          <div className="row">
            <button className="primary" onClick={train} disabled={busy}>
              {busy ? "학습 중..." : "학습 시작"}
            </button>
            <button onClick={() => setStep(1)} disabled={busy}>이전</button>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <div className="muted" style={{ marginBottom: 8 }}>
            어댑터: {trainResult?.adapter_name} — fuse → GGUF → Ollama 등록
          </div>
          <div className="row">
            <button className="primary" onClick={build} disabled={busy}>
              {busy ? "빌드 중..." : "모델 빌드 + Ollama 등록"}
            </button>
            <button onClick={() => setStep(2)} disabled={busy}>이전</button>
          </div>
        </>
      )}

      {models.length > 0 && (
        <>
          <h4 style={{ marginTop: 20 }}>등록된 파인튜닝 모델</h4>
          <table className="agent-table">
            <thead>
              <tr>
                <th>이름</th>
                <th>베이스</th>
                <th>반복</th>
                <th>생성일</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.name}>
                  <td><code>{m.name}</code></td>
                  <td>{m.base_model.split("/").pop()}</td>
                  <td>{m.iters}</td>
                  <td>{m.created}</td>
                  <td><button onClick={() => remove(m.name)}>삭제</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function EscalationEditor({ available }: { available: string[] }) {
  const [ladder, setLadder] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.escalation().then((d) => {
      setLadder(d.ladder);
      setEnabled(d.ladder.length > 0);
    }).catch(() => {});
  }, []);

  function move(i: number, dir: -1 | 1) {
    const next = [...ladder];
    const j = i + dir;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setLadder(next);
  }

  function add(key: string) {
    if (!ladder.includes(key)) setLadder([...ladder, key]);
  }

  function remove(i: number) {
    setLadder(ladder.filter((_, idx) => idx !== i));
  }

  async function save() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await api.saveEscalation(enabled ? ladder : []);
      setMsg(enabled ? "저장됨" : "에스컬레이션 비활성화됨");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  const unused = available.filter((k) => !ladder.includes(k));

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <h4 style={{ margin: 0 }}>에스컬레이션 사다리</h4>
        <label className="inline" style={{ marginLeft: "auto", fontSize: 12 }}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          {enabled ? "ON" : "OFF"}
        </label>
      </div>
      <p className="muted">
        {enabled
          ? "gemma4가 빈 응답을 반환하면 아래 순서대로 자동 전환합니다."
          : "에스컬레이션이 비활성화되어 있습니다. 현재 모델만 사용합니다."}
      </p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
        {ladder.map((k, i) => (
          <div
            key={k}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 10px",
              background: "var(--panel-bg)",
              border: "1px solid var(--border)",
              borderRadius: 6,
            }}
          >
            <span style={{ color: "var(--text-muted)", fontSize: 12, width: 20 }}>
              {i + 1}
            </span>
            <code style={{ flex: 1 }}>{k}</code>
            {k.startsWith("claude") && (
              <span style={{ fontSize: 10, color: "var(--primary)", background: "var(--tag-bg)", padding: "1px 6px", borderRadius: 3 }}>
                구독
              </span>
            )}
            <button onClick={() => move(i, -1)} disabled={i === 0} style={{ fontSize: 11, padding: "2px 6px" }}>
              ▲
            </button>
            <button onClick={() => move(i, 1)} disabled={i === ladder.length - 1} style={{ fontSize: 11, padding: "2px 6px" }}>
              ▼
            </button>
            <button onClick={() => remove(i)} style={{ fontSize: 11, padding: "2px 6px", color: "#dc2626" }}>
              ✕
            </button>
          </div>
        ))}
      </div>
      {unused.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          {unused.map((k) => (
            <button
              key={k}
              onClick={() => add(k)}
              style={{ fontSize: 12 }}
            >
              + {k}
            </button>
          ))}
        </div>
      )}
      <div className="row">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "저장 중..." : "사다리 저장"}
        </button>
      </div>
    </div>
  );
}

function SkillsPanel() {
  const [list, setList] = useState<SkillInfo[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState("");

  async function refresh() {
    try {
      setList(await api.skills());
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function remove(name: string) {
    if (!(await confirmDialog(`${name} 삭제?`, { danger: true, okLabel: "삭제" }))) return;
    try {
      await api.deleteSkill(name);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (editing !== null || creating) {
    return (
      <SkillEditor
        name={editing}
        onSaved={async () => {
          setEditing(null);
          setCreating(false);
          await refresh();
        }}
        onCancel={() => {
          setEditing(null);
          setCreating(false);
        }}
      />
    );
  }

  return (
    <div>
      <div className="panel-toolbar">
        <button className="primary" onClick={() => setCreating(true)}>
          + 새 스킬
        </button>
      </div>
      {err && <div className="err">{err}</div>}
      <p className="muted">
        스킬은 <code>ask --skill X</code> 또는 채팅 입력 시 선택하여
        system_prompt에 임시 주입하는 재사용 가능한 지시사항입니다.
      </p>
      <table className="agent-table">
        <thead>
          <tr>
            <th>이름</th>
            <th>설명</th>
            <th>기본 에이전트</th>
            <th>태그</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                스킬 없음
              </td>
            </tr>
          )}
          {list.map((s) => (
            <tr key={s.name}>
              <td>
                <code>{s.name}</code>
              </td>
              <td>{s.description}</td>
              <td>{s.agent || <span className="muted">(무관)</span>}</td>
              <td style={{ fontSize: 11, color: "#6b7280" }}>
                {s.tags.join(", ")}
              </td>
              <td className="actions">
                <button onClick={() => setEditing(s.name)}>편집</button>
                <button onClick={() => remove(s.name)}>삭제</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SkillEditor({
  name,
  onSaved,
  onCancel,
}: {
  name: string | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<SkillUpsert>({
    name: "",
    description: "",
    prompt: "",
    agent: "",
    tags: [],
  });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [agents, setAgents] = useState<string[]>([]);

  useEffect(() => {
    api.agents().then((a) => setAgents(a.map((x) => x.name))).catch(() => {});
    if (name === null) return;
    (async () => {
      try {
        const d: SkillDetail = await api.skill(name);
        setForm({
          name: d.name,
          description: d.description,
          prompt: d.prompt,
          agent: d.agent,
          tags: d.tags,
        });
      } catch (e: any) {
        setErr(e.message);
      }
    })();
  }, [name]);

  async function save() {
    setLoading(true);
    setErr("");
    try {
      await api.upsertSkill(form);
      onSaved();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  const isNew = name === null;
  return (
    <div className="agent-editor">
      <h3>{isNew ? "새 스킬" : `${form.name} 편집`}</h3>
      {err && <div className="err">{err}</div>}
      <label>
        이름
        <input
          value={form.name}
          disabled={!isNew}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="예: summarize-ko"
        />
      </label>
      <label>
        설명
        <input
          value={form.description || ""}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
      </label>
      <label>
        기본 에이전트 <span className="muted">(선택 — 자동 적용 조건)</span>
        <select
          value={form.agent || ""}
          onChange={(e) => setForm({ ...form, agent: e.target.value })}
        >
          <option value="">(무관)</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>
      <label>
        태그 (쉼표 구분)
        <input
          value={(form.tags || []).join(", ")}
          onChange={(e) =>
            setForm({
              ...form,
              tags: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      </label>
      <label>
        프롬프트 본문
        <textarea
          value={form.prompt}
          onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          rows={14}
          placeholder="에이전트에 추가로 주입할 지시사항"
        />
      </label>
      <div className="row">
        <button className="primary" onClick={save} disabled={loading}>
          {loading ? "저장 중..." : "저장"}
        </button>
        <button onClick={onCancel} disabled={loading}>
          취소
        </button>
      </div>
    </div>
  );
}

// 상황별 슬롯 정의 (web UI와 동일)
interface Slot {
  id: string;
  label: string;
  hint: string;
  match: Record<string, any>; // match 조건 (nested)
  prefer_agent?: string;      // 선호 에이전트 (slot 고유 — 사용자 미선택)
}

const ROUTING_SLOTS: Slot[] = [
  {
    id: "short",
    label: "짧은 입력 (60 토큰 미만)",
    hint: "빠른 응답용 소형 모델",
    match: { token_estimate_lt: 60 },
  },
  {
    id: "review",
    label: "리뷰/분석/디버깅 키워드 포함",
    hint: "로직/품질 중요 — 강한 모델",
    match: {
      contains_any: ["리뷰", "검토", "분석", "디버그", "debug", "review", "analysis"],
    },
  },
  {
    id: "project",
    label: "큰 작업 (만들/구현/프로젝트 키워드 + 긴 입력) + planner",
    hint: "기획 + 위임 필요",
    match: {
      contains_any: ["만들", "구현", "프로젝트", "project", "build", "create"],
      token_estimate_gt: 80,
    },
    prefer_agent: "planner",
  },
  {
    id: "long_chat",
    label: "긴 대화 (10턴 이상, coding 에이전트)",
    hint: "맥락 유지 중요",
    match: { agent: "coding", min_messages: 10 },
  },
  {
    id: "default",
    label: "기본값 (위 조건 모두 미해당)",
    hint: "균형형 기본 모델",
    match: { default: true },
  },
];

function matchEquals(a: Record<string, any>, b: Record<string, any>): boolean {
  const ak = Object.keys(a).sort();
  const bk = Object.keys(b).sort();
  if (ak.length !== bk.length) return false;
  for (const k of ak) {
    const av = a[k];
    const bv = b[k];
    if (Array.isArray(av) && Array.isArray(bv)) {
      if (av.length !== bv.length) return false;
      if (!av.every((x, i) => x === bv[i])) return false;
    } else if (av !== bv) {
      return false;
    }
  }
  return true;
}

function RoutingPanel() {
  const [strategy, setStrategy] = useState<"auto" | "manual">("manual");
  const [slotModels, setSlotModels] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<string[]>([]);

  async function reload() {
    try {
      const [c, m] = await Promise.all([api.routingSettings(), api.models()]);
      setStrategy((c.strategy as any) || "manual");
      setModels(m.available);
      const byId: Record<string, string> = {};
      for (const slot of ROUTING_SLOTS) {
        const found = c.rules.find((r: any) =>
          matchEquals((r.match || {}) as any, slot.match),
        );
        byId[slot.id] = (found?.prefer_model || "") as string;
      }
      setSlotModels(byId);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function save() {
    setSaving(true);
    setErr("");
    setMsg("");
    const rules: any[] = [];
    for (const slot of ROUTING_SLOTS) {
      const m = (slotModels[slot.id] || "").trim();
      if (!m) continue;
      const rule: any = { match: { ...slot.match }, prefer_model: m };
      if (slot.prefer_agent) rule.prefer_agent = slot.prefer_agent;
      rule.name = slot.id;
      rules.push(rule);
    }
    try {
      await api.saveRoutingSettings({ strategy, rules });
      setMsg(`저장 완료 — 활성 규칙 ${rules.length}개`);
      await reload();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) return <div className="muted">불러오는 중...</div>;

  return (
    <div>
      <p className="muted">
        각 상황에 어떤 모델을 쓸지 선택하세요. auto로 두면 매 호출마다
        위→아래로 평가, manual이면 현재 선택된 모델만 사용합니다.
      </p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      <div className="row" style={{ marginBottom: 16 }}>
        <label className="inline">
          <input
            type="radio"
            name="strategy"
            checked={strategy === "manual"}
            onChange={() => setStrategy("manual")}
          />
          manual
        </label>
        <label className="inline">
          <input
            type="radio"
            name="strategy"
            checked={strategy === "auto"}
            onChange={() => setStrategy("auto")}
          />
          auto
        </label>
      </div>

      {ROUTING_SLOTS.map((slot) => (
        <div key={slot.id} className="slot-card">
          <div className="slot-head">
            <div>
              <div className="slot-label">{slot.label}</div>
              <div className="slot-hint">{slot.hint}</div>
            </div>
            <select
              value={slotModels[slot.id] || ""}
              onChange={(e) =>
                setSlotModels({
                  ...slotModels,
                  [slot.id]: e.target.value,
                })
              }
            >
              <option value="">(비활성)</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      ))}

      <div className="row" style={{ marginTop: 16 }}>
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "저장 중..." : "저장"}
        </button>
        <button onClick={reload} disabled={saving}>
          다시 불러오기
        </button>
        <button onClick={applyRecommended} disabled={saving}>
          추천 불러오기
        </button>
      </div>
    </div>
  );

  function applyRecommended() {
    const pick = (keywords: string[], fallback: string) => {
      for (const kw of keywords) {
        const found = models.find((m) => m.includes(kw));
        if (found) return found;
      }
      return models.includes(fallback) ? fallback : models[0] || "";
    };
    setStrategy("auto");
    setSlotModels({
      short: pick(["e2b", "haiku"], "gemma4-e2b"),
      review: pick(["sonnet", "26b", "e4b"], "gemma4-e4b"),
      project: pick(["opus", "sonnet", "26b"], "gemma4-26b"),
      long_chat: pick(["26b", "e4b", "sonnet"], "gemma4-e4b"),
      default: pick(["e4b"], "gemma4-e4b"),
    });
    setMsg("추천 매핑이 적용되었습니다. '저장'을 눌러 반영하세요.");
  }
}

function RagPanel() {
  const [status, setStatus] = useState<{
    vault_path: string;
    doc_count: number;
    embedding_model: string;
    chroma_db_path: string;
    error?: string;
  } | null>(null);
  const [vault, setVault] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const s = await api.ragStatus();
      setStatus(s);
      setVault(s.vault_path || "");
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function saveVault() {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api.setRagVault(vault);
      setMsg("볼트 경로 저장됨.");
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function sync() {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.ragSync();
      setMsg(
        `sync 완료: +${r.added} new, ~${r.updated} updated, -${r.deleted} deleted, ${r.unchanged} unchanged`,
      );
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function reindex() {
    if (!(await confirmDialog("전체 재인덱싱 (시간 소요). 계속?"))) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.ragReindex();
      setMsg(`${r.indexed}개 청크 인덱싱됨.`);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="agent-editor">
      <h3>Obsidian RAG</h3>
      <p className="muted">
        옵시디언 볼트의 마크다운 노트를 ChromaDB에 인덱싱하여 research 에이전트가
        참조합니다.
      </p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}
      {status && (
        <div
          className="info-box"
          style={{
            borderRadius: 6,
            padding: 10,
            marginBottom: 12,
            fontSize: 13,
          }}
        >
          <div>
            <b>인덱싱된 청크:</b> {status.doc_count.toLocaleString()}
          </div>
          <div>
            <b>임베딩 모델:</b>{" "}
            <code>{status.embedding_model || "(미지정)"}</code>
          </div>
          <div>
            <b>ChromaDB 경로:</b>{" "}
            <code style={{ fontSize: 11 }}>{status.chroma_db_path}</code>
          </div>
          {status.error && (
            <div className="err" style={{ marginTop: 6 }}>
              {status.error}
            </div>
          )}
        </div>
      )}
      <label>
        볼트 경로
        <input
          value={vault}
          onChange={(e) => setVault(e.target.value)}
          placeholder="예: /Users/dh/Documents/Obsidian Vault"
        />
      </label>
      <div className="row">
        <button className="primary" onClick={saveVault} disabled={busy}>
          경로 저장
        </button>
        <button onClick={sync} disabled={busy}>
          {busy ? "진행 중..." : "Sync (증분)"}
        </button>
        <button onClick={reindex} disabled={busy}>
          전체 재인덱싱
        </button>
      </div>
    </div>
  );
}

function SecurityPanel() {
  const [paths, setPaths] = useState<string[]>([]);
  const [newPath, setNewPath] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const [secrets, setSecrets] = useState<
    { key: string; source: string; in_keychain: boolean }[]
  >([]);
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");

  async function refresh() {
    try {
      const [p, s] = await Promise.all([api.allowedPaths(), api.listSecrets()]);
      setPaths(p.allowed_paths);
      setSecrets(s.keys);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function savePaths() {
    try {
      await api.saveAllowedPaths(paths);
      setMsg("저장됨.");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  function addPath() {
    if (!newPath.trim()) return;
    setPaths([...paths, newPath.trim()]);
    setNewPath("");
  }

  function removePath(i: number) {
    setPaths(paths.filter((_, idx) => idx !== i));
  }

  async function saveSecret() {
    if (!newKey.trim()) return;
    try {
      await api.setSecret(newKey.trim(), newVal);
      setMsg(`${newKey} 저장됨.`);
      setNewKey("");
      setNewVal("");
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function delSecret(k: string) {
    if (!(await confirmDialog(`시크릿 ${k} 삭제?`, { danger: true, okLabel: "삭제" }))) return;
    try {
      await api.deleteSecret(k);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (!loaded) return <div className="muted">불러오는 중...</div>;

  return (
    <div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      <h3 style={{ marginTop: 0 }}>허용 경로 (Allowed Paths)</h3>
      <p className="muted">
        파일 도구(read_file/write_file/...)가 접근 가능한 경로. 비우면 홈 +
        /tmp + cwd 자동 허용.
      </p>
      <ul className="model-list" style={{ marginBottom: 12 }}>
        {paths.map((p, i) => (
          <li key={i}>
            <code>{p}</code>
            <button
              style={{ marginLeft: "auto" }}
              onClick={() => removePath(i)}
            >
              삭제
            </button>
          </li>
        ))}
        {paths.length === 0 && (
          <li>
            <span className="muted">(빈 리스트 — 기본값 적용)</span>
          </li>
        )}
      </ul>
      <div className="row" style={{ marginBottom: 16 }}>
        <input
          placeholder="예: ~/Projects"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addPath()}
          style={{
            flex: 1,
            border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)",
            borderRadius: 6,
            padding: "6px 10px",
          }}
        />
        <button onClick={addPath}>추가</button>
        <button className="primary" onClick={savePaths}>
          저장
        </button>
      </div>

      <h3>Keychain 시크릿</h3>
      <p className="muted">
        OS Keychain(macOS) / Secret Service(Linux) / Credential Manager(Windows)
        에 저장됩니다. 키 목록은 <code>.env</code> 기반 — Keychain은 목록
        조회를 지원하지 않습니다.
      </p>
      <table className="agent-table" style={{ marginBottom: 12 }}>
        <thead>
          <tr>
            <th>키</th>
            <th>.env 출처</th>
            <th>Keychain</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {secrets.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                저장된 시크릿 없음
              </td>
            </tr>
          )}
          {secrets.map((s) => (
            <tr key={s.key + s.source}>
              <td>
                <code>{s.key}</code>
              </td>
              <td>{s.source}</td>
              <td>
                {s.in_keychain ? (
                  <span
                    className="badge"
                    style={{ background: "#dcfce7", color: "#166534" }}
                  >
                    있음
                  </span>
                ) : (
                  <span className="muted">없음</span>
                )}
              </td>
              <td className="actions">
                <button onClick={() => delSecret(s.key)}>삭제</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row">
        <input
          placeholder="키 (예: TELEGRAM_BOT_TOKEN)"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          style={{
            border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)",
            borderRadius: 6,
            padding: "6px 10px",
            width: 260,
          }}
        />
        <input
          type="password"
          placeholder="값"
          value={newVal}
          onChange={(e) => setNewVal(e.target.value)}
          style={{
            flex: 1,
            border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)",
            borderRadius: 6,
            padding: "6px 10px",
          }}
        />
        <button className="primary" onClick={saveSecret}>
          저장
        </button>
      </div>
    </div>
  );
}

function FactRow({ fact, onDelete }: { fact: ProfileFact; onDelete: () => void }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        style={{ cursor: "pointer" }}
      >
        <td style={{ maxWidth: 300 }}>
          <span style={{ marginRight: 6, fontSize: 10, color: "var(--text-muted)" }}>
            {expanded ? "▼" : "▶"}
          </span>
          {fact.text.length > 60 ? fact.text.slice(0, 60) + "..." : fact.text}
        </td>
        <td style={{ fontSize: 11 }}>{fact.source}</td>
        <td style={{ fontSize: 11 }}>{fact.added.replace("T", " ")}</td>
        <td className="actions">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
          >
            삭제
          </button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td
            colSpan={4}
            style={{
              background: "var(--panel-bg)",
              padding: "10px 14px",
              fontSize: 13,
              whiteSpace: "pre-wrap",
              lineHeight: 1.5,
              borderBottom: "1px solid var(--border)",
            }}
          >
            {fact.text}
          </td>
        </tr>
      )}
    </>
  );
}

function ProfilePanel() {
  const [facts, setFacts] = useState<ProfileFact[]>([]);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");

  async function refresh() {
    try {
      const r = await api.profile();
      setFacts(r.facts);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function add() {
    if (!text.trim()) return;
    try {
      await api.addFact(text);
      setText("");
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function del(id: string) {
    if (!(await confirmDialog("이 fact를 삭제하시겠습니까?", { danger: true, okLabel: "삭제" }))) return;
    try {
      await api.deleteFact(id);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function clearAll() {
    if (!(await confirmDialog("모든 fact를 삭제합니다. 계속?", { danger: true, okLabel: "모두 삭제" }))) return;
    try {
      await api.clearProfile();
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <div className="agent-editor">
      <h3>사용자 프로필 (자동 주입)</h3>
      <p className="muted">
        아래 정보가 모든 에이전트의 시스템 메시지에 자동 주입됩니다.
        채팅에서 "내 이름은 dh야" → 자동 저장. 직접 추가/삭제도 가능합니다.
      </p>
      {err && <div className="err">{err}</div>}
      <table className="agent-table">
        <thead>
          <tr>
            <th>내용</th>
            <th>출처</th>
            <th>추가 시각</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {facts.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                저장된 fact 없음
              </td>
            </tr>
          )}
          {facts.map((f) => (
            <FactRow key={f.id} fact={f} onDelete={() => del(f.id)} />
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 8 }}>
        <input
          placeholder="예: 사용자는 한국어 응답 선호"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          style={{
            flex: 1,
            border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)",
            borderRadius: 6,
            padding: "6px 10px",
          }}
        />
        <button className="primary" onClick={add}>
          추가
        </button>
        {facts.length > 0 && <button onClick={clearAll}>전체 삭제</button>}
      </div>
    </div>
  );
}

function PoolPanel() {
  const [servers, setServers] = useState<PoolServer[]>([]);
  const [health, setHealth] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [loaded, setLoaded] = useState(false);

  async function refresh() {
    try {
      const r = await api.poolStatus();
      setServers(r.configured as PoolServer[]);
      setHealth(r.health);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function update(i: number, patch: Partial<PoolServer>) {
    const next = [...servers];
    next[i] = { ...next[i], ...patch };
    setServers(next);
  }

  function add() {
    setServers([
      ...servers,
      {
        name: `server-${servers.length + 1}`,
        host: "localhost",
        port: 11434,
        weight: 1,
        models: [],
        timeout: 120,
      },
    ]);
  }

  function remove(i: number) {
    setServers(servers.filter((_, idx) => idx !== i));
  }

  async function save() {
    try {
      await api.savePool(servers);
      setMsg("저장됨. 라우터 재초기화.");
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (!loaded) return <div className="muted">불러오는 중...</div>;

  return (
    <div>
      <p className="muted">
        다중 Ollama 서버를 등록해 모델별로 라우팅합니다. 비어있으면 단일 서버
        모드 (서버 탭).
      </p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      {servers.map((srv, i) => {
        const h = health[i];
        return (
          <div key={i} className="rule-card">
            <div className="rule-head">
              <input
                value={srv.name}
                onChange={(e) => update(i, { name: e.target.value })}
                style={{
                  border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)",
                  borderRadius: 4,
                  padding: "3px 8px",
                  width: 140,
                }}
              />
              {h && h.health && (
                <span
                  className="badge"
                  style={{
                    background: h.health.ok ? "#dcfce7" : "#fee2e2",
                    color: h.health.ok ? "#166534" : "#991b1b",
                  }}
                >
                  {h.health.ok ? "online" : "offline"}
                </span>
              )}
              <div style={{ flex: 1 }} />
              <button onClick={() => remove(i)}>삭제</button>
            </div>
            <div className="rule-body">
              <div className="rule-col">
                <label>
                  Host
                  <input
                    value={srv.host}
                    onChange={(e) => update(i, { host: e.target.value })}
                  />
                </label>
                <label>
                  Port
                  <input
                    type="number"
                    value={srv.port}
                    onChange={(e) =>
                      update(i, { port: parseInt(e.target.value) || 11434 })
                    }
                  />
                </label>
                <label>
                  Weight
                  <input
                    type="number"
                    value={srv.weight}
                    onChange={(e) =>
                      update(i, { weight: parseInt(e.target.value) || 1 })
                    }
                  />
                </label>
              </div>
              <div className="rule-col">
                <label>
                  보유 모델 (쉼표 구분)
                  <input
                    value={srv.models.join(", ")}
                    onChange={(e) =>
                      update(i, {
                        models: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder="gemma4:e4b, gemma4:26b"
                  />
                </label>
                <label>
                  Timeout (s)
                  <input
                    type="number"
                    value={srv.timeout}
                    onChange={(e) =>
                      update(i, { timeout: parseInt(e.target.value) || 120 })
                    }
                  />
                </label>
              </div>
            </div>
          </div>
        );
      })}

      <div className="row">
        <button onClick={add}>+ 서버 추가</button>
        <button className="primary" onClick={save}>
          저장
        </button>
      </div>
    </div>
  );
}

function ServerPanel({ onSaved }: { onSaved?: () => void }) {
  const [form, setForm] = useState<{
    host: string;
    port: number;
    timeout: number;
  }>({ host: "", port: 11434, timeout: 120 });
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const s = await api.serverSettings();
        setForm(s);
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  async function save() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await api.saveServerSettings(form);
      // Ollama 연결 확인
      try {
        const h = await api.healthPanel();
        setMsg(h.ok ? "저장 완료 — Ollama 연결 성공" : "저장 완료 — Ollama 연결 실패");
      } catch {
        setMsg("저장 완료 — 연결 확인 실패");
      }
      onSaved?.();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) return <div className="muted">불러오는 중...</div>;

  const baseUrl = `http://${form.host}:${form.port}`;

  return (
    <div className="agent-editor">
      <h3>Ollama 서버</h3>
      <p className="muted">
        외부 Ollama 서버를 사용하려면 호스트/포트를 지정하세요. 로컬은
        <code> localhost:11434</code>.
      </p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}
      <label>
        호스트
        <input
          value={form.host}
          onChange={(e) => setForm({ ...form, host: e.target.value })}
          placeholder="예: localhost, 100.64.0.10, ollama.local"
        />
      </label>
      <label>
        포트
        <input
          type="number"
          value={form.port}
          onChange={(e) =>
            setForm({ ...form, port: parseInt(e.target.value) || 11434 })
          }
        />
      </label>
      <label>
        타임아웃 (초)
        <input
          type="number"
          value={form.timeout}
          onChange={(e) =>
            setForm({ ...form, timeout: parseInt(e.target.value) || 120 })
          }
        />
      </label>
      <p className="muted">
        저장 후 Base URL: <code>{baseUrl}</code>
      </p>
      <div className="row">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "저장 중..." : "저장"}
        </button>
      </div>
    </div>
  );
}


function ImageGenPanel() {
  const [cfg, setCfg] = useState({
    backend: "auto",
    local_model: "",
    openai_model: "dall-e-3",
    default_size: "1024x1024",
  });
  const [backends, setBackends] = useState<
    { id: string; name: string; available: boolean; model: string; cost: string }[]
  >([]);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [c, b, s] = await Promise.all([
          api.imageGenSettings(),
          api.imageBackends(),
          api.listSecrets(),
        ]);
        const sm: Record<string, string> = {};
        for (const k of s.keys) {
          if (k.in_keychain) sm[k.key] = k.masked || "설정됨";
        }
        setSecrets(sm);
        setCfg(c);
        setBackends(b);
      } catch (e: any) {
        setErr(e.message);
      }
    })();
  }, []);

  async function save() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await api.saveImageGenSettings(cfg);
      setMsg("저장됨");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="agent-editor">
      <h3>이미지 생성</h3>
      <p className="muted">
        채팅에서 "그림 그려줘" 요청 시 사용할 백엔드를 설정합니다.
      </p>
      <details style={{ marginBottom: 12, fontSize: 12 }}>
        <summary style={{ cursor: "pointer", color: "var(--primary)" }}>로컬 FLUX.1 설정 가이드</summary>
        <div className="info-box" style={{ borderRadius: 6, padding: 10, marginTop: 6 }}>
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>터미널: <code>pip install mflux</code></li>
            <li><a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">HuggingFace 토큰 생성</a> (Read 권한)</li>
            <li><a href="https://huggingface.co/black-forest-labs/FLUX.1-schnell" target="_blank" rel="noreferrer">FLUX.1-schnell 모델 접근 승인</a> (Agree 버튼)</li>
            <li>아래 HUGGINGFACE_TOKEN에 토큰 입력</li>
            <li>터미널: <code>huggingface-cli login</code> (토큰 입력)</li>
            <li>첫 생성 시 ~4GB 모델 자동 다운로드</li>
          </ol>
        </div>
      </details>
      <details style={{ marginBottom: 12, fontSize: 12 }}>
        <summary style={{ cursor: "pointer", color: "var(--primary)" }}>OpenAI DALL-E 설정 가이드</summary>
        <div className="info-box" style={{ borderRadius: 6, padding: 10, marginTop: 6 }}>
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li><a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">OpenAI API 키 생성</a></li>
            <li>아래 OPENAI_API_KEY에 키 입력</li>
            <li>백엔드를 "OpenAI DALL-E 3" 또는 "auto"로 설정</li>
            <li>비용: ~$0.04/장 (1024x1024)</li>
          </ol>
        </div>
      </details>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      {backends.length > 0 && (
        <div className="info-box" style={{ borderRadius: 6, padding: 10, marginBottom: 12, fontSize: 13 }}>
          {backends.map((b) => (
            <div key={b.id} style={{ marginBottom: 4 }}>
              <strong>{b.name}</strong>:{" "}
              {b.available ? (
                <span style={{ color: "#16a34a" }}>사용 가능 ({b.model})</span>
              ) : (
                <span style={{ color: "#dc2626" }}>미설정</span>
              )}{" "}
              — {b.cost}
            </div>
          ))}
        </div>
      )}

      <label>
        백엔드
        <select
          value={cfg.backend}
          onChange={(e) => setCfg({ ...cfg, backend: e.target.value })}
        >
          <option value="auto">auto (키 있으면 OpenAI, 없으면 로컬)</option>
          <option value="local">로컬 (MLX — 무료)</option>
          <option value="openai">OpenAI DALL-E 3 (~$0.04/장)</option>
        </select>
      </label>
      <label>
        기본 크기
        <select
          value={cfg.default_size}
          onChange={(e) => setCfg({ ...cfg, default_size: e.target.value })}
        >
          <option value="512x512">512x512 (로컬 빠름)</option>
          <option value="1024x1024">1024x1024 (기본)</option>
          <option value="1024x1792">1024x1792 (세로)</option>
          <option value="1792x1024">1792x1024 (가로)</option>
        </select>
      </label>
      <h4 style={{ marginTop: 16, marginBottom: 4 }}>API 키</h4>
      <p className="muted">
        입력 후 포커스를 빼면 OS Keychain에 자동 저장됩니다.
      </p>
      <label>
        OPENAI_API_KEY {secrets["OPENAI_API_KEY"] && <span className="muted"> — 저장됨: {secrets["OPENAI_API_KEY"]}</span>}
        <input
          placeholder={secrets["OPENAI_API_KEY"] ? `현재: ${secrets["OPENAI_API_KEY"]}  (새 값 입력 시 덮어씀)` : "sk-..."}
          onBlur={async (e) => {
            const v = e.target.value.trim();
            if (v) {
              try {
                await api.setSecret("OPENAI_API_KEY", v);
                setSecrets((s) => ({ ...s, OPENAI_API_KEY: v.slice(0, 4) + "..." + v.slice(-4) }));
                setMsg("OPENAI_API_KEY 저장됨");
              } catch (ex: any) { setErr(ex.message); }
            }
          }}
        />
      </label>
      <label>
        HUGGINGFACE_TOKEN {secrets["HUGGINGFACE_TOKEN"] && <span className="muted"> — 저장됨: {secrets["HUGGINGFACE_TOKEN"]}</span>}
        <input
          placeholder={secrets["HUGGINGFACE_TOKEN"] ? `현재: ${secrets["HUGGINGFACE_TOKEN"]}  (새 값 입력 시 덮어씀)` : "hf_..."}
          onBlur={async (e) => {
            const v = e.target.value.trim();
            if (v) {
              try {
                await api.setSecret("HUGGINGFACE_TOKEN", v);
                setSecrets((s) => ({ ...s, HUGGINGFACE_TOKEN: v.slice(0, 4) + "..." + v.slice(-4) }));
                setMsg("HUGGINGFACE_TOKEN 저장됨");
              } catch (ex: any) { setErr(ex.message); }
            }
          }}
        />
      </label>
      <div className="row">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "저장 중..." : "저장"}
        </button>
      </div>
    </div>
  );
}
