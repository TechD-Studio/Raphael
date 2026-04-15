// Raphael 데몬 API 클라이언트
const BASE = "http://127.0.0.1:8765";

export interface SessionMeta {
  id: string;
  agent: string;
  title: string;
  turns: number;
  mtime: number;
}

export interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface SessionDetail {
  id: string;
  agent: string;
  conversation: Message[];
}

export interface AgentInfo {
  name: string;
  description: string;
  active: boolean;
  model: string | null;
  tools: string | string[];
}

export interface AgentDetail {
  name: string;
  description: string;
  model: string | null;
  tools: string[];
  system_prompt: string;
  default_enabled: boolean;
  active: boolean;
}

export interface AgentUpsert {
  name: string;
  description?: string;
  model?: string | null;
  tools?: string[];
  system_prompt?: string;
  default_enabled?: boolean;
  active?: boolean;
}

export interface ModelsInfo {
  current: string;
  available: string[];
}

export interface AbResultSummary {
  file: string;
  scenario_id: number | null;
  title: string;
  mtime: number;
  models: string[];
  success_count: number;
  total: number;
}

export interface AbRunResult {
  model: string;
  success: boolean;
  duration?: number;
  response_len?: number;
  final_model?: string;
  error?: string;
}

export interface AbResultDetail {
  scenario_id: number;
  title: string;
  results: AbRunResult[];
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export const api = {
  health: () => jget<{ ok: boolean; version: string }>("/healthz"),
  sessions: () => jget<SessionMeta[]>("/sessions"),
  session: (id: string) => jget<SessionDetail>(`/sessions/${id}`),
  deleteSession: async (id: string) => {
    const r = await fetch(`${BASE}/sessions/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status}`);
  },
  agents: () => jget<AgentInfo[]>("/agents"),
  agent: (name: string) => jget<AgentDetail>(`/agents/${encodeURIComponent(name)}`),
  upsertAgent: (payload: AgentUpsert) => jpost<{ ok: boolean; name: string }>("/agents", payload),
  deleteAgent: async (name: string) => {
    const r = await fetch(`${BASE}/agents/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  toggleAgent: (name: string, active: boolean) =>
    jpost<{ name: string; active: boolean }>(`/agents/${encodeURIComponent(name)}/toggle`, { active }),
  models: () => jget<ModelsInfo>("/models"),
  useModel: (key: string) => jpost<{ current: string }>("/models/use", { key }),

  exportSession: (id: string, fmt: "markdown" | "json") =>
    jget<{ format: string; content: string; filename: string }>(
      `/sessions/${encodeURIComponent(id)}/export?fmt=${fmt}`,
    ),
  tokenStats: () =>
    jget<Record<string, { calls: number; prompt: number; completion: number; total_ms: number }>>(
      "/models/token-stats",
    ),

  abResults: () => jget<AbResultSummary[]>("/ab-results"),
  abResult: (name: string) =>
    jget<AbResultDetail>(`/ab-results/${encodeURIComponent(name)}`),

  serverSettings: () =>
    jget<{ host: string; port: number; timeout: number }>("/settings/server"),
  saveServerSettings: (payload: { host: string; port: number; timeout: number }) =>
    jpost<{ ok: boolean; host: string; port: number; timeout: number }>(
      "/settings/server",
      payload,
    ),

  // SSE 메시지 전송 — onChunk(token), onFinal(text), onDone()
  async sendMessage(
    sid: string,
    content: string,
    agent: string | undefined,
    handlers: {
      onChunk?: (text: string) => void;
      onFinal?: (text: string) => void;
      onError?: (msg: string) => void;
      onDone?: () => void;
      onToolCall?: (data: any) => void;
    },
  ) {
    const r = await fetch(`${BASE}/sessions/${sid}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, agent }),
    });
    if (!r.ok || !r.body) throw new Error(`${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE: 빈 줄 단위로 분리, 각 메시지는 "data: ...\n"
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const dataLine = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        try {
          const ev = JSON.parse(dataLine.slice(5).trim());
          switch (ev.type) {
            case "token_chunk":
              handlers.onChunk?.(ev.data?.text ?? "");
              break;
            case "tool_call":
              handlers.onToolCall?.(ev.data);
              break;
            case "final":
              handlers.onFinal?.(ev.data?.text ?? "");
              break;
            case "error":
              handlers.onError?.(ev.data?.message ?? "");
              break;
            case "done":
              handlers.onDone?.();
              return;
          }
        } catch {
          // ignore parse error
        }
      }
    }
    handlers.onDone?.();
  },
};

export function newSessionId(): string {
  return Math.random().toString(16).slice(2, 14);
}
