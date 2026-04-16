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

export default function Settings({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("agents");

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
            <AgentsPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #e7e9ef" }} />
            <ProfilePanel />
          </>
        )}
        {tab === "skills" && <SkillsPanel />}
        {tab === "models" && (
          <>
            <ModelsPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #e7e9ef" }} />
            <RoutingPanel />
          </>
        )}
        {tab === "server" && (
          <>
            <ServerPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #e7e9ef" }} />
            <PoolPanel />
            <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #e7e9ef" }} />
            <SecurityPanel />
          </>
        )}
        {tab === "rag" && <RagPanel />}
      </main>
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
      <ul className="model-list">
        {info.available.map((k) => (
          <li key={k}>
            <code>{k}</code>
            {k === info.current ? (
              <span className="badge">활성</span>
            ) : (
              <button disabled={busy} onClick={() => choose(k)}>
                사용
              </button>
            )}
          </li>
        ))}
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
            border: "1px solid #d4d7df",
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
      <p className="muted" style={{ marginTop: 12 }}>
        라우터에 새 모델 등록은 <code>~/.raphael/settings.yaml</code> 의
        models.ollama.available 직접 수정 (향후 UI 예정).
      </p>
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
      </div>
    </div>
  );
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
            border: "1px solid #d4d7df",
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
            border: "1px solid #d4d7df",
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
            border: "1px solid #d4d7df",
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
    <div>
      <p className="muted">
        Orchestrator가 매 라우팅 시 system 메시지로 자동 주입합니다. 이름,
        선호도, 사용 환경, 자주 쓰는 도구 등을 기록하세요.
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
            <tr key={f.id}>
              <td>{f.text}</td>
              <td style={{ fontSize: 11 }}>{f.source}</td>
              <td style={{ fontSize: 11 }}>{f.added.replace("T", " ")}</td>
              <td className="actions">
                <button onClick={() => del(f.id)}>삭제</button>
              </td>
            </tr>
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
            border: "1px solid #d4d7df",
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
                  border: "1px solid #d4d7df",
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

function ServerPanel() {
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
      setMsg("저장 완료. 다음 요청부터 적용됩니다.");
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

