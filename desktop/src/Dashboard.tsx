import { useEffect, useMemo, useState } from "react";
import {
  api,
  type AbResultDetail,
  type AbResultSummary,
  type AbRunResult,
} from "./api";

export default function Dashboard({ onBack }: { onBack: () => void }) {
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

  // 모델별 누적 통계 (전체 결과에서 모델 이름 수집)
  const [aggregate, aggregateModels] = useMemo(() => {
    const byModel: Record<
      string,
      { runs: number; success: number; avgDuration: number; durSum: number; durN: number }
    > = {};
    list.forEach((s) => {
      s.models.forEach((_m) => {
        // summary에는 개별 model별 success/duration이 없어 간단 요약만
      });
    });
    return [byModel, Object.keys(byModel)];
  }, [list]);
  void aggregate;
  void aggregateModels;

  return (
    <div className="settings-root">
      <header className="settings-header">
        <button className="back-btn" onClick={onBack}>
          ← 돌아가기
        </button>
        <h2>A/B 대시보드</h2>
        <div className="settings-tabs">
          <button onClick={refresh}>새로고침</button>
        </div>
      </header>
      <main className="settings-body">
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
      </main>
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
