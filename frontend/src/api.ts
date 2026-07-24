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
      "Content-Type": "application/json",
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

export async function sendText(id: string, text: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/input`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function sendEnter(id: string) {
  await request(`/api/v1/sessions/${encodeURIComponent(id)}/keys`, {
    method: "POST",
    body: JSON.stringify({ key: "Enter" }),
  });
}

export async function createSession(name: string, directory: string) {
  await request("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ name: name.trim(), directory: directory.trim(), profile: "shell" }),
  });
}

export function streamUrl(id: string): string {
  const url = new URL(window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/v1/ws/sessions/${encodeURIComponent(id)}`;
  return url.toString();
}
