export type Session = {
  id: string;
  name: string;
  attached: boolean;
  windows: number;
  current_command: string;
  activity_at: string;
  hidden: boolean;
};

let csrfToken = "";

// Chiamato da qualunque richiesta HTTP (Console inclusa, non solo la lista
// sessioni) quando il cookie di sessione non è più valido — es. scaduto
// mentre l'app resta aperta a lungo (scheda in background/dormiente).
// Punto unico invece di doverlo ripetere in ogni singolo punto di chiamata.
let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(value: unknown): string {
  if (value instanceof ApiError) {
    if (value.status === 401) return "Sessione scaduta: accedi nuovamente.";
    if (value.status === 404 && value.message === "Session not found") {
      return "La sessione tmux non esiste più.";
    }
    if (value.status === 409 && value.message === "Session name already exists") {
      return "Esiste già una sessione con questo nome.";
    }
    if (
      value.status === 409 &&
      value.message === "Refusing to terminate the reserved keepalive session"
    ) {
      return "Questa sessione è riservata al servizio e non può essere terminata.";
    }
    if (value.status === 429) {
      return "Troppe richieste ravvicinate. Attendi qualche secondo e riprova.";
    }
    if (value.status === 502 || value.status === 503) {
      return "Il backend o tmux non è disponibile. Riprova tra poco.";
    }
    return value.message;
  }
  if (value instanceof TypeError) {
    return "Backend non raggiungibile. Controlla la connessione.";
  }
  return value instanceof Error ? value.message : String(value);
}

async function request(path: string, init?: RequestInit) {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(!(init?.body instanceof Blob) ? { "Content-Type": "application/json" } : {}),
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch { /* keep status fallback */ }
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(response.status, detail);
  }
  return response;
}

export type Role = "admin" | "operator" | "viewer";
export type Identity = { username: string; role: Role };

