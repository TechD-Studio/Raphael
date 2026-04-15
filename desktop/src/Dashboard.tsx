import { useEffect, useState } from "react";
import {
  api,
  type AbResultDetail,
  type AbResultSummary,
  type AbRunResult,
  type FailureDetail,
  type FailureSummary,
} from "./api";

type Tab = "ab" | "failures";

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
        </nav>
      </header>
      <main className="settings-body">
        {tab === "ab" ? <AbTab /> : <FailuresTab />}
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
