import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  api,
  newSessionId,
  type Message,
  type SessionMeta,
  type ModelsInfo,
  type SessionHit,
} from "./api";
import Settings from "./Settings";
import Dashboard from "./Dashboard";
import "highlight.js/styles/github-dark.css";
import "./App.css";

export default function App() {
  const [view, setView] = useState<"chat" | "settings" | "dashboard">("chat");
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeSid, setActiveSid] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamBuf, setStreamBuf] = useState("");
  const [models, setModels] = useState<ModelsInfo | null>(null);
  const [healthy, setHealthy] = useState<boolean>(false);
  const [tools, setTools] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchHits, setSearchHits] = useState<SessionHit[]>([]);
  const [searching, setSearching] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      for (let i = 0; i < 30; i++) {
        try {
          await api.health();
          if (!alive) return;
          setHealthy(true);
          break;
        } catch {
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      if (alive) {
        await refreshSessions();
        try {
          setModels(await api.models());
        } catch {}
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (healthy && !activeSid) startNewSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [healthy]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, streamBuf]);

  async function refreshSessions() {
    try {
      setSessions(await api.sessions());
    } catch {}
  }

  function startNewSession() {
    const sid = newSessionId();
    setActiveSid(sid);
    setMessages([]);
    setStreamBuf("");
    setTools([]);
  }

  async function loadSession(sid: string) {
    setActiveSid(sid);
    setStreamBuf("");
    setTools([]);
    try {
      const det = await api.session(sid);
      setMessages(det.conversation.filter((m) => m.role !== "system"));
    } catch {
      setMessages([]);
    }
  }

  async function deleteSession(sid: string) {
    if (!confirm(`세션 ${sid.slice(0, 8)}... 삭제할까요?`)) return;
    try {
      await api.deleteSession(sid);
      if (sid === activeSid) startNewSession();
      await refreshSessions();
    } catch {}
  }

  async function sendMessage() {
    if (!input.trim() || streaming) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setStreaming(true);
    setStreamBuf("");
    setTools([]);
    let buf = "";
    try {
      await api.sendMessage(activeSid, text, undefined, {
        onChunk: (t) => {
          buf += t;
          setStreamBuf(buf);
        },
        onToolCall: (d) => {
          setTools((tt) => [...tt, `🔧 ${d?.name ?? "?"}`]);
        },
        onFinal: (full) => {
          buf = full;
          setStreamBuf(full);
        },
      });
      setMessages((m) => [...m, { role: "assistant", content: buf || "(빈 응답)" }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠ 오류: ${e}` }]);
    } finally {
      setStreaming(false);
      setStreamBuf("");
      setTools([]);
      await refreshSessions();
    }
  }

  async function changeModel(key: string) {
    try {
      await api.useModel(key);
      setModels(await api.models());
    } catch {}
  }

  async function exportCurrent(fmt: "markdown" | "json") {
    if (!activeSid) return;
    try {
      const res = await api.exportSession(activeSid, fmt);
      const mime = fmt === "json" ? "application/json" : "text/markdown";
      const blob = new Blob([res.content], { type: `${mime};charset=utf-8` });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`export 실패: ${e}`);
    }
  }

  async function runSessionSearch() {
    const q = searchQuery.trim();
    if (!q) {
      setSearchHits([]);
      return;
    }
    setSearching(true);
    try {
      const hits = await api.searchSessions(q, 15);
      setSearchHits(hits);
    } catch (e: any) {
      alert(`검색 실패: ${e.message || e}`);
    } finally {
      setSearching(false);
    }
  }

  async function reindexSessions() {
    if (!confirm("모든 세션을 재인덱싱합니다 (임베딩 호출, 시간 소요). 계속?"))
      return;
    try {
      const r = await api.reindexSessions();
      alert(`${r.indexed}개 메시지 인덱싱됨.`);
    } catch (e: any) {
      alert(`인덱싱 실패: ${e.message || e}`);
    }
  }

  async function showTokens() {
    try {
      const stats = await api.tokenStats();
      const entries = Object.entries(stats);
      if (!entries.length) {
        alert("아직 호출 기록이 없습니다.");
        return;
      }
      const lines = entries.map(([model, s]) => {
        const total = s.prompt + s.completion;
        return `${model}\n  ${s.calls}회, prompt ${s.prompt.toLocaleString()} + completion ${s.completion.toLocaleString()} = ${total.toLocaleString()} tokens, ${(s.total_ms / 1000).toFixed(1)}s`;
      });
      alert("토큰 사용량\n\n" + lines.join("\n\n"));
    } catch (e) {
      alert(`token stats 실패: ${e}`);
    }
  }

  if (view === "settings") {
    return <Settings onBack={() => setView("chat")} />;
  }
  if (view === "dashboard") {
    return <Dashboard onBack={() => setView("chat")} />;
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-head">
          <span className="brand">Raphael</span>
          <button onClick={startNewSession} title="새 세션">＋</button>
          <button
            title="A/B 대시보드"
            onClick={() => setView("dashboard")}
            style={{ marginLeft: 4, fontSize: 11, fontWeight: 300 }}
          >
            A/B
          </button>
          <button
            title="설정"
            onClick={() => setView("settings")}
            style={{ marginLeft: 4 }}
          >
            ⚙
          </button>
        </div>
        <div className="session-search">
          <input
            placeholder="세션 검색 (의미 기반)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runSessionSearch();
              if (e.key === "Escape") {
                setSearchQuery("");
                setSearchHits([]);
              }
            }}
          />
          {searchQuery && (
            <button
              className="session-search-clear"
              onClick={() => {
                setSearchQuery("");
                setSearchHits([]);
              }}
              title="지우기"
            >
              ×
            </button>
          )}
          <button
            className="session-search-reindex"
            onClick={reindexSessions}
            title="모든 세션 재인덱싱"
          >
            ⟳
          </button>
        </div>
        {searchHits.length > 0 && (
          <div className="search-results">
            <div className="search-results-head">
              {searching ? "검색 중..." : `결과 ${searchHits.length}`}
            </div>
            {searchHits.map((h, i) => (
              <div
                key={i}
                className="search-hit"
                onClick={() => {
                  loadSession(h.session_id);
                  setSearchHits([]);
                  setSearchQuery("");
                }}
              >
                <div className="search-hit-head">
                  <code>{h.session_id}</code>
                  <span className="muted">{h.role}</span>
                </div>
                <div className="search-hit-content">
                  {h.content.slice(0, 120)}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="sessions">
          {sessions.length === 0 && <div className="empty">세션 없음</div>}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session ${s.id === activeSid ? "active" : ""}`}
              onClick={() => loadSession(s.id)}
            >
              <div className="session-title">{s.title || "(빈 세션)"}</div>
              {s.tags && s.tags.length > 0 && (
                <div className="session-tags">
                  {s.tags.map((t) => (
                    <span key={t} className="session-tag">
                      #{t}
                    </span>
                  ))}
                </div>
              )}
              <div className="session-meta">
                <span>{s.agent}</span>
                <span>{s.turns}턴</span>
                <button
                  className="del"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteSession(s.id);
                  }}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="sidebar-foot">
          <span className={`dot ${healthy ? "ok" : "bad"}`} />
          <span style={{ fontSize: 12 }}>{healthy ? "연결됨" : "데몬 대기..."}</span>
          {models && (
            <select
              value={models.current}
              onChange={(e) => changeModel(e.target.value)}
              style={{ marginLeft: 8 }}
            >
              {models.available.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          )}
        </div>
      </aside>

      <main className="chat">
        <div className="chat-toolbar">
          <span className="muted" style={{ fontSize: 12 }}>
            {activeSid ? `session: ${activeSid}` : "new session"}
          </span>
          <div className="spacer" />
          <button
            className="tool-btn"
            disabled={!activeSid || messages.length === 0}
            onClick={() => exportCurrent("markdown")}
            title="대화를 Markdown으로 저장"
          >
            Export MD
          </button>
          <button
            className="tool-btn"
            disabled={!activeSid || messages.length === 0}
            onClick={() => exportCurrent("json")}
            title="대화를 JSON으로 저장"
          >
            Export JSON
          </button>
          <button
            className="tool-btn"
            onClick={showTokens}
            title="모델별 토큰 사용량"
          >
            Tokens
          </button>
        </div>
        <div className="messages" ref={scrollRef}>
          {messages.map((m, i) => (
            <div key={i} className={`msg msg-${m.role}`}>
              <div className="role">{m.role === "user" ? "You" : "Raphael"}</div>
              <div className="content">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {m.content}
                </ReactMarkdown>
              </div>
            </div>
          ))}
          {streaming && (
            <div className="msg msg-assistant streaming">
              <div className="role">Raphael (생성 중...)</div>
              {tools.length > 0 && <div className="tools">{tools.join("  ")}</div>}
              <div className="content">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {streamBuf || "..."}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>
        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={healthy ? "메시지 입력 (Enter 전송, Shift+Enter 줄바꿈)" : "데몬 대기 중..."}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            disabled={!healthy || streaming}
            rows={3}
          />
          <button onClick={sendMessage} disabled={!healthy || streaming || !input.trim()}>
            {streaming ? "전송 중..." : "전송"}
          </button>
        </div>
      </main>
    </div>
  );
}
