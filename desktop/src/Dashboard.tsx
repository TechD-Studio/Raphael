import { useEffect, useState } from "react";
import {
  api,
  type ActivityEntry,
  type AuditEntry,
  type Checkpoint,
  type FailureDetail,
  type FailureSummary,
} from "./api";
import { confirmDialog } from "./confirm";

type Tab =
  | "failures"
  | "checkpoints"
  | "logs"
  | "system";

export default function Dashboard({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("failures");
  return (
    <div className="settings-root">
      <header className="settings-header">
        <button className="back-btn" onClick={onBack}>
          ← 돌아가기
        </button>
        <h2>대시보드</h2>
        <nav className="settings-tabs">
          <button
            className={tab === "failures" ? "active" : ""}
            onClick={() => setTab("failures")}
          >
            실패 케이스
          </button>
          <button
            className={tab === "checkpoints" ? "active" : ""}
            onClick={() => setTab("checkpoints")}
          >
            체크포인트
          </button>
          <button
            className={tab === "logs" ? "active" : ""}
            onClick={() => setTab("logs")}
          >
            로그
          </button>
          <button
            className={tab === "system" ? "active" : ""}
            onClick={() => setTab("system")}
          >
            시스템
          </button>
        </nav>
      </header>
      <main className="settings-body">
        {tab === "failures" && <FailuresTab />}
        {/* AbTab removed */}
        {tab === "checkpoints" && <CheckpointsTab />}
        {tab === "logs" && <LogsTab />}
        {tab === "system" && <SystemTab />}
      </main>
    </div>
  );
}

function FailuresTab() {
  const [list, setList] = useState<FailureSummary[]>([]);
  const [detail, setDetail] = useState<{
    name: string;
    data: FailureDetail;
  } | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setList(await api.failures());
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function open(name: string) {
    try {
      setDetail({ name, data: await api.failure(name) });
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function remove(name: string) {
    if (!(await confirmDialog(`${name} 삭제?`, { danger: true, okLabel: "삭제" }))) return;
    try {
      await api.deleteFailure(name);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function clearAll() {
    if (
      !(await confirmDialog("모든 실패 케이스를 삭제합니다. 계속?", {
        danger: true,
        okLabel: "모두 삭제",
      }))
    )
      return;
    try {
      await api.clearFailures();
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (detail) {
    return (
      <FailureDetailView
        name={detail.name}
        data={detail.data}
        onClose={() => setDetail(null)}
      />
    );
  }

  return (
    <>
      <div className="panel-toolbar">
        <button onClick={refresh}>새로고침</button>
        {list.length > 0 && (
          <button onClick={clearAll} style={{ marginLeft: 8 }}>
            전체 삭제
          </button>
        )}
      </div>
      {err && <div className="err">{err}</div>}
      {loading && <div className="muted">불러오는 중...</div>}
      {!loading && list.length === 0 && (
        <div className="muted">기록된 실패 케이스가 없습니다.</div>
      )}
      {!loading && list.length > 0 && (
        <table className="agent-table">
          <thead>
            <tr>
              <th>시간</th>
              <th>에이전트</th>
              <th>모델</th>
              <th>원인</th>
              <th>턴</th>
              <th>입력 (발췌)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((f) => (
              <tr key={f.file}>
                <td>{new Date(f.mtime * 1000).toLocaleString()}</td>
                <td>
                  <code>{f.agent}</code>
                </td>
                <td>{f.model}</td>
                <td>
                  <span
                    className="badge"
                    style={{ background: "#fee2e2", color: "#991b1b" }}
                  >
                    {f.reason}
                  </span>
                </td>
                <td>{f.turns}</td>
                <td
                  style={{ maxWidth: 320, fontSize: 12, color: "var(--text-sub)" }}
                  title={f.user_input}
                >
                  {f.user_input}
                </td>
                <td className="actions">
                  <button onClick={() => open(f.file)}>보기</button>
                  <button onClick={() => remove(f.file)}>삭제</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function CheckpointsTab() {
  const [list, setList] = useState<Checkpoint[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    setMsg("");
    try {
      setList(await api.checkpoints());
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function restore(id: string) {
    if (
      !(await confirmDialog(`${id} 복원? 현재 파일은 덮어쓰여집니다.`, {
        danger: true,
        okLabel: "복원",
      }))
    )
      return;
    try {
      const res = await api.restoreCheckpoint(id);
      setMsg(res.message);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function cleanup() {
    const daysStr = prompt("며칠 이전 체크포인트를 삭제할까요?", "7");
    if (!daysStr) return;
    const days = parseInt(daysStr);
    if (!Number.isFinite(days) || days < 1) {
      alert("유효한 일수를 입력하세요");
      return;
    }
    try {
      const res = await api.cleanupCheckpoints(days);
      setMsg(`${res.deleted}개 삭제됨 (> ${res.days}일)`);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <>
      <div className="panel-toolbar">
        <button onClick={refresh}>새로고침</button>
        <button onClick={cleanup} style={{ marginLeft: 8 }}>
          오래된 항목 정리
        </button>
      </div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}
      {loading && <div className="muted">불러오는 중...</div>}
      {!loading && list.length === 0 && (
        <div className="muted">체크포인트가 없습니다.</div>
      )}
      {!loading && list.length > 0 && (
        <table className="agent-table">
          <thead>
            <tr>
              <th>생성 시각</th>
              <th>작업</th>
              <th>대상 파일</th>
              <th>백업</th>
              <th>메모</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((cp) => (
              <tr key={cp.id}>
                <td>{cp.created.replace("T", " ")}</td>
                <td>
                  <code>{cp.operation}</code>
                </td>
                <td
                  style={{
                    fontSize: 12,
                    maxWidth: 320,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={cp.target}
                >
                  {cp.target}
                </td>
                <td>
                  {cp.backup_path ? (
                    <span
                      className="badge"
                      style={{ background: "#dcfce7", color: "#166534" }}
                    >
                      있음
                    </span>
                  ) : (
                    <span className="muted">없음 (신규 파일)</span>
                  )}
                </td>
                <td style={{ fontSize: 12 }}>{cp.note}</td>
                <td className="actions">
                  <button
                    disabled={!cp.backup_path}
                    onClick={() => restore(cp.id)}
                  >
                    복원
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function LogsTab() {
  const [sub, setSub] = useState<"audit" | "activity">("audit");
  return (
    <>
      <div className="panel-toolbar" style={{ display: "flex", gap: 6 }}>
        <button
          className={sub === "audit" ? "primary" : ""}
          onClick={() => setSub("audit")}
          style={sub === "audit" ? {} : { background: "var(--bg-card)", color: "var(--text-sub)", border: "1px solid var(--input-border)" }}
        >
          Audit
        </button>
        <button
          className={sub === "activity" ? "primary" : ""}
          onClick={() => setSub("activity")}
          style={sub === "activity" ? {} : { background: "var(--bg-card)", color: "var(--text-sub)", border: "1px solid var(--input-border)" }}
        >
          활동 로그
        </button>
      </div>
      {sub === "audit" && <AuditTab />}
      {sub === "activity" && <ActivityTab />}
    </>
  );
}

function AuditTab() {
  const [list, setList] = useState<AuditEntry[]>([]);
  const [tail, setTail] = useState(200);
  const [err, setErr] = useState("");
  const [verifyMsg, setVerifyMsg] = useState("");
  const [verifyOk, setVerifyOk] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setList(await api.audit(tail));
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tail]);

  async function doVerify() {
    try {
      const res = await api.auditVerify();
      setVerifyOk(res.ok);
      setVerifyMsg(`${res.count}줄 검증 — ${res.message}`);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <>
      <div className="panel-toolbar">
        <button onClick={refresh}>새로고침</button>
        <button onClick={doVerify} style={{ marginLeft: 8 }}>
          체인 무결성 검증
        </button>
        <label className="muted" style={{ marginLeft: 12, fontSize: 12 }}>
          최근 N줄:
          <select
            value={tail}
            onChange={(e) => setTail(parseInt(e.target.value))}
            style={{ marginLeft: 6 }}
          >
            <option value={50}>50</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </label>
      </div>
      {err && <div className="err">{err}</div>}
      {verifyMsg && (
        <div
          className={verifyOk ? "ok-msg" : "err"}
          style={{ marginBottom: 12 }}
        >
          {verifyOk ? "✓ " : "✗ "}
          {verifyMsg}
        </div>
      )}
      {loading && <div className="muted">불러오는 중...</div>}
      {!loading && list.length === 0 && (
        <div className="muted">Audit 로그가 비어있습니다.</div>
      )}
      {!loading && list.length > 0 && (
        <table className="agent-table">
          <thead>
            <tr>
              <th>시간</th>
              <th>유형</th>
              <th>에이전트</th>
              <th>세션</th>
              <th>데이터</th>
              <th>hash</th>
            </tr>
          </thead>
          <tbody>
            {list.map((e, i) => (
              <tr key={i}>
                <td style={{ fontSize: 12 }}>{(e.ts || "").replace("T", " ")}</td>
                <td>
                  <code>{e.type}</code>
                </td>
                <td>
                  {e.agent && <code>{e.agent}</code>}
                </td>
                <td style={{ fontSize: 12 }}>{e.session || ""}</td>
                <td
                  style={{
                    fontSize: 11,
                    maxWidth: 360,
                    fontFamily: "ui-monospace, monospace",
                    color: "var(--text-sub)",
                  }}
                  title={JSON.stringify(e.data)}
                >
                  {JSON.stringify(e.data).slice(0, 160)}
                </td>
                <td
                  style={{
                    fontSize: 10,
                    fontFamily: "ui-monospace, monospace",
                    color: "var(--text-muted)",
                  }}
                  title={e.hash}
                >
                  {(e.hash || "").slice(0, 8)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function ActivityTab() {
  const [list, setList] = useState<ActivityEntry[]>([]);
  const [tail, setTail] = useState(200);
  const [session, setSession] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [auto, setAuto] = useState(true);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      setList(await api.activity(tail, session));
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tail, session]);

  useEffect(() => {
    if (!auto) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, tail, session]);

  const filtered = typeFilter
    ? list.filter((e) => e.type === typeFilter)
    : list;
  const types = Array.from(new Set(list.map((e) => e.type || ""))).filter(Boolean);

  function eventColor(t?: string): string {
    switch (t) {
      case "user_message":
        return "#2563eb";
      case "model_call_start":
      case "model_call_end":
        return "#7c3aed";
      case "token_chunk":
        return "#9ca3af";
      case "tool_call":
        return "#ca8a04";
      case "tool_result":
        return "#16a34a";
      default:
        return "#4b5563";
    }
  }

  return (
    <>
      <div className="panel-toolbar" style={{ flexWrap: "wrap", gap: 8 }}>
        <button onClick={refresh}>새로고침</button>
        <label className="muted" style={{ fontSize: 12 }}>
          <input
            type="checkbox"
            checked={auto}
            onChange={(e) => setAuto(e.target.checked)}
            style={{ marginRight: 4 }}
          />
          자동 새로고침 (3초)
        </label>
        <label className="muted" style={{ fontSize: 12 }}>
          Tail:
          <select
            value={tail}
            onChange={(e) => setTail(parseInt(e.target.value))}
            style={{ marginLeft: 6 }}
          >
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </label>
        <input
          placeholder="session id 필터"
          value={session}
          onChange={(e) => setSession(e.target.value)}
          style={{
            border: "1px solid #d4d7df",
            borderRadius: 4,
            padding: "4px 8px",
            fontSize: 12,
            width: 180,
          }}
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          style={{
            border: "1px solid #d4d7df",
            borderRadius: 4,
            padding: "4px 8px",
            fontSize: 12,
          }}
        >
          <option value="">전체 타입</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      {err && <div className="err">{err}</div>}
      {loading && <div className="muted">불러오는 중...</div>}
      {!loading && filtered.length === 0 && (
        <div className="muted">
          활동 로그가 비어있습니다 (<code>~/.raphael/activity.jsonl</code>).
        </div>
      )}
      {!loading && filtered.length > 0 && (
        <div className="activity-log">
          {filtered.map((e, i) => (
            <div key={i} className="activity-row">
              <span className="activity-ts">
                {(e.ts || "").slice(11, 19)}
              </span>
              <span
                className="activity-type"
                style={{ color: eventColor(e.type), fontWeight: 600 }}
              >
                {e.type}
              </span>
              {e.agent && <span className="activity-agent">{e.agent}</span>}
              {e.model && <span className="activity-agent">{e.model}</span>}
              <span className="activity-data" title={JSON.stringify(e.data)}>
                {JSON.stringify(e.data).slice(0, 240)}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function SystemTab() {
  const [health, setHealth] = useState<any>(null);
  const [feedback, setFeedback] = useState<any>(null);
  const [mcp, setMcp] = useState<any>(null);
  const [plugins, setPlugins] = useState<any>(null);
  const [bots, setBots] = useState<any[]>([]);
  const [err, setErr] = useState("");

  // MCP call form
  const [mcpSel, setMcpSel] = useState<{ server: string; tool: string } | null>(
    null,
  );
  const [mcpArgs, setMcpArgs] = useState("{}");
  const [mcpResult, setMcpResult] = useState("");

  async function refresh() {
    try {
      const [h, f, m, p, b] = await Promise.all([
        api.healthPanel(),
        api.feedbackStats(),
        api.mcpServers(),
        api.plugins(),
        api.bots(),
      ]);
      setHealth(h);
      setFeedback(f);
      setMcp(m);
      setPlugins(p);
      setBots(b);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function callMcp() {
    if (!mcpSel) return;
    setMcpResult("실행 중...");
    try {
      const args = JSON.parse(mcpArgs || "{}");
      const r = await api.mcpCall(mcpSel.server, mcpSel.tool, args);
      setMcpResult(r.result);
    } catch (e: any) {
      setMcpResult(`오류: ${e?.message || e}`);
    }
  }

  async function botAction(name: string, action: "start" | "stop") {
    try {
      if (action === "start") await api.startBot(name);
      else await api.stopBot(name);
      await refresh();
    } catch (e: any) {
      alert(`${action} 실패: ${e.message}`);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <>
      <div className="panel-toolbar">
        <button onClick={refresh}>새로고침</button>
      </div>
      {err && <div className="err">{err}</div>}

      <h3 style={{ marginTop: 0 }}>Health</h3>
      {health && (
        <div className="card-grid">
          <div className="stat-card">
            <div className="stat-label">현재 모델</div>
            <div className="stat-value">
              <code>{health.current_model}</code>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">활성 에이전트</div>
            <div className="stat-value">{health.agents.length}</div>
            <div className="stat-sub">{health.agents.join(", ")}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">누적 호출</div>
            <div className="stat-value">
              {health.total_calls.toLocaleString()}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">누적 토큰</div>
            <div className="stat-value">
              {health.total_tokens.toLocaleString()}
            </div>
          </div>
        </div>
      )}

      <h3>피드백</h3>
      {feedback && (
        <div className="card-grid">
          <div className="stat-card">
            <div className="stat-label">전체</div>
            <div className="stat-value">{feedback.total}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label" style={{ color: "#16a34a" }}>
              긍정
            </div>
            <div className="stat-value">{feedback.positive}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label" style={{ color: "#dc2626" }}>
              부정
            </div>
            <div className="stat-value">{feedback.negative}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">중립</div>
            <div className="stat-value">{feedback.neutral}</div>
          </div>
        </div>
      )}

      <h3>MCP 서버</h3>
      {mcp && (
        <div style={{ fontSize: 13 }}>
          <div style={{ marginBottom: 8 }}>
            <b>설정된 서버:</b>{" "}
            {mcp.configured.length === 0 ? (
              <span className="muted">없음 — settings.yaml의 mcp.servers 참고</span>
            ) : (
              mcp.configured.map((s: any, i: number) => (
                <code key={i} style={{ marginRight: 6 }}>
                  {s.name || JSON.stringify(s)}
                </code>
              ))
            )}
          </div>
          <div>
            <b>런타임 도구:</b>{" "}
            {(!mcp.runtime_tools || mcp.runtime_tools.length === 0) && (
              <span className="muted">없음</span>
            )}
          </div>
          {mcp.runtime_tools && mcp.runtime_tools.length > 0 && (
            <>
              <table className="agent-table" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>서버</th>
                    <th>도구</th>
                    <th>설명</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {mcp.runtime_tools.map(
                    (
                      t: { server: string; tool: string; description: string },
                      i: number,
                    ) => (
                      <tr key={i}>
                        <td>
                          <code>{t.server}</code>
                        </td>
                        <td>
                          <code>{t.tool}</code>
                        </td>
                        <td style={{ fontSize: 12 }}>{t.description}</td>
                        <td>
                          <button
                            onClick={() => {
                              setMcpSel({ server: t.server, tool: t.tool });
                              setMcpArgs("{}");
                              setMcpResult("");
                            }}
                          >
                            호출
                          </button>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
              {mcpSel && (
                <div
                  style={{
                    marginTop: 10,
                    padding: 10,
                    border: "1px solid #e7e9ef",
                    borderRadius: 6,
                    background: "var(--panel-bg)",
                  }}
                >
                  <div style={{ fontSize: 13, marginBottom: 6 }}>
                    <b>
                      <code>
                        {mcpSel.server} / {mcpSel.tool}
                      </code>
                    </b>{" "}
                    호출
                  </div>
                  <textarea
                    value={mcpArgs}
                    onChange={(e) => setMcpArgs(e.target.value)}
                    rows={5}
                    style={{
                      width: "100%",
                      border: "1px solid #d4d7df",
                      borderRadius: 4,
                      padding: 6,
                      fontFamily: "ui-monospace, monospace",
                      fontSize: 12,
                    }}
                  />
                  <div className="row" style={{ marginTop: 6 }}>
                    <button className="primary" onClick={callMcp}>
                      실행
                    </button>
                    <button onClick={() => setMcpSel(null)}>닫기</button>
                  </div>
                  {mcpResult && (
                    <pre
                      style={{
                        marginTop: 8,
                        background: "var(--bg-card)",
                        padding: 8,
                        border: "1px solid #e7e9ef",
                        borderRadius: 4,
                        fontSize: 12,
                        maxHeight: 240,
                        overflow: "auto",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {mcpResult}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      <h3>봇 프로세스</h3>
      <p className="muted">
        토큰은 설정 &gt; 보안 의 Keychain 시크릿으로 저장됩니다
        (TELEGRAM_BOT_TOKEN, SLACK_APP_TOKEN, DISCORD_BOT_TOKEN 등).
      </p>
      <table className="agent-table">
        <thead>
          <tr>
            <th>봇</th>
            <th>상태</th>
            <th>PID</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {bots.map((b) => (
            <tr key={b.name}>
              <td>
                <code>{b.name}</code>
              </td>
              <td>
                {b.running ? (
                  <span
                    className="badge"
                    style={{ background: "#dcfce7", color: "#166534" }}
                  >
                    실행 중
                  </span>
                ) : (
                  <span className="muted">중지</span>
                )}
              </td>
              <td>{b.pid || "-"}</td>
              <td>
                {b.running ? (
                  <button onClick={() => botAction(b.name, "stop")}>중지</button>
                ) : (
                  <button onClick={() => botAction(b.name, "start")}>시작</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>플러그인</h3>
      {plugins && (
        <div style={{ fontSize: 13 }}>
          <div>
            <b>Tool plugins:</b>{" "}
            {plugins.tools.length === 0 ? (
              <span className="muted">없음</span>
            ) : (
              plugins.tools.map((p: any) => (
                <div key={p.name}>
                  <code>{p.name}</code> → {p.value}
                </div>
              ))
            )}
          </div>
          <div style={{ marginTop: 6 }}>
            <b>Agent plugins:</b>{" "}
            {plugins.agents.length === 0 ? (
              <span className="muted">없음</span>
            ) : (
              plugins.agents.map((p: any) => (
                <div key={p.name}>
                  <code>{p.name}</code> → {p.value}
                </div>
              ))
            )}
          </div>
        </div>
      )}

    </>
  );
}

function FailureDetailView({
  name,
  data,
  onClose,
}: {
  name: string;
  data: FailureDetail;
  onClose: () => void;
}) {
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={onClose}>← 목록으로</button>
        <span className="muted" style={{ marginLeft: 12 }}>
          {name}
        </span>
      </div>
      <div
        style={{
          background: "var(--panel-bg)",
          border: "1px solid #e7e9ef",
          borderRadius: 6,
          padding: 12,
          marginBottom: 12,
          fontSize: 13,
        }}
      >
        <div>
          <b>agent:</b> <code>{data.agent}</code>
        </div>
        <div>
          <b>model:</b> <code>{data.model}</code>
        </div>
        <div>
          <b>reason:</b>{" "}
          <span
            className="badge"
            style={{ background: "#fee2e2", color: "#991b1b" }}
          >
            {data.reason}
          </span>
        </div>
        <div style={{ marginTop: 8 }}>
          <b>user_input:</b>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              marginTop: 4,
              background: "var(--bg-card)",
              padding: 8,
              borderRadius: 4,
              border: "1px solid #e7e9ef",
              fontSize: 12,
            }}
          >
            {data.user_input}
          </pre>
        </div>
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        대화 (총 {data.conversation.length}턴)
      </div>
      {data.conversation.map((m, i) => (
        <div
          key={i}
          style={{
            background: m.role === "user" ? "#eff6ff" : "#f9fafb",
            border: "1px solid #e7e9ef",
            borderRadius: 6,
            padding: 10,
            marginBottom: 8,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--text-sub)",
              marginBottom: 6,
            }}
          >
            [{i}] {m.role}
          </div>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              margin: 0,
              fontSize: 12,
              fontFamily: "ui-monospace, monospace",
            }}
          >
            {m.content}
          </pre>
        </div>
      ))}
    </div>
  );
}
