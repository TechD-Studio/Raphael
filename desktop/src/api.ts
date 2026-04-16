// Raphael 데몬 API 클라이언트
const BASE = "http://127.0.0.1:8765";

export interface SessionMeta {
  id: string;
  agent: string;
  title: string;
  turns: number;
  mtime: number;
  tags?: string[];
}

export interface SessionHit {
  session_id: string;
  role: string;
  content: string;
  distance: number;
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

export interface ProfileFact {
  id: string;
  text: string;
  added: string;
  source: string;
}

export interface PoolServer {
  name: string;
  host: string;
  port: number;
  weight: number;
  models: string[];
  timeout: number;
}

export interface HookWatch {
  path: string;
  patterns: string[];
  events: string[];
  agent: string;
  prompt: string;
  debounce_seconds: number;
}

export interface SkillInfo {
  name: string;
  description: string;
  agent: string;
  tags: string[];
}

export interface SkillDetail extends SkillInfo {
  prompt: string;
}

export interface SkillUpsert {
  name: string;
  description?: string;
  prompt: string;
  agent?: string;
  tags?: string[];
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

export interface ActivityEntry {
  ts?: string;
  type?: string;
  agent?: string;
  session?: string;
  model?: string;
  data?: Record<string, unknown>;
}

export interface AuditEntry {
  ts?: string;
  type?: string;
  agent?: string;
  session?: string;
  data?: Record<string, unknown>;
  prev?: string;
  hash?: string;
}

export interface Checkpoint {
  id: string;
  operation: string;
  target: string;
  backup_path: string | null;
  created: string;
  note: string;
}

export interface RoutingRule {
  agent?: string;
  min_messages?: number;
  token_estimate_gt?: number;
  token_estimate_lt?: number;
  contains_any?: string[];
  default?: boolean;
  prefer_model?: string;
  prefer_agent?: string;
  note?: string;
}

export interface RoutingConfig {
  strategy: "auto" | "manual";
  rules: RoutingRule[];
}

export interface FailureSummary {
  file: string;
  agent: string;
  model: string;
  reason: string;
  user_input: string;
  mtime: number;
  turns: number;
}

export interface FailureDetail {
  agent: string;
  model: string;
  reason: string;
  user_input: string;
  conversation: { role: string; content: string }[];
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
  searchSessions: (query: string, n_results = 10) =>
    jpost<SessionHit[]>("/sessions/search", { query, n_results }),
  reindexSessions: () =>
    jpost<{ indexed: number }>("/sessions/reindex", {}),
  deleteSession: async (id: string) => {
    const r = await fetch(`${BASE}/sessions/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status}`);
  },
  agents: () => jget<AgentInfo[]>("/agents"),
  agentRecommendations: (limit = 3) =>
    jget<{ name: string; reason: string }[]>(
      `/agents/recommendations?limit=${limit}`,
    ),
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


  activity: (tail = 200, session = "") =>
    jget<ActivityEntry[]>(
      `/activity?tail=${tail}${session ? `&session=${encodeURIComponent(session)}` : ""}`,
    ),

  audit: (tail = 200) => jget<AuditEntry[]>(`/audit?tail=${tail}`),
  auditVerify: () =>
    jget<{ ok: boolean; count: number; message: string }>("/audit/verify"),

  checkpoints: (limit = 100) =>
    jget<Checkpoint[]>(`/checkpoints?limit=${limit}`),
  restoreCheckpoint: (id: string) =>
    jpost<{ ok: boolean; message: string }>("/checkpoints/restore", { id }),
  cleanupCheckpoints: (days = 7) =>
    jpost<{ deleted: number; days: number }>("/checkpoints/cleanup", { days }),

