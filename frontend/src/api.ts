export type Session = {
  id: string;
  name: string;
  attached: boolean;
  windows: number;
  current_command: string;
  activity_at: string;
};

let csrfToken = "";

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
    throw new Error(detail);
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

export async function sendText(id: string, text: string, attachmentIds: string[] = []) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/input`, {
    method: "POST",
    body: JSON.stringify({ text, attachment_ids: attachmentIds }),
  });
}

export async function sendEnter(id: string) {
  await sendKey(id, "Enter");
}

export async function sendKey(
  id: string,
  key: "Enter" | "Up" | "Down" | "Escape" | "C-c",
  confirmed = false,
) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/keys`, {
    method: "POST",
    body: JSON.stringify({ key, confirmed }),
  });
}

export async function terminateSession(id: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function createSession(name: string, directory: string) {
  await request("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ name: name.trim(), directory: directory.trim(), profile: "shell" }),
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

export function streamUrl(id: string): string {
  const url = new URL(window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/v1/ws/sessions/${encodeURIComponent(id)}`;
  return url.toString();
}