export async function login(username: string, password: string): Promise<Identity> {
  const response = await request("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const body = await response.json();
  csrfToken = body.csrf_token;
  return { username: body.username, role: body.role };
}

export async function restoreSession(): Promise<Identity> {
  const response = await request("/api/v1/auth/session");
  const body = await response.json();
  csrfToken = body.csrf_token;
  return { username: body.username, role: body.role };
}

export async function logout(): Promise<void> {
  await request("/api/v1/auth/logout", { method: "POST" });
  csrfToken = "";
}

export type UserAccount = {
  username: string;
  role: Role;
  active: boolean;
  created_at: string;
};

export async function listUsers(): Promise<UserAccount[]> {
  const response = await request("/api/v1/users");
  return (await response.json()).users;
}

export type AuditEvent = {
  id: number;
  actor: string;
  action: string;
  target: string;
  outcome: number;
  created_at: string;
};

export async function listAudit(limit = 200): Promise<AuditEvent[]> {
  const response = await request(`/api/v1/audit?limit=${limit}`);
  return (await response.json()).events;
}

export type Backup = {
  id: string;
  created_at: string;
  size: number;
  sha256: string;
  files: number;
};

export async function listBackups(): Promise<Backup[]> {
  const response = await request("/api/v1/backups");
  return (await response.json()).backups;
}

export async function createBackup(): Promise<Backup> {
  const response = await request("/api/v1/backups", { method: "POST" });
  return response.json();
}

export async function deleteBackup(id: string): Promise<void> {
  await request(`/api/v1/backups/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmed: true }),
  });
}

export function backupDownloadUrl(id: string): string {
  return `/api/v1/backups/${encodeURIComponent(id)}/download`;
}

export async function createUser(
  username: string,
  password: string,
  role: Role,
): Promise<UserAccount> {
  const response = await request("/api/v1/users", {
    method: "POST",
    body: JSON.stringify({ username, password, role }),
  });
  return response.json();
}

export async function setUserActive(username: string, active: boolean): Promise<UserAccount> {
  const response = await request(`/api/v1/users/${encodeURIComponent(username)}/status`, {
    method: "POST",
    body: JSON.stringify({ active }),
  });
  return response.json();
}

export async function listSessions(): Promise<Session[]> {
  const response = await request("/api/v1/sessions");
  return (await response.json()).sessions;
}

export type AgentState =
  | "active"
  | "idle"
  | "waiting_input"
  | "waiting_authorization"
  | "unknown";

export type AgentStatus = {
  session_id: string;
  provider: "codex" | "claude" | "antigravity" | "opencode";
  state: AgentState;
  detail: string;
  permission_state:
    | "restricted"
    | "standard"
    | "elevated"
    | "bypass"
    | "plan"
    | "ask"
    | "auto"
    | "manual"
    | "accept_edits"
    | "dont_ask"
    | "unknown";
  permission_detail: string;
  context_used_percent: number | null;
  summary: string | null;
};

export async function listAgentStatuses(): Promise<AgentStatus[]> {
  const response = await request("/api/v1/agent-statuses");
  return (await response.json()).statuses;
}

export type AppConfig = {
  allowed_roots: string[];
  workspace_presets: Record<string, string>;
  max_upload_bytes?: number;
  upload_allowed_extensions?: string[];
  claude_history_enabled: boolean;
  host_observability_enabled: boolean;
  rate_limit_fresh_enabled: boolean;
  session_usage_enabled: boolean;
  opencode_history_enabled?: boolean;
  // Drill-down "fase C" (BH-04): flag dedicato e indipendente da
  // claude_history_enabled/session_usage_enabled (GATE-BH-04). `false` per i
  // ruoli non-admin, come host_observability_enabled.
  session_timeline_enabled: boolean;
  // Enunciazione di fatto per il ruolo admin (BH-03): quali funzioni
  // opzionali sono accese ora. `null` per i ruoli non-admin.
  optional_features: Record<string, boolean> | null;
};

export type HostStatus = "ok" | "warning" | "critical" | "unknown";
export type HostComponent = { status: HostStatus; reasons: string[] };

export type HostProcessItem = {
  pid: number;
  name: string;
  label: string | null;
  rss_bytes: number;
  swap_bytes?: number | null;
  age_seconds: number;
};

type HostObservabilitySnapshotBase = HostComponent & {
  collected_at: string;
  duration_ms: number;
  memory: HostComponent & {
    total_bytes: number | null;
    available_bytes: number | null;
    available_percent: number | null;
    swap_total_bytes: number | null;
    swap_used_bytes: number | null;
    swap_used_percent: number | null;
  };
  load: HostComponent & {
    one: number | null;
    five: number | null;
    fifteen: number | null;
    cpu_count: number | null;
    normalized_one: number | null;
  };
  filesystems: HostComponent & {
    items: Array<HostComponent & {
      label: string;
      total_bytes: number | null;
      available_bytes: number | null;
      used_percent: number | null;
    }>;
  };
  processes: HostComponent & {
    top: HostProcessItem[];
    groups: Array<{
      name: string;
      label: string | null;
      count: number;
      rss_bytes: number;
      // Assente su v1 e sugli snapshot v2 prodotti da collector precedenti:
      // `null`/assente vuol dire non accertato, non "zero swap".
      swap_bytes?: number | null;
      oldest_age_seconds: number;
      policy_status?: "not_configured" | "within_limits" | "violated";
    }>;
    scanned: number;
    skipped: number;
    inaccessible: number;
    truncated: boolean;
  };
  docker: HostComponent & {
    available: boolean;
    problematic: Array<{
      label: string;
      status: "warning" | "critical";
      reason: string;
    }>;
    unmapped_problematic_count: number;
  };
};

type HostListenerBase = {
  port: number;
  process_name: string | null;
  process_label: string | null;
  status: "ok" | "warning" | "critical";
};

export type HostObservabilitySnapshotV1 = HostObservabilitySnapshotBase & {
  schema_version: 1;
  listeners: HostComponent & {
    items: Array<HostListenerBase & {
      address_scope: "loopback" | "tailscale" | "wildcard" | "other";
      expected: boolean;
    }>;
    truncated: boolean;
  };
};

export type HostObservabilitySnapshotV2 = HostObservabilitySnapshotBase & {
  schema_version: 2;
  memory: HostObservabilitySnapshotBase["memory"] & {
    swap_io_sample: {
      available: boolean;
      duration_ms: number | null;
      pages_in_delta: number | null;
      pages_out_delta: number | null;
    };
  };
  processes: HostObservabilitySnapshotBase["processes"] & {
    // Classifica per swap: un processo quasi interamente paginato ha poca
    // memoria residente e non comparirebbe mai in `top`.
    top_swap?: HostProcessItem[];
    swap_attributed_bytes?: number | null;
  };
  docker: HostObservabilitySnapshotBase["docker"] & {
    containers?: Array<{
      label: string;
      memory_bytes: number | null;
      state: "running" | "stopped" | "restarting" | "unhealthy" | "starting" | "paused" | "unknown";
      priority: "essential" | "optional";
    }>;
    unmapped_count?: number;
    // L'evidenza Docker arriva da un file aggiornato a timer: è l'unico
    // componente della fotografia che non è istantaneo (ADR 011).
    state_age_seconds?: number | null;
  };
  listeners: HostComponent & {
    items: Array<HostListenerBase & {
      bind_scope: "loopback" | "tailscale" | "wildcard" | "other";
      external_reachability: "not_assessed";
      policy_status: "not_configured" | "allowed" | "violated";
    }>;
    truncated: boolean;
  };
  // Assente o `null` quando la raccolta dei servizi supervisionati non è
  // configurata: non è "nessun servizio giù", è una fonte che non esiste.
  services?: (HostComponent & {
    available: boolean;
    items: HostServiceItem[];
    unmapped_count: number;
    state_age_seconds: number | null;
  }) | null;
};

export type HostObservabilitySnapshotV3 = Omit<HostObservabilitySnapshotV2, "schema_version"> & {
  schema_version: 3;
  tmux_orphans: HostComponent & {
    available: boolean;
    items: Array<{
      pane_pid: number;
      age_seconds: number;
      tasks: number | null;
      memory_bytes: number | null;
      memory_peak_bytes: number | null;
      swap_bytes: number | null;
    }>;
    scanned_scopes: number;
    truncated: boolean;
    state_age_seconds: number | null;
  };
};

export type HostServiceItem = {
  label: string;
  supervisor: "systemd_system" | "systemd_user" | "pm2";
  // `absent`: il supervisore ha risposto e non conosce più questo servizio.
  // `unknown`: il supervisore non ha risposto, quindi non è accertato nulla.
  state: "running" | "starting" | "stopped" | "failed" | "restarting" | "absent" | "unknown";
  priority: "essential" | "optional";
  restarts: number | null;
  memory_bytes: number | null;
};

export type HostObservabilitySnapshot =
  | HostObservabilitySnapshotV1
  | HostObservabilitySnapshotV2
  | HostObservabilitySnapshotV3;

export async function fetchHostObservability(): Promise<HostObservabilitySnapshot> {
  const response = await request("/api/v1/host-observability");
  return response.json();
}

export type ProviderRateLimitWindow = {
  label: string;
  used_percent: number | null;
  resets_at: number | null;
  detail: string | null;
};

export type ProviderRateLimit = {
  provider: string;
  available: boolean;
  observed_at: string | null;
  windows: ProviderRateLimitWindow[];
  reached_type: string | null;
  error: string | null;
};

export type ProviderRateLimits = {
  collected_at: string;
  providers: ProviderRateLimit[];
};

export async function fetchProviderRateLimits(): Promise<ProviderRateLimits | null> {
  const response = await request("/api/v1/provider-rate-limits");
  return response.json();
}

// Storico quota (contratto storico budget v1): un campione per rilevazione del
// collector, non lo snapshot istantaneo sopra. `resets_at` segmenta la serie
// (la finestra scorrevole non deve leggere il reset come calo di consumo) e
// `stale` marca un campione valido ma di osservazione vecchia, da non
// interpolare come misura corrente.
export type RateLimitHistoryWindow = {
  label: string;
  used_percent: number | null;
  resets_at: number | null;
};

export type RateLimitHistorySample = {
  sampled_at: string;
  provider: string;
  source: "cache" | "fresh";
  observed_at: string | null;
  stale: boolean;
  // Quale forma ha prodotto la riga: `structured` (`--json` dello script
  // quote), `text` (fallback sul parsing testuale storico) o `null` per le
  // righe scritte prima di BH-03 ("non noto", non "testuale").
  parse_mode: "structured" | "text" | null;
  windows: RateLimitHistoryWindow[];
  error: string | null;
};

export type RateLimitHistory = {
  samples: RateLimitHistorySample[];
};

export async function fetchRateLimitHistory(
  hours = 24,
  limit = 3000,
): Promise<RateLimitHistory> {
  const params = new URLSearchParams({ hours: String(hours), limit: String(limit) });
  const response = await request(`/api/v1/provider-rate-limits/history?${params.toString()}`);
  return response.json();
}

export type RateLimitFreshResult = {
  collected_at: string;
  samples: RateLimitHistorySample[];
};

// Admin + CSRF; 404 se disabilitato (`rate_limit_fresh_enabled`), 429 oltre il
// rate limit, 503/504 se il collector host non risponde — il chiamante
// distingue questi stati sull'errore restituito.
export async function refreshRateLimits(): Promise<RateLimitFreshResult> {
  const response = await request("/api/v1/provider-rate-limits/refresh", { method: "POST" });
  return response.json();
}

// Consumo attribuito per sessione (contratto storico budget v1). La forma
// autorevole è nei modelli Pydantic di
// backend/app/services/session_usage_service.py. `ranking_tokens` è solo la
// chiave di ordinamento (input + cache_creation + output): non è, e non deve
// diventare, una stima di percentuale di quota — quel valore non è
// ricostruibile dai contatori di token grezzi.
export type SessionUsageTotals = {
  turns: number;
  input_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  output_tokens: number;
  ranking_tokens: number;
};

export type SessionUsageEntry = {
  session_uuid: string;
  provider: string;
  origin: string;
  project: string;
  tmux_session_id: string | null;
  models: string[];
  own: SessionUsageTotals;
  subagents: SessionUsageTotals;
  total: SessionUsageTotals;
};

// Riga grezza per bucket di 5 minuti (stesso contratto di
// `session-usage-history.jsonl`): serve al frontend solo per individuare il
// bucket di picco di una sessione da offrire come punto di ingresso al
// drill-down BH-04, non per un rendering proprio.
export type SessionUsageBucket = {
  bucket_start: string;
  provider: string;
  session_uuid: string;
  tmux_session_id: string | null;
  origin: string;
  project: string;
  model: string;
  is_subagent: boolean;
  turns: number;
  input_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  output_tokens: number;
};

export type SessionUsageReport = {
  since: string;
  entries: SessionUsageEntry[];
  buckets: SessionUsageBucket[];
};

// 404 quando l'attribuzione per sessione è disabilitata lato backend: il
// chiamante deve degradare mostrando comunque lo storico quota.
export async function fetchSessionUsage(hours = 6, limit = 50): Promise<SessionUsageReport> {
  const params = new URLSearchParams({ hours: String(hours), limit: String(limit) });
  const response = await request(`/api/v1/session-usage?${params.toString()}`);
  return response.json();
}

// Drill-down "fase C" (BH-04): timeline dei turni di una sessione in un
// singolo bucket di 5 minuti, solo metadati di turno (mai testo). Admin-only
// e dietro `session_timeline_enabled` lato backend: il chiamante deve
// trattare 404/403 come "funzione non disponibile", non come un errore da
// mostrare in modo allarmante.
export type SessionTimelineTurn = {
  timestamp: string;
  model: string;
  input_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  output_tokens: number;
};

export type SessionTimelineCompaction = {
  timestamp: string;
  pre_tokens: number | null;
  post_tokens: number | null;
};

export type SessionTimelineSubagentSpawn = {
  timestamp: string;
};

export type SessionTimelineWindow = {
  provider: string;
  session_uuid: string;
  bucket_start: string;
  bucket_end: string;
  available: boolean;
  unavailable_reason: string | null;
  turns: SessionTimelineTurn[];
  // Aggregato sull'intera finestra di 5 minuti, non per turno; chiavi
  // sempre da una tassonomia fissa (mai il nome grezzo dello strumento).
  tool_counts: Record<string, number>;
  compactions: SessionTimelineCompaction[];
  subagent_spawns: SessionTimelineSubagentSpawn[];
  truncated: boolean;
};

export async function fetchSessionTimeline(
  provider: string,
  sessionUuid: string,
  bucketStart: string,
): Promise<SessionTimelineWindow> {
  const params = new URLSearchParams({
    provider,
    session_uuid: sessionUuid,
    bucket_start: bucketStart,
  });
  const response = await request(`/api/v1/session-usage/timeline?${params.toString()}`);
  return response.json();
}

export type OrchestratorWindow = {
  used_percent: number;
  window_minutes: number | null;
  resets_at: number | null;
};

export type OrchestratorProvider = {
  provider: "claude" | "codex";
  available: boolean | null;
  observed_at: string | null;
  primary: OrchestratorWindow | null;
  secondary: OrchestratorWindow | null;
};

export type OrchestratorPhase = {
  index: number;
  total: number;
  name: string;
  interruptible: boolean;
};

export type OrchestratorTask = {
  task_id: string;
  task_kind: string;
  status: string;
  provider: "claude" | "codex";
  execution_mode: "atomic" | "phased";
  phase: OrchestratorPhase | null;
  capacity_paused: boolean;
  next_attempt_at: string | null;
  fallback_providers: ("claude" | "codex")[];
  checkpoint_present: boolean;
};

export type OrchestratorState = {
  schema_version: 1;
  collected_at: string;
  providers: OrchestratorProvider[];
  tasks: OrchestratorTask[];
};

export async function fetchOrchestratorState(): Promise<OrchestratorState | null> {
  const response = await request("/api/v1/orchestrator-state");
  return response.json();
}

export async function fetchConfig(): Promise<AppConfig> {
  const response = await request("/api/v1/config");
  return response.json();
}

export type ClaudeHistoryMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  kind: "message" | "activity";
  pending: boolean;
};

export type ClaudeHistory = {
  session_id: string;
  collected_at: string;
  source_updated_at: string;
  truncated: boolean;
  messages: ClaudeHistoryMessage[];
};

export async function fetchClaudeHistory(id: string): Promise<ClaudeHistory> {
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/claude-history`,
  );
  return response.json();
}

export type OpencodeHistoryBlock = {
  id: string;
  kind: "user" | "agent" | "activity";
  content: string;
  timestamp: string;
};

export type OpencodeHistory = {
  session_id: string;
  opencode_session_id: string;
  title: string | null;
  directory: string;
  collected_at: string;
  blocks: OpencodeHistoryBlock[];
};

export async function fetchOpencodeHistory(id: string): Promise<OpencodeHistory> {
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/opencode-history`,
  );
  return response.json();
}

export type Attachment = {
  id: string;
  name: string;
  media_type: string;
  size: number;
  path: string;
};

export async function uploadAttachment(id: string, file: File): Promise<Attachment> {
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/attachments?filename=${encodeURIComponent(file.name)}`,
    {
      method: "POST",
      headers: { "Content-Type": file.type || mediaTypeFromName(file.name) },
      body: file,
    },
  );
  return response.json();
}

