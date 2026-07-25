export type Session = {
  id: string;
  name: string;
  attached: boolean;
  windows: number;
  current_command: string;
  activity_at: string;
};

let csrfToken = "";

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
    throw new ApiError(response.status, detail);
  }
  return response;
}

export async function login(password: string): Promise<void> {
  const response = await request("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  csrfToken = (await response.json()).csrf_token;
}

export async function restoreSession(): Promise<void> {
  const response = await request("/api/v1/auth/session");
  csrfToken = (await response.json()).csrf_token;
}

export async function listSessions(): Promise<Session[]> {
  const response = await request("/api/v1/sessions");
  return (await response.json()).sessions;
}

export type AppConfig = {
  allowed_roots: string[];
  workspace_presets: Record<string, string>;
};

export async function fetchConfig(): Promise<AppConfig> {
  const response = await request("/api/v1/config");
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

export async function splitPane(id: string, paneId?: string): Promise<Pane> {
  const query = paneId ? `?pane_id=${encodeURIComponent(paneId)}` : "";
  const response = await request(
    `/api/v1/sessions/${encodeURIComponent(id)}/panes/split${query}`,
    { method: "POST" },
  );
  return response.json();
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

export async function sendEnter(id: string, paneId?: string) {
  await sendKey(id, "Enter", false, paneId);
}

export async function sendKey(
  id: string,
  key: "Enter" | "Up" | "Down" | "Escape" | "C-c",
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

export async function renameSession(id: string, name: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/rename`, {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
}

export async function createSession(name: string, directory: string) {
  await request("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ name: name.trim(), directory: directory.trim(), profile: "shell" }),
  });
}

export type SnapshotMode = "shell" | "codex" | "claude" | "manual";

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

export function streamUrl(id: string, paneId?: string): string {
  const url = new URL(window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/v1/ws/sessions/${encodeURIComponent(id)}`;
  if (paneId) url.searchParams.set("pane_id", paneId);
  return url.toString();
}
