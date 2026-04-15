import { useEffect, useState } from "react";
import {
  api,
  type AbResultDetail,
  type AbResultSummary,
  type AbRunResult,
  type ActivityEntry,
  type AuditEntry,
  type Checkpoint,
  type FailureDetail,
  type FailureSummary,
} from "./api";

type Tab = "ab" | "failures" | "checkpoints" | "audit" | "activity";

export default function Dashboard({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("ab");
  return (
    <div className="settings-root">
      <header className="settings-header">
        <button className="back-btn" onClick={onBack}>
          ← 돌아가기
        </button>
        <h2>대시보드</h2>
        <nav className="settings-tabs">
          <button
            className={tab === "ab" ? "active" : ""}
            onClick={() => setTab("ab")}
          >
            A/B 결과
          </button>
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
            className={tab === "audit" ? "active" : ""}
            onClick={() => setTab("audit")}
          >
            Audit
          </button>
          <button
            className={tab === "activity" ? "active" : ""}
            onClick={() => setTab("activity")}
          >
            활동 로그
          </button>
        </nav>
      </header>
      <main className="settings-body">
        {tab === "ab" && <AbTab />}
        {tab === "failures" && <FailuresTab />}
        {tab === "checkpoints" && <CheckpointsTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "activity" && <ActivityTab />}
      </main>
    </div>
  );
}

function AbTab() {
  const [list, setList] = useState<AbResultSummary[]>([]);
  const [detail, setDetail] = useState<{
    name: string;
    data: AbResultDetail;
  } | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setList(await api.abResults());
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
      const d = await api.abResult(name);
      setDetail({ name, data: d });
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <>
      <div className="panel-toolbar">
        <button onClick={refresh}>새로고침</button>
      </div>
      {err && <div className="err">{err}</div>}
      {loading && <div className="muted">불러오는 중...</div>}
      {!loading && list.length === 0 && (
        <div className="muted">
          저장된 A/B 결과가 없습니다. 터미널에서{" "}
          <code>raphael ab-test &lt;scenario&gt; --models gemma4-e2b,gemma4-e4b</code>{" "}
          실행 후 새로고침하세요.
        </div>
      )}
      {!loading && list.length > 0 && !detail && (
        <RunList list={list} onOpen={open} />
      )}
      {detail && (
        <RunDetail
          name={detail.name}
          data={detail.data}
          onClose={() => setDetail(null)}
        />
      )}
    </>
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
    if (!confirm(`${name} 삭제?`)) return;
    try {
      await api.deleteFailure(name);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function clearAll() {
    if (!confirm("모든 실패 케이스를 삭제합니다. 계속?")) return;
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
                  style={{ maxWidth: 320, fontSize: 12, color: "#4b5563" }}
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
    if (!confirm(`${id} 복원? 현재 파일은 덮어쓰여집니다.`)) return;
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
                    color: "#4b5563",
                  }}
                  title={JSON.stringify(e.data)}
                >
                  {JSON.stringify(e.data).slice(0, 160)}
                </td>
                <td
                  style={{
                    fontSize: 10,
                    fontFamily: "ui-monospace, monospace",
                    color: "#9ca3af",
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
          background: "#f9fafb",
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
              background: "#fff",
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
              color: "#4b5563",
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

function RunList({
  list,
  onOpen,
}: {
  list: AbResultSummary[];
  onOpen: (name: string) => void;
}) {
  // 모델별 전체 성공률 계산: 각 파일의 results를 로드해야 정확하지만,
  // 요약 단계에서는 파일당 success_count/total만 사용
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>최근 실행 ({list.length})</h3>
      <table className="agent-table">
        <thead>
          <tr>
            <th>시간</th>
            <th>시나리오</th>
            <th>모델</th>
            <th>성공률</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.map((s) => {
            const rate = s.total ? (s.success_count / s.total) * 100 : 0;
            return (
              <tr key={s.file}>
                <td>{new Date(s.mtime * 1000).toLocaleString()}</td>
                <td>
                  #{s.scenario_id} {s.title}
                </td>
                <td>{s.models.join(", ")}</td>
                <td>
                  <SuccessBar rate={rate} label={`${s.success_count}/${s.total}`} />
                </td>
                <td>
                  <button onClick={() => onOpen(s.file)}>상세</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SuccessBar({ rate, label }: { rate: number; label: string }) {
  const color = rate >= 80 ? "#16a34a" : rate >= 40 ? "#ca8a04" : "#dc2626";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 140 }}>
      <div
        style={{
          flex: 1,
          height: 6,
          background: "#eef0f3",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${rate}%`,
            height: "100%",
            background: color,
            transition: "width 0.3s",
          }}
        />
      </div>
      <span style={{ fontSize: 12, color: "#4b5563", minWidth: 40 }}>{label}</span>
    </div>
  );
}

function RunDetail({
  name,
  data,
  onClose,
}: {
  name: string;
  data: AbResultDetail;
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
      <h3 style={{ marginTop: 0 }}>
        #{data.scenario_id} {data.title}
      </h3>
      <table className="agent-table">
        <thead>
          <tr>
            <th>모델</th>
            <th>결과</th>
            <th>소요</th>
            <th>응답 길이</th>
            <th>최종 모델</th>
            <th>오류</th>
          </tr>
        </thead>
        <tbody>
          {data.results.map((r: AbRunResult, i: number) => (
            <tr key={i}>
              <td>
                <code>{r.model}</code>
              </td>
              <td>
                {r.success ? (
                  <span style={{ color: "#16a34a", fontWeight: 600 }}>✓ 성공</span>
                ) : (
                  <span style={{ color: "#dc2626", fontWeight: 600 }}>✗ 실패</span>
                )}
              </td>
              <td>{r.duration != null ? `${r.duration.toFixed(1)}s` : "-"}</td>
              <td>{r.response_len ?? "-"}</td>
              <td>
                {r.final_model === r.model ? (
                  <code>{r.final_model}</code>
                ) : (
                  <span title="에스컬레이션 발생">
                    <code>{r.final_model}</code>{" "}
                    <span className="badge" style={{ background: "#fef3c7", color: "#854d0e" }}>
                      escalated
                    </span>
                  </span>
                )}
              </td>
              <td style={{ fontSize: 12, color: "#dc2626", maxWidth: 260 }}>
                {r.error || ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div
        style={{
          marginTop: 24,
          padding: 12,
          background: "#f9fafb",
          borderRadius: 6,
        }}
      >
        <div className="muted" style={{ marginBottom: 8 }}>
          모델별 요약
        </div>
        {data.results.map((r, i) => (
          <div key={i} style={{ marginBottom: 6 }}>
            <code>{r.model}</code>:{" "}
            <SuccessBar
              rate={r.success ? 100 : 0}
              label={r.success ? "성공" : "실패"}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