export async function deleteAttachment(sessionId: string, attachmentId: string): Promise<void> {
  await request(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE" },
  );
}

function mediaTypeFromName(name: string): string {
  const extension = name.split(".").pop()?.toLowerCase();
  return ({
    csv: "text/csv",
    json: "application/json",
    md: "text/markdown",
    markdown: "text/markdown",
    mp3: "audio/mpeg",
    pdf: "application/pdf",
    txt: "text/plain",
    xml: "application/xml",
  } as Record<string, string>)[extension ?? ""] ?? "application/octet-stream";
}

export type Pane = {
  id: string;
  window_index: number;
  pane_index: number;
  active: boolean;
  command: string;
  title: string;
  width: number;
  height: number;
};

export async function listPanes(id: string): Promise<Pane[]> {
  const response = await request(`/api/v1/sessions/${encodeURIComponent(id)}/panes`);
  return (await response.json()).panes;
}

export async function resizePane(id: string, paneId: string, columns: number, rows: number) {
  await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/panes/${encodeURIComponent(paneId)}/resize`,
    { method: "POST", body: JSON.stringify({ columns, rows }) },
  );
}

export async function splitPane(
  id: string,
  paneId?: string,
  direction: "horizontal" | "vertical" = "horizontal",
): Promise<Pane> {
  const params = new URLSearchParams({ direction });
  if (paneId) params.set("pane_id", paneId);
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/panes/split?${params.toString()}`,
    { method: "POST" },
  );
  return response.json();
}