  failures: () => jget<FailureSummary[]>("/failures"),
  failure: (name: string) =>
    jget<FailureDetail>(`/failures/${encodeURIComponent(name)}`),
  deleteFailure: async (name: string) => {
    const r = await fetch(
      `${BASE}/failures/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    );
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
  clearFailures: async () => {
    const r = await fetch(`${BASE}/failures`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  mcpServers: () =>
    jget<{
      configured: any[];
      runtime_tools: { server: string; tool: string; description: string }[];
    }>("/mcp/servers"),
  mcpCall: (server: string, tool: string, args: Record<string, unknown>) =>
    jpost<{ ok: boolean; result: string }>("/mcp/call", { server, tool, args }),

  bots: () =>
    jget<{ name: string; running: boolean; pid: number | null; exit_code: number | null }[]>(
      "/bots",
    ),
  startBot: (name: string) =>
    jpost<{ ok: boolean; name: string; pid: number }>("/bots/start", { name }),
  stopBot: (name: string) =>
    jpost<{ ok: boolean; name: string }>("/bots/stop", { name }),
  plugins: () =>
    jget<{
      tools: { name: string; value: string }[];
      agents: { name: string; value: string }[];
      error?: string;
    }>("/plugins"),
  healthPanel: () =>
    jget<{
      ok: boolean;
      agents: string[];
      models_available: string[];
      current_model: string;
      total_calls: number;
      total_tokens: number;
      per_model: Record<
        string,
        { calls: number; prompt: number; completion: number; total_ms: number }
      >;
    }>("/health-panel"),
  feedbackStats: () =>
    jget<{ total: number; positive: number; negative: number; neutral: number }>(
      "/feedback/stats",
    ),
  stt: async (blob: Blob): Promise<{ text: string }> => {
    const fd = new FormData();
    fd.append("audio", blob, "audio.webm");
    const r = await fetch(`${BASE}/stt`, { method: "POST", body: fd });
    if (!r.ok) throw new Error(`STT ${r.status}`);
    return r.json();
  },
  tts: (text: string) =>
    jpost<{ ok: boolean; message: string }>("/tts", { text }),
  recordFeedback: (payload: {
    session?: string;
    agent?: string;
    question?: string;
    response?: string;
    score: number;
    comment?: string;
  }) => jpost<{ ok: boolean }>("/feedback", payload),
  systemUpdate: () =>
    jpost<{
      ok: boolean;
      pull?: string;
      pip?: string;
      note?: string;
      error?: string;
      stage?: string;
      output?: string;
    }>("/system/update", {}),

  escalation: () =>
    jget<{ ladder: string[]; available: string[] }>("/settings/escalation"),
  saveEscalation: (ladder: string[]) =>
    jpost<{ ok: boolean; ladder: string[] }>("/settings/escalation", { ladder }),

  finetuneCheck: () =>
    jget<{ mlx_lm: boolean; llama_cpp: boolean; ollama: boolean }>("/finetune/check"),
  finetunePrepare: (vault_path: string) =>
    jpost<{ ok: boolean; total_pairs?: number; train?: number; valid?: number; error?: string }>(
      "/finetune/prepare", { vault_path },
    ),
  finetuneTrain: (params: {
    base_model?: string; iters?: number; batch_size?: number;
    lora_layers?: number; learning_rate?: number;
  }) =>
    jpost<{ ok: boolean; adapter_name?: string; error?: string; output?: string }>(
      "/finetune/train", params,
    ),
  finetuneBuild: (adapter_name: string, model_name?: string) =>
    jpost<{ ok: boolean; model_name?: string; error?: string; stage?: string }>(
      "/finetune/build", { adapter_name, model_name },
    ),
  finetuneModels: () =>
    jget<{ name: string; base_model: string; iters: number; created: string }[]>(
      "/finetune/models",
    ),
  finetuneDelete: async (name: string) => {
    const r = await fetch(`${BASE}/finetune/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  imageBackends: () =>
    jget<{ id: string; name: string; available: boolean; model: string; cost: string }[]>(
      "/image/backends",
    ),
  imageGenSettings: () =>
    jget<{ backend: string; local_model: string; openai_model: string; default_size: string }>(
      "/settings/image-gen",
    ),
  saveImageGenSettings: (payload: {
    backend: string;
    local_model?: string;
    openai_model?: string;
    default_size?: string;
  }) => jpost<{ ok: boolean }>("/settings/image-gen", payload),
  generateImage: (payload: {
    prompt: string;
    negative_prompt?: string;
    size?: string;
    backend?: string;
  }) =>
    jpost<{
      ok: boolean;
      backend?: string;
      model?: string;
      path?: string;
      data_url?: string;
      revised_prompt?: string;
      error?: string;
    }>("/image/generate", payload),

  skills: () => jget<SkillInfo[]>("/skills"),
  skill: (name: string) =>
    jget<SkillDetail>(`/skills/${encodeURIComponent(name)}`),
  upsertSkill: (payload: SkillUpsert) =>
    jpost<{ ok: boolean; name: string }>("/skills", payload),
  deleteSkill: async (name: string) => {
    const r = await fetch(
      `${BASE}/skills/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    );
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  allowedPaths: () =>
    jget<{ allowed_paths: string[] }>("/settings/allowed-paths"),
  saveAllowedPaths: (allowed_paths: string[]) =>
    jpost<{ ok: boolean; count: number; allowed_paths: string[] }>(
      "/settings/allowed-paths",
      { allowed_paths },
    ),

  listSecrets: () =>
    jget<{ keys: { key: string; source: string; in_keychain: boolean }[] }>(
      "/secrets",
    ),
  setSecret: (key: string, value: string) =>
    jpost<{ ok: boolean; key: string; backend: string }>("/secrets", {
      key,
      value,
    }),
  deleteSecret: async (key: string) => {
    const r = await fetch(
      `${BASE}/secrets/${encodeURIComponent(key)}`,
      { method: "DELETE" },
    );
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  ragStatus: () =>
    jget<{
      vault_path: string;
      doc_count: number;
      embedding_model: string;
      chroma_db_path: string;
      error?: string;
    }>("/rag/status"),
  setRagVault: (vault_path: string) =>
    jpost<{ ok: boolean; vault_path: string }>("/rag/vault", { vault_path }),
  ragSync: () =>
    jpost<{ added: number; updated: number; deleted: number; unchanged: number }>(
      "/rag/sync",
      {},
    ),
  ragReindex: () => jpost<{ indexed: number }>("/rag/reindex", {}),

  routingSettings: () => jget<RoutingConfig>("/settings/routing"),
  saveRoutingSettings: (payload: RoutingConfig) =>
    jpost<{ ok: boolean; strategy: string; rules_count: number }>(
      "/settings/routing",
      payload,
    ),

  serverSettings: () =>
    jget<{ host: string; port: number; timeout: number }>("/settings/server"),
  saveServerSettings: (payload: { host: string; port: number; timeout: number }) =>
    jpost<{ ok: boolean; host: string; port: number; timeout: number }>(
      "/settings/server",
      payload,
    ),

  profile: () => jget<{ facts: ProfileFact[] }>("/profile"),
  addFact: (text: string, source = "user") =>
    jpost<ProfileFact>("/profile", { text, source }),
  deleteFact: async (id: string) => {
    const r = await fetch(`${BASE}/profile/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
  clearProfile: async () => {
    const r = await fetch(`${BASE}/profile`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  poolStatus: () =>
    jget<{ configured: PoolServer[]; health: any[] }>("/pool"),
  savePool: (servers: PoolServer[]) =>
    jpost<{ ok: boolean; count: number }>("/pool", { servers }),
  installedModels: () =>
    jget<{ host: string; models: string[]; error?: string }>(
      "/models/installed",
    ),
  pullModel: (name: string) =>
    jpost<{ ok: boolean; name: string; result: any }>("/models/pull", { name }),

  hookWatches: () =>
    jget<{ watches: HookWatch[] }>("/hooks/watches"),
  saveHookWatches: (watches: HookWatch[]) =>
    jpost<{ ok: boolean; count: number }>("/hooks/watches", { watches }),

  convertFile: (payload: {
    operation: "md_to_html" | "md_to_pdf" | "csv_to_chart" | "image_resize";
    src: string;
    dst?: string;
    x?: string;
    y?: string;
    width?: number;
  }) =>
    jpost<{ ok: boolean; operation: string; output: string }>(
      "/convert",
      payload,
    ),

  takeScreenshot: () =>
    jpost<{ data_url: string; size: number }>("/screenshot", {}),

  resolveApproval: (token: string, approved: boolean) =>
    jpost<{ ok: boolean; token: string; approved: boolean }>(
      `/approvals/${encodeURIComponent(token)}`,
      { approved },
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
      onToolResult?: (data: any) => void;
      onModelCall?: (data: { model: string; iteration: number }) => void;
      onApproval?: (data: {
        token: string;
        tool: string;
        args: Record<string, any>;
        timeout: number;
      }) => void;
    },
    images: string[] = [],
    skill: string | undefined = undefined,
    signal?: AbortSignal,
  ) {
    const r = await fetch(`${BASE}/sessions/${sid}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, agent, images, skill }),
      signal,
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
            case "tool_result":
              handlers.onToolResult?.(ev.data);
              break;
            case "model_call_start":
              handlers.onModelCall?.(ev.data);
              break;
            case "approval_required":
              handlers.onApproval?.(ev.data);
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
