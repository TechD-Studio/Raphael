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
import { confirmDialog } from "./confirm";
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
  const [tagFilter, setTagFilter] = useState<string>("");
  const [searching, setSearching] = useState(false);
  const [agentNames, setAgentNames] = useState<string[]>([]);
  const [targetAgent, setTargetAgent] = useState<string>("");
  const [skillNames, setSkillNames] = useState<string[]>([]);
  const [activeSkill, setActiveSkill] = useState<string>("");
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [pendingApproval, setPendingApproval] = useState<{
    token: string;
    tool: string;
    args: Record<string, any>;
    timeout: number;
  } | null>(null);
  const [updateInfo, setUpdateInfo] = useState<{
    version: string;
    notes: string;
    // opaque handle from Tauri updater
    update: any;
  } | null>(null);
  const [updateInstalling, setUpdateInstalling] = useState(false);
  const [updateProgress, setUpdateProgress] = useState(0);
  const [tokenStats, setTokenStats] = useState<Record<
    string,
    { calls: number; prompt: number; completion: number; total_ms: number }
  > | null>(null);
  const [tokenPanelOpen, setTokenPanelOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [darkMode, setDarkMode] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
  const [plannerSteps, setPlannerSteps] = useState<
    {
      agent: string;
      task: string;
      status: "running" | "done" | "error";
      output?: string;
    }[]
  >([]);
  const [dragOver, setDragOver] = useState(false);
  const [activeModel, setActiveModel] = useState("");
  const [toolLog, setToolLog] = useState<
    { type: "call" | "result" | "model"; name: string; detail: string; ts: number }[]
  >([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordChunksRef = useRef<Blob[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
  }, [darkMode]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setDarkMode(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    // Auto-check for app updates (non-blocking)
    (async () => {
      try {
        const { check } = await import("@tauri-apps/plugin-updater");
        const upd = await check();
        if (upd) {
          setUpdateInfo({
            version: upd.version,
            notes: upd.body || "",
            update: upd,
          });
        }
      } catch {
        // Not running under Tauri or network blocked — silently skip
      }
    })();
  }, []);

  async function installUpdate() {
    if (!updateInfo) return;
    setUpdateInstalling(true);
    setUpdateProgress(0);
    try {
      let total = 0;
      let received = 0;
      await updateInfo.update.downloadAndInstall((ev: any) => {
        if (ev?.event === "Started") {
          total = ev.data?.contentLength || 0;
        } else if (ev?.event === "Progress") {
          received += ev.data?.chunkLength || 0;
          if (total > 0) setUpdateProgress((received / total) * 100);
        } else if (ev?.event === "Finished") {
          setUpdateProgress(100);
        }
      });
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (e: any) {
      alert(`업데이트 실패: ${e?.message || e}`);
      setUpdateInstalling(false);
    }
  }

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
        try {
          const ags = await api.agents();
          setAgentNames(ags.filter((a) => a.active).map((a) => a.name));
        } catch {}
        try {
          const sks = await api.skills();
          setSkillNames(sks.map((s) => s.name));
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

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".code-copy")) return;
      const btn = document.createElement("button");
      btn.className = "code-copy";
      btn.textContent = "Copy";
      btn.addEventListener("click", async () => {
        const code = pre.querySelector("code");
        await navigator.clipboard.writeText(code?.textContent || pre.textContent || "");
        btn.textContent = "✓";
        setTimeout(() => (btn.textContent = "Copy"), 1500);
      });
      pre.style.position = "relative";
      pre.appendChild(btn);
    });
  }, [messages]);

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
    const ok = await confirmDialog(`세션 ${sid.slice(0, 8)}... 삭제할까요?`, {
      danger: true,
      okLabel: "삭제",
    });
    if (!ok) return;
    try {
      await api.deleteSession(sid);
      if (sid === activeSid) startNewSession();
      await refreshSessions();
    } catch (e: any) {
      alert(`세션 삭제 실패: ${e?.message || e}`);
    }
  }

  async function toggleRecord() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      recordChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) recordChunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(recordChunksRef.current, {
          type: mr.mimeType || "audio/webm",
        });
        if (blob.size === 0) return;
        try {
          const r = await api.stt(blob);
          if (r.text?.trim()) {
            setInput((prev) => (prev ? prev + " " : "") + r.text.trim());
          }
        } catch (e: any) {
          alert(`음성 인식 실패: ${e?.message || e}`);
        }
      };
      recorderRef.current = mr;
      mr.start();
      setRecording(true);
    } catch (e: any) {
      alert(`마이크 접근 실패: ${e?.message || e}`);
    }
  }

  const lastUserText = useRef("");

  function forkAt(turnIndex: number) {
    const kept = messages.slice(0, turnIndex);
    const sid = newSessionId();
    setActiveSid(sid);
    setMessages(kept);
    setStreamBuf("");
    setTools([]);
    refreshSessions();
  }

  async function regenerate() {
    if (streaming || messages.length < 2) return;
    const trimmed = [...messages];
    if (trimmed[trimmed.length - 1].role === "assistant") trimmed.pop();
    if (trimmed[trimmed.length - 1]?.role === "user") {
      lastUserText.current = trimmed[trimmed.length - 1].content
        .replace(/\n\n_\(첨부 이미지 \d+개\)_$/, "")
        .trim();
      trimmed.pop();
    }
    if (!lastUserText.current) return;
    setMessages(trimmed);
    setInput(lastUserText.current);
    requestAnimationFrame(() => {
      setInput("");
      const text = lastUserText.current;
      lastUserText.current = "";
      doSend(text);
    });
  }

  function stopStreaming() {
    abortRef.current?.abort();
  }

  async function doSend(text: string, imgs: string[] = []) {
    const userContent = imgs.length > 0 ? `${text}${text ? "\n\n" : ""}_(첨부 이미지 ${imgs.length}개)_` : text;
    setMessages((m) => [...m, { role: "user", content: userContent }]);
    setStreaming(true);
    setStreamBuf("");
    setTools([]);
    setPlannerSteps([]);
    setToolLog([]);
    const ac = new AbortController();
    abortRef.current = ac;
    refreshSessions();
    let buf = "";
    try {
      await api.sendMessage(activeSid, text, targetAgent || undefined, {
        onChunk: (t) => { buf += t; setStreamBuf(buf); },
        onModelCall: (d) => {
          const model = d?.model || "?";
          if (activeModel && model !== activeModel) {
            setToolLog((l) => [...l, { type: "model", name: model, detail: `모델 전환: ${activeModel} → ${model}`, ts: Date.now() }]);
          }
          setActiveModel(model);
        },
        onToolCall: (d) => {
          setTools((tt) => [...tt, `🔧 ${d?.name ?? "?"}`]);
          const argsStr = Object.entries(d?.args || {}).map(([k, v]) => `${k}=${typeof v === "string" ? v.slice(0, 80) : v}`).join(", ");
          setToolLog((l) => [...l, { type: "call", name: d?.name || "?", detail: argsStr, ts: Date.now() }]);
          if (d?.name === "delegate") {
            setPlannerSteps((s) => [...s, { agent: d?.args?.agent || "?", task: d?.args?.task || "", status: "running" }]);
          }
        },
        onToolResult: (d) => {
          const out = d?.error || (d?.output || "").slice(0, 200);
          setToolLog((l) => [...l, { type: "result", name: d?.name || "?", detail: out, ts: Date.now() }]);
          if (d?.name === "delegate") {
            setPlannerSteps((s) => {
              const next = [...s];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].status === "running") {
                  next[i] = { ...next[i], status: d?.error ? "error" : "done", output: d?.error || d?.output || "" };
                  break;
                }
              }
              return next;
            });
          }
        },
        onApproval: (d) => setPendingApproval(d),
        onFinal: (full) => { buf = full; setStreamBuf(full); },
      }, imgs, activeSkill || undefined, ac.signal);
      setMessages((m) => [...m, { role: "assistant", content: buf || "(빈 응답)" }]);
      if (ttsEnabled && buf) api.tts(buf).catch(() => {});
    } catch (e: any) {
      if (e?.name === "AbortError" || ac.signal.aborted) {
        if (buf) {
          setMessages((m) => [...m, { role: "assistant", content: buf + "\n\n_(중단됨)_" }]);
        }
      } else {
        setMessages((m) => [...m, { role: "assistant", content: `⚠ 오류: ${e}` }]);
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
      setStreamBuf("");
      setTools([]);
      await refreshSessions();
    }
  }

  async function sendMessage() {
    if ((!input.trim() && pendingImages.length === 0) || streaming) return;
    const text = input.trim();
    const imgs = [...pendingImages];
    setInput("");
    setPendingImages([]);
    await doSend(text, imgs);
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
    if (
      !(await confirmDialog(
        "모든 세션을 재인덱싱합니다 (임베딩 호출, 시간 소요). 계속?",
      ))
    )
      return;
    try {
      const r = await api.reindexSessions();
      alert(`${r.indexed}개 메시지 인덱싱됨.`);
    } catch (e: any) {
      alert(`인덱싱 실패: ${e.message || e}`);
    }
  }

  function attachFiles(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((f) => {
      if (f.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = () => {
          if (typeof reader.result === "string") {
            setPendingImages((arr) => [...arr, reader.result as string]);
          }
        };
        reader.readAsDataURL(f);
      } else if (
        f.type.startsWith("text/") ||
        /\.(txt|md|csv|json|xml|log|py|js|ts|html|css|yaml|yml|toml|sh|sql)$/i.test(f.name)
      ) {
        const reader = new FileReader();
        reader.onload = () => {
          if (typeof reader.result === "string") {
            const prefix = `[파일: ${f.name}]\n`;
            setInput((prev) => (prev ? prev + "\n\n" : "") + prefix + reader.result);
          }
        };
        reader.readAsText(f);
      } else if (f.name.endsWith(".pdf")) {
        const reader = new FileReader();
        reader.onload = () => {
          if (reader.result instanceof ArrayBuffer) {
            const b64 = btoa(
              new Uint8Array(reader.result).reduce((s, b) => s + String.fromCharCode(b), ""),
            );
            setInput(
              (prev) => (prev ? prev + "\n\n" : "") + `[PDF 첨부: ${f.name}, ${(f.size / 1024).toFixed(0)}KB — base64 인코딩됨]\ndata:application/pdf;base64,${b64.slice(0, 200)}...`,
            );
          }
        };
        reader.readAsArrayBuffer(f);
      }
    });
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    attachFiles(e.dataTransfer.files);
  }

  async function respondApproval(approved: boolean) {
    if (!pendingApproval) return;
    try {
      await api.resolveApproval(pendingApproval.token, approved);
    } catch (e) {
      console.error("approval 응답 실패:", e);
    } finally {
      setPendingApproval(null);
    }
  }

  function handleComposerPaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const items = e.clipboardData?.items;
    if (!items) return;
    let attached = 0;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = () => {
            if (typeof reader.result === "string") {
              setPendingImages((arr) => [...arr, reader.result as string]);
            }
          };
          reader.readAsDataURL(file);
          attached++;
        }
      }
    }
    if (attached > 0) e.preventDefault();
  }

  async function showTokens() {
    try {
      const stats = await api.tokenStats();
      setTokenStats(stats);
      setTokenPanelOpen(true);
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
      {updateInfo && (
        <div className="approval-overlay">
          <div className="approval-dialog">
            <div
              className="approval-title"
              style={{ color: "var(--primary)" }}
            >
              업데이트 가능: v{updateInfo.version}
            </div>
            {updateInfo.notes && (
              <pre
                className="approval-args"
                style={{ maxHeight: 220, fontSize: 12 }}
              >
                {updateInfo.notes}
              </pre>
            )}
            {updateInstalling ? (
              <>
                <div className="approval-hint">
                  다운로드 {updateProgress.toFixed(0)}%
                </div>
                <div
                  style={{
                    height: 6,
                    background: "var(--border)",
                    borderRadius: 3,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${updateProgress}%`,
                      height: "100%",
                      background: "var(--primary)",
                      transition: "width 0.2s",
                    }}
                  />
                </div>
              </>
            ) : (
              <>
                <div className="approval-hint">
                  설치 후 앱이 자동 재시작됩니다.
                </div>
                <div className="approval-actions">
                  <button
                    className="approval-deny"
                    onClick={() => setUpdateInfo(null)}
                  >
                    나중에
                  </button>
                  <button
                    className="approval-approve"
                    style={{ background: "var(--primary)" }}
                    onClick={installUpdate}
                  >
                    지금 설치
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
      {pendingApproval && (
        <div className="approval-overlay">
          <div className="approval-dialog">
            <div className="approval-title">위험 도구 실행 승인 필요</div>
            <div className="approval-tool">
              <code>{pendingApproval.tool}</code>
            </div>
            <pre className="approval-args">
              {JSON.stringify(pendingApproval.args, null, 2)}
            </pre>
            <div className="approval-hint">
              {pendingApproval.timeout}초 내 응답하지 않으면 자동 거부됩니다.
            </div>
            <div className="approval-actions">
              <button
                className="approval-deny"
                onClick={() => respondApproval(false)}
              >
                거부
              </button>
              <button
                className="approval-approve"
                onClick={() => respondApproval(true)}
              >
                승인
              </button>
            </div>
          </div>
        </div>
      )}
      {tokenPanelOpen && tokenStats && (
        <div
          className="approval-overlay"
          onClick={() => setTokenPanelOpen(false)}
        >
          <div
            className="approval-dialog"
            onClick={(e) => e.stopPropagation()}
            style={{ minWidth: 520 }}
          >
            <div className="approval-title">토큰 사용량 (모델별)</div>
            <TokenChart stats={tokenStats} />
            <div className="approval-actions">
              <button
                className="primary"
                onClick={() => setTokenPanelOpen(false)}
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}
      <aside className="sidebar">
        <div className="sidebar-head">
          <span className="brand">Raphael</span>
          <button onClick={startNewSession} title="새 세션">＋</button>
          <button
            title="대시보드"
            onClick={() => setView("dashboard")}
            style={{ marginLeft: 4 }}
          >
            📊
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
        {tagFilter && (
          <div className="tag-filter-bar">
            <span className="muted">필터:</span>
            <span className="session-tag on">#{tagFilter}</span>
            <button
              className="tag-filter-clear"
              onClick={() => setTagFilter("")}
              title="필터 해제"
            >
              ×
            </button>
          </div>
        )}
        <div className="sessions">
          {sessions.filter((s) => !tagFilter || (s.tags || []).includes(tagFilter)).length === 0 && (
            <div className="empty">{tagFilter ? "해당 태그의 세션 없음" : "세션 없음"}</div>
          )}
          {sessions
            .filter((s) => !tagFilter || (s.tags || []).includes(tagFilter))
            .map((s) => (
            <div
              key={s.id}
              className={`session ${s.id === activeSid ? "active" : ""}`}
              onClick={() => loadSession(s.id)}
            >
              <div className="session-title">{s.title || "(빈 세션)"}</div>
              {s.tags && s.tags.length > 0 && (
                <div className="session-tags">
                  {s.tags.map((t) => (
                    <span
                      key={t}
                      className={`session-tag ${tagFilter === t ? "on" : ""}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setTagFilter(tagFilter === t ? "" : t);
                      }}
                      title={`태그 "${t}"로 필터`}
                    >
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
                  title="삭제"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
        <SidebarStats healthy={healthy} />
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

      <main
        className={`chat ${dragOver ? "drag-over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return;
          setDragOver(false);
        }}
        onDrop={handleDrop}
      >
        {dragOver && (
          <div className="drop-overlay">파일을 여기에 놓으세요</div>
        )}
        <div className="chat-toolbar">
          <span className="muted" style={{ fontSize: 12 }}>
            {activeSid ? `session: ${activeSid}` : "new session"}
          </span>
          <label className="muted" style={{ fontSize: 12, marginLeft: 16 }}>
            에이전트:
            <select
              value={targetAgent}
              onChange={(e) => setTargetAgent(e.target.value)}
              style={{
                marginLeft: 4,
                fontSize: 12,
                padding: "2px 6px",
                border: "1px solid #d4d7df",
                borderRadius: 4,
              }}
            >
              <option value="">(자동)</option>
              {agentNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
            스킬:
            <select
              value={activeSkill}
              onChange={(e) => setActiveSkill(e.target.value)}
              style={{
                marginLeft: 4,
                fontSize: 12,
                padding: "2px 6px",
                border: "1px solid #d4d7df",
                borderRadius: 4,
              }}
            >
              <option value="">(없음)</option>
              {skillNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
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
                {m.role === "assistant" && <InlineGeneratedImage text={m.content} />}
              </div>
              {m.role === "user" && i > 0 && !streaming && (
                <button
                  className="fork-btn"
                  onClick={() => forkAt(i)}
                  title="여기서 분기 — 이 시점까지만 유지하고 새 세션 시작"
                >
                  ↗ 분기
                </button>
              )}
              {m.role === "assistant" && (
                <div className="msg-actions">
                  <CopyButton text={m.content} />
                  {i === messages.length - 1 && !streaming && (
                    <button className="copy-btn" onClick={regenerate} title="재생성">
                      ♻
                    </button>
                  )}
                  <FeedbackBar
                    session={activeSid}
                    agent={targetAgent}
                    question={i > 0 ? messages[i - 1].content : ""}
                    response={m.content}
                  />
                </div>
              )}
            </div>
          ))}
          {plannerSteps.length > 0 && <PlannerSteps steps={plannerSteps} />}
          {toolLog.length > 0 && streaming && <ToolLogPanel log={toolLog} />}
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
        {pendingImages.length > 0 && (
          <div className="pending-images">
            {pendingImages.map((img, i) => (
              <div key={i} className="pending-image">
                <img src={img} alt={`첨부 ${i + 1}`} />
                <button
                  onClick={() =>
                    setPendingImages(pendingImages.filter((_, idx) => idx !== i))
                  }
                  title="제거"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="composer">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              attachFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={handleComposerPaste}
            placeholder={healthy ? "메시지 입력 (Enter 전송, Shift+Enter 줄바꿈, 파일은 드래그앤드롭)" : "데몬 대기 중..."}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            disabled={!healthy}
            rows={3}
          />
          <div className="composer-actions">
            <button
              className={`tool-btn ${recording ? "recording" : ""}`}
              onClick={toggleRecord}
              title={recording ? "녹음 중지 (전사)" : "음성 입력"}
              disabled={streaming}
            >
              {recording ? "⏹" : "🎙"}
            </button>
            <button
              className={`tool-btn tts-toggle ${ttsEnabled ? "on" : "off"}`}
              onClick={() => setTtsEnabled(!ttsEnabled)}
              title={ttsEnabled ? "응답 음성 ON" : "응답 음성 OFF"}
            >
              {ttsEnabled ? "🔊" : "🔇"}
            </button>
            {streaming ? (
              <button className="send-btn stop" onClick={stopStreaming}>
                중지
              </button>
            ) : (
              <button
                className="send-btn"
                onClick={sendMessage}
                disabled={
                  !healthy ||
                  (!input.trim() && pendingImages.length === 0)
                }
              >
                전송
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function FeedbackBar({
  session,
  agent,
  question,
  response,
}: {
  session: string;
  agent: string;
  question: string;
  response: string;
}) {
  const [sent, setSent] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(score: number) {
    if (busy || sent !== null) return;
    setBusy(true);
    try {
      await api.recordFeedback({
        session,
        agent,
        question,
        response,
        score,
      });
      setSent(score);
    } catch {
      /* swallow */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="feedback-bar">
      <button
        className={`fb ${sent === 1 ? "on" : ""}`}
        onClick={() => send(1)}
        disabled={busy || sent !== null}
        title="좋은 응답"
      >
        👍
      </button>
      <button
        className={`fb ${sent === -1 ? "on" : ""}`}
        onClick={() => send(-1)}
        disabled={busy || sent !== null}
        title="나쁜 응답"
      >
        👎
      </button>
      {sent !== null && <span className="fb-thanks">기록됨</span>}
    </div>
  );
}

function TokenChart({
  stats,
}: {
  stats: Record<
    string,
    { calls: number; prompt: number; completion: number; total_ms: number }
  >;
}) {
  const entries = Object.entries(stats);
  if (entries.length === 0) {
    return <div className="muted">아직 호출 기록이 없습니다.</div>;
  }
  const max = Math.max(
    ...entries.map(([, s]) => s.prompt + s.completion),
    1,
  );
  const totalCalls = entries.reduce((sum, [, s]) => sum + s.calls, 0);
  const totalTokens = entries.reduce(
    (sum, [, s]) => sum + s.prompt + s.completion,
    0,
  );
  const totalMs = entries.reduce((sum, [, s]) => sum + s.total_ms, 0);

  return (
    <div className="token-chart">
      <div className="token-totals">
        <span>총 {totalCalls.toLocaleString()}회</span>
        <span>{totalTokens.toLocaleString()} tokens</span>
        <span>{(totalMs / 1000).toFixed(1)}s</span>
      </div>
      <div className="token-rows">
        {entries.map(([model, s]) => {
          const total = s.prompt + s.completion;
          const promptPct = (s.prompt / max) * 100;
          const completionPct = (s.completion / max) * 100;
          return (
            <div key={model} className="token-row">
              <div className="token-row-head">
                <code>{model}</code>
                <span className="muted">
                  {s.calls}회 · {total.toLocaleString()} tok ·{" "}
                  {(s.total_ms / 1000).toFixed(1)}s
                </span>
              </div>
              <div className="token-bar">
                <div
                  className="token-bar-prompt"
                  style={{ width: `${promptPct}%` }}
                  title={`prompt ${s.prompt.toLocaleString()}`}
                />
                <div
                  className="token-bar-completion"
                  style={{ width: `${completionPct}%` }}
                  title={`completion ${s.completion.toLocaleString()}`}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="token-legend">
        <span className="legend-prompt"></span> prompt
        <span className="legend-completion" style={{ marginLeft: 12 }}></span>{" "}
        completion
      </div>
    </div>
  );
}

function PlannerSteps({
  steps,
}: {
  steps: {
    agent: string;
    task: string;
    status: "running" | "done" | "error";
    output?: string;
  }[];
}) {
  return (
    <div className="planner-steps">
      <div className="planner-steps-head">
        🧭 Planner — {steps.length}개 단계
      </div>
      {steps.map((s, i) => (
        <div key={i} className={`planner-step planner-${s.status}`}>
          <div className="planner-step-head">
            <span className="planner-step-num">#{i + 1}</span>
            <code className="planner-step-agent">{s.agent}</code>
            <span className="planner-step-status">
              {s.status === "running"
                ? "⏳ 진행 중"
                : s.status === "done"
                  ? "✓ 완료"
                  : "✗ 실패"}
            </span>
          </div>
          <div className="planner-step-task">{s.task}</div>
          {s.output && (
            <details className="planner-step-output">
              <summary>결과 보기</summary>
              <pre>{s.output}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }

  return (
    <button className="copy-btn" onClick={copy} title="복사">
      {copied ? "✓" : "📋"}
    </button>
  );
}

function SidebarStats({ healthy }: { healthy: boolean }) {
  const [stats, setStats] = useState<{
    calls: number;
    tokens: number;
  } | null>(null);

  useEffect(() => {
    if (!healthy) return;
    let alive = true;
    async function poll() {
      try {
        const s = await api.tokenStats();
        if (!alive) return;
        let calls = 0;
        let tokens = 0;
        for (const v of Object.values(s)) {
          calls += v.calls;
          tokens += v.prompt + v.completion;
        }
        setStats({ calls, tokens });
      } catch {}
    }
    poll();
    const id = setInterval(poll, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [healthy]);

  if (!stats || !stats.calls) return null;
  return (
    <div className="sidebar-stats">
      <span>{stats.calls.toLocaleString()} calls</span>
      <span>{stats.tokens >= 1000 ? `${(stats.tokens / 1000).toFixed(1)}k` : stats.tokens} tok</span>
    </div>
  );
}

function ToolLogPanel({
  log,
}: {
  log: { type: "call" | "result" | "model"; name: string; detail: string; ts: number }[];
}) {
  if (log.length === 0) return null;
  return (
    <details className="tool-log" open>
      <summary>
        행동 과정 ({log.filter((e) => e.type === "call").length}개 도구 호출)
      </summary>
      <div className="tool-log-entries">
        {log.map((e, i) => (
          <div key={i} className={`tool-log-entry tool-log-${e.type}`}>
            <span className="tool-log-icon">
              {e.type === "call" ? "🔧" : e.type === "result" ? "📄" : "🔄"}
            </span>
            <span className="tool-log-name">{e.name}</span>
            <span className="tool-log-detail">{e.detail}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

function InlineGeneratedImage({ text }: { text: string }) {
  const match = text.match(/저장 경로:\s*(.+\.png)/);
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!match) return;
    const path = match[1].trim();
    (async () => {
      try {
        const resp = await fetch(
          `http://127.0.0.1:8765/file-preview?path=${encodeURIComponent(path)}`,
        );
        if (resp.ok) {
          const blob = await resp.blob();
          setSrc(URL.createObjectURL(blob));
        }
      } catch {
        // fallback: try as local file URL (Tauri allows file:// in some configs)
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  if (!match || !src) return null;
  return (
    <div className="generated-image">
      <img src={src} alt="generated" style={{ maxWidth: "100%", borderRadius: 8, marginTop: 8 }} />
    </div>
  );
}