export async function killPane(id: string, paneId: string) {
  await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/panes/${encodeURIComponent(paneId)}`,
    { method: "DELETE", body: JSON.stringify({ confirmed: true }) },
  );
}

export async function sendText(
  id: string,
  text: string,
  attachmentIds: string[] = [],
  paneId?: string,
) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/input`, {
    method: "POST",
    body: JSON.stringify({ text, attachment_ids: attachmentIds, pane_id: paneId }),
  });
}

export async function sendArtifactPrompt(id: string, paneId?: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/artifact-prompt`, {
    method: "POST",
    body: JSON.stringify({ pane_id: paneId }),
  });
}

export async function sendArchiveSummaryPrompt(id: string, paneId?: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/archive-summary-prompt`, {
    method: "POST",
    body: JSON.stringify({ pane_id: paneId }),
  });
}

export async function sendEnter(id: string, paneId?: string) {
  await sendKey(id, "Enter", false, paneId);
}

export async function sendKey(
  id: string,
  key: "Enter" | "Up" | "Down" | "Left" | "Right" | "Escape" | "C-c" | "Tab" | "Shift-Tab",
  confirmed = false,
  paneId?: string,
) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/keys`, {
    method: "POST",
    body: JSON.stringify({ key, confirmed, pane_id: paneId }),
  });
}

export async function terminateSession(id: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function setSessionVisibility(id: string, hidden: boolean) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/visibility`, {
    method: "POST",
    body: JSON.stringify({ hidden }),
  });
}

