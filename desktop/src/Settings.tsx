import { useEffect, useState } from "react";
import {
  api,
  type AgentDetail,
  type AgentInfo,
  type AgentUpsert,
  type ModelsInfo,
  type RoutingConfig,
  type RoutingRule,
} from "./api";

type Tab =
  | "agents"
  | "models"
  | "routing"
  | "rag"
  | "security"
  | "server";

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
            className={tab === "models" ? "active" : ""}
            onClick={() => setTab("models")}
          >
            모델
          </button>
          <button
            className={tab === "routing" ? "active" : ""}
            onClick={() => setTab("routing")}
          >
            라우팅
          </button>
          <button
            className={tab === "rag" ? "active" : ""}
            onClick={() => setTab("rag")}
          >
            RAG
          </button>
          <button
            className={tab === "security" ? "active" : ""}
            onClick={() => setTab("security")}
          >
            보안
          </button>
          <button
            className={tab === "server" ? "active" : ""}
            onClick={() => setTab("server")}
          >
            서버
          </button>
        </nav>
      </header>
      <main className="settings-body">
        {tab === "agents" && <AgentsPanel />}
        {tab === "models" && <ModelsPanel />}
        {tab === "routing" && <RoutingPanel />}
        {tab === "rag" && <RagPanel />}
        {tab === "security" && <SecurityPanel />}
        {tab === "server" && <ServerPanel />}
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
    if (!confirm(`"${name}" 에이전트를 삭제하시겠습니까?`)) return;
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
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setInfo(await api.models());
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

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
      <p className="muted">
        모델 추가는 <code>~/.raphael/settings.yaml</code> 에서 관리합니다.
      </p>
    </div>
  );
}

function RoutingPanel() {
  const [cfg, setCfg] = useState<RoutingConfig>({ strategy: "manual", rules: [] });
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [agents, setAgents] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const [c, m, a] = await Promise.all([
          api.routingSettings(),
          api.models(),
          api.agents(),
        ]);
        setCfg(c);
        setModels(m.available);
        setAgents(a.map((x) => x.name));
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  function updateRule(i: number, patch: Partial<RoutingRule>) {
    const rules = [...cfg.rules];
    rules[i] = { ...rules[i], ...patch };
    setCfg({ ...cfg, rules });
  }

  function addRule() {
    setCfg({
      ...cfg,
      rules: [...cfg.rules, { note: "새 규칙" }],
    });
  }

  function removeRule(i: number) {
    const rules = cfg.rules.filter((_, idx) => idx !== i);
    setCfg({ ...cfg, rules });
  }

  function moveRule(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= cfg.rules.length) return;
    const rules = [...cfg.rules];
    [rules[i], rules[j]] = [rules[j], rules[i]];
    setCfg({ ...cfg, rules });
  }

  async function save() {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await api.saveRoutingSettings(cfg);
      setMsg("저장 완료. 다음 요청부터 적용됩니다.");
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
        상황별로 다른 모델/에이전트를 자동 선택합니다. 규칙은 위에서 아래로
        매칭되며 첫 매치가 적용됩니다.
      </p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      <div className="row" style={{ marginBottom: 16 }}>
        <label className="inline">
          <input
            type="radio"
            name="strategy"
            checked={cfg.strategy === "auto"}
            onChange={() => setCfg({ ...cfg, strategy: "auto" })}
          />
          auto (규칙 기반 자동)
        </label>
        <label className="inline">
          <input
            type="radio"
            name="strategy"
            checked={cfg.strategy === "manual"}
            onChange={() => setCfg({ ...cfg, strategy: "manual" })}
          />
          manual (고정 모델)
        </label>
      </div>

      {cfg.rules.length === 0 && (
        <div className="muted" style={{ marginBottom: 12 }}>
          규칙이 없습니다.
        </div>
      )}

      {cfg.rules.map((r, i) => (
        <div key={i} className="rule-card">
          <div className="rule-head">
            <span className="muted">#{i + 1}</span>
            <input
              className="rule-note"
              placeholder="설명 (선택)"
              value={r.note || ""}
              onChange={(e) => updateRule(i, { note: e.target.value })}
            />
            <div style={{ flex: 1 }} />
            <button onClick={() => moveRule(i, -1)} disabled={i === 0}>
              ↑
            </button>
            <button
              onClick={() => moveRule(i, 1)}
              disabled={i === cfg.rules.length - 1}
            >
              ↓
            </button>
            <button onClick={() => removeRule(i)}>삭제</button>
          </div>
          <div className="rule-body">
            <div className="rule-col">
              <div className="rule-section-title">조건</div>
              <label>
                에이전트
                <select
                  value={r.agent || ""}
                  onChange={(e) =>
                    updateRule(i, { agent: e.target.value || undefined })
                  }
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
                최소 메시지 수
                <input
                  type="number"
                  value={r.min_messages ?? ""}
                  onChange={(e) =>
                    updateRule(i, {
                      min_messages: e.target.value
                        ? parseInt(e.target.value)
                        : undefined,
                    })
                  }
                  placeholder="예: 5"
                />
              </label>
              <label>
                토큰 추정치 &gt; (gt)
                <input
                  type="number"
                  value={r.token_estimate_gt ?? ""}
                  onChange={(e) =>
                    updateRule(i, {
                      token_estimate_gt: e.target.value
                        ? parseInt(e.target.value)
                        : undefined,
                    })
                  }
                  placeholder="예: 1000"
                />
              </label>
              <label>
                토큰 추정치 &lt; (lt)
                <input
                  type="number"
                  value={r.token_estimate_lt ?? ""}
                  onChange={(e) =>
                    updateRule(i, {
                      token_estimate_lt: e.target.value
                        ? parseInt(e.target.value)
                        : undefined,
                    })
                  }
                />
              </label>
              <label>
                포함 키워드 (쉼표 구분)
                <input
                  value={(r.contains_any || []).join(", ")}
                  onChange={(e) =>
                    updateRule(i, {
                      contains_any: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="예: 코드, 파일, 디버그"
                />
              </label>
              <label className="inline">
                <input
                  type="checkbox"
                  checked={!!r.default}
                  onChange={(e) => updateRule(i, { default: e.target.checked })}
                />
                기본 규칙 (다른 규칙 매치 실패 시)
              </label>
            </div>
            <div className="rule-col">
              <div className="rule-section-title">결과</div>
              <label>
                선호 모델
                <select
                  value={r.prefer_model || ""}
                  onChange={(e) =>
                    updateRule(i, { prefer_model: e.target.value || undefined })
                  }
                >
                  <option value="">(변경 없음)</option>
                  {models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                선호 에이전트
                <select
                  value={r.prefer_agent || ""}
                  onChange={(e) =>
                    updateRule(i, { prefer_agent: e.target.value || undefined })
                  }
                >
                  <option value="">(변경 없음)</option>
                  {agents.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        </div>
      ))}

      <div className="row">
        <button onClick={addRule}>+ 규칙 추가</button>
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "저장 중..." : "저장"}
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
    if (!confirm("전체 재인덱싱 (시간 소요). 계속?")) return;
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
          style={{
            background: "#f9fafb",
            border: "1px solid #e7e9ef",
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
    if (!confirm(`${k} 삭제?`)) return;
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