export type ArchivedSession = {
  id: string;
  name: string;
  directory: string;
  profile: "shell" | "codex" | "claude" | "antigravity" | "opencode";
  agent_session_name: string | null;
  summary: string | null;
  archived_by: string;
  archived_at: string;
};

export async function listArchives(): Promise<ArchivedSession[]> {
  const response = await request("/api/v1/archives");
  return (await response.json()).archives;
}

export async function fetchArchiveDraft(id: string): Promise<{ summary: string | null }> {
  const response = await request(`/api/v1/sessions/${encodeURIComponent(id)}/archive-draft`);
  return response.json();
}

export async function archiveSession(
  id: string,
  agentSessionName: string,
  summary: string,
): Promise<ArchivedSession> {
  const response = await request(`/api/v1/sessions/${encodeURIComponent(id)}/archive`, {
    method: "POST",
    body: JSON.stringify({
      confirmed: true,
      agent_session_name: agentSessionName.trim() || null,
      summary: summary.trim() || null,
    }),
  });
  return response.json();
}

export async function restoreArchive(id: string): Promise<void> {
  await request(`/api/v1/archives/${encodeURIComponent(id)}/restore`, {
    method: "POST",
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function deleteArchive(id: string): Promise<void> {
  await request(`/api/v1/archives/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function renameSession(id: string, name: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/rename`, {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
}

export type SessionProfile =
  | "shell"
  | "codex"
  | "claude"
  | "antigravity"
  | "antigravity_yolo"
  | "opencode"
  | "opencode_yolo";

export async function createSession(name: string, directory: string, profile: SessionProfile) {
  await request("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ name: name.trim(), directory: directory.trim(), profile }),
  });
}

export type SnapshotMode = "shell" | "codex" | "claude" | "antigravity" | "opencode" | "manual";

export type SessionSnapshot = {
  name: string;
  directory: string;
  mode: SnapshotMode;
  observed_command: string;
};

export type Snapshot = {
  id: string;
  name: string;
  created_at: string;
  sessions: SessionSnapshot[];
};

export type RestoreItem = {
  name: string;
  status: "restored" | "skipped" | "manual" | "error";
  detail: string;
};

export async function listSnapshots(): Promise<Snapshot[]> {
  const response = await request("/api/v1/snapshots");
  return (await response.json()).snapshots;
}

export async function createSnapshot(
  name: string,
  sessions: { session_id: string; mode: SnapshotMode }[],
): Promise<Snapshot> {
  const response = await request("/api/v1/snapshots", {
    method: "POST",
    body: JSON.stringify({ name: name.trim(), sessions }),
  });
  return response.json();
}

export async function restoreSnapshot(id: string): Promise<RestoreItem[]> {
  const response = await request(`/api/v1/snapshots/${encodeURIComponent(id)}/restore`, {
    method: "POST",
    body: JSON.stringify({ confirmed: true }),
  });
  return (await response.json()).results;
}

export async function deleteSnapshot(id: string): Promise<void> {
  await request(`/api/v1/snapshots/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmed: true }),
  });
}

export type DirectoryEntry = {
  name: string;
  type: "dir" | "file" | "other";
  size: number | null;
  created_at: string | null;
};

export type DirectoryListing = {
  session_id: string;
  path: string;
  root: string;
  parent: string | null;
  entries: DirectoryEntry[];
  truncated: boolean;
};

export async function fetchDirectory(id: string, path?: string): Promise<DirectoryListing> {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  const response = await request(`/api/v1/sessions/${encodeURIComponent(id)}/directory${query}`);
  return response.json();
}

export type UploadResult = {
  session_id: string;
  path: string;
  name: string;
  size: number;
};

export async function uploadDirectoryFile(
  id: string,
  path: string | undefined,
  file: File,
): Promise<UploadResult> {
  const params = new URLSearchParams();
  params.set("filename", file.name);
  if (path) params.set("path", path);
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/directory/upload?${params.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    },
  );
  return response.json();
}

export type FileContent = {
  session_id: string;
  path: string;
  size: number;
  content: string;
  truncated: boolean;
};

export async function fetchFile(id: string, path: string): Promise<FileContent> {
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`,
  );
  return response.json();
}

export function fileDownloadUrl(id: string, path: string): string {
  return `/api/v1/sessions/${encodeURIComponent(id)}/file/download?path=${encodeURIComponent(path)}`;
}

// Media del browser di directory: il backend li serve inline col media
// type dedotto dai byte, come gia' fa la cartella artefatti.
export function filePreviewUrl(id: string, path: string): string {
  return `/api/v1/sessions/${encodeURIComponent(id)}/file/preview?path=${encodeURIComponent(path)}`;
}

export function attachmentPreviewUrl(sessionId: string, attachmentId: string): string {
  return `/api/v1/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/preview`;
}

export type Artifact = {
  name: string;
  media_type: string;
  size: number;
  modified_at: string;
};

export type ArtifactDirectory = {
  path: string;
};

export async function fetchArtifactDirectory(sessionId: string): Promise<ArtifactDirectory> {
  const response = await request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/artifact-directory`);
  return response.json();
}

export async function listArtifacts(sessionId: string): Promise<Artifact[]> {
  const response = await request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts`);
  return response.json();
}

export function artifactDownloadUrl(sessionId: string, name: string): string {
  const encodedPath = name.split("/").map(encodeURIComponent).join("/");
  return `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodedPath}`;
}

export async function fetchArtifactContent(sessionId: string, name: string): Promise<string> {
  const response = await request(artifactDownloadUrl(sessionId, name));
  return response.text();
}

export function streamUrl(id: string, paneId?: string, ansi?: boolean, lines?: number): string {
  const url = new URL(window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/v1/ws/sessions/${encodeURIComponent(id)}`;
  if (paneId) url.searchParams.set("pane_id", paneId);
  if (ansi) url.searchParams.set("ansi", "true");
  if (lines) url.searchParams.set("lines", String(lines));
  return url.toString();
}

export async function fetchPushPublicKey(): Promise<string> {
  const response = await request("/api/v1/push/public-key");
  return (await response.json()).public_key;
}

export async function subscribePush(subscription: PushSubscriptionJSON): Promise<void> {
  await request("/api/v1/push/subscriptions", {
    method: "POST",
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys: subscription.keys,
    }),
  });
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  await request("/api/v1/push/subscriptions", {
    method: "DELETE",
    body: JSON.stringify({ endpoint }),
  });
}
