import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import {
  ApiError,
  AgentStatus,
  ArchivedSession,
  AuditEvent,
  Attachment,
  Artifact,
  Backup,
  ClaudeHistory,
  archiveSession,
  artifactDownloadUrl,
  attachmentPreviewUrl,
  fetchArtifactContent,
  backupDownloadUrl,
  createBackup,
  createUser,
  createSnapshot,
  createSession,
  deleteArchive,
  deleteSnapshot,
  deleteAttachment,
  deleteBackup,
  DirectoryEntry,
  DirectoryListing,
  fetchConfig,
  fetchClaudeHistory,
  fetchDirectory,
  fetchFile,
  fetchHostObservability,
  fetchOrchestratorState,
  fetchProviderRateLimits,
  fetchPushPublicKey,
  fetchRateLimitHistory,
  fetchSessionUsage,
  fetchSessionTimeline,
  fileDownloadUrl,
  FileContent,
  errorMessage,
  login,
  Identity,
  HostComponent,
  HostObservabilitySnapshot,
  killPane,
  listSessions,
  listArchives,
  listAgentStatuses,
  listArtifacts,
  listAudit,
  listBackups,
  listPanes,
  listSnapshots,
  listUsers,
  Pane,
  OrchestratorState,
  ProviderRateLimitWindow,
  ProviderRateLimits,
  RateLimitHistory,
  RateLimitHistorySample,
  refreshRateLimits,
  renameSession,
  restoreSession,
  setUnauthorizedHandler,
  setSessionVisibility,
  restoreArchive,
  restoreSnapshot,
  Role,
  resizePane,
  sendEnter,
  sendArtifactPrompt,
  sendKey,
  sendText,
  Session,
  SessionUsageBucket,
  SessionUsageEntry,
  SessionUsageReport,
  SessionUsageTotals,
  SessionTimelineWindow,
  setUserActive,
  subscribePush,
  unsubscribePush,
  Snapshot,
  SnapshotMode,
  splitPane,
  streamUrl,
  terminateSession,
  uploadAttachment,
  UserAccount,
} from "./api";

function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);
  return online;
}

type Connection = "connecting" | "online" | "offline" | "closed";

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: "connessione",
  online: "online",
  offline: "offline",
  closed: "chiusa",
};

// Solo per Blocchi (testo semplice, si reimpagina via CSS): forzare lo
// stesso minimo anche su Terminale (xterm.js, cursore ANSI posizionato)
// aveva causato un disallineamento della scrollbar interna e problemi di
// geometria col load-more — provato e revertito, vedi docs/roadmap.md.
const MIN_PANE_COLUMNS = 120;
// Profondità massima e incremento dello storico caricabile in Terminale
// con lo scroll-indietro ("load more"); il WS accetta lines 100-2000
// (vedi main.py, stream()).
const MAX_TERMINAL_LINES = 2000;
const LOAD_MORE_STEP_LINES = 500;
const SESSION_NAME_PATTERN = /^[\p{L}\p{N}_-]+(?: [\p{L}\p{N}_-]+)*$/u;
const SESSION_NAME_HINT = "Usa lettere (anche accentate), numeri, trattini e spazi singoli; massimo 64 caratteri";

const LATEST_RELEASE = {
  title: "Antigravity (agy) promosso ad agente",
  description:
    "Le sessioni AGY ora hanno la barra stato, la vista Blocchi, i comandi rapidi, il pulsante permessi (Shift-Tab), il resume con agy -c e il match rate limit indipendente.",
};

const AGENT_STATE_ICON: Record<AgentStatus["state"], string> = {
  active: "◌",
  idle: "✓",
  waiting_input: "!",
  waiting_authorization: "🔒",
  unknown: "?",
};

const DEFAULT_AGENT_VIEW_KEY = "mac-default-agent-view";
const DASHBOARD_DENSITY_KEY = "mac-dashboard-density";
const RECENT_SESSIONS_KEY = "mac-recent-sessions";

type DashboardDensity = "extended" | "compact";

function readDefaultAgentView(): "blocks" | "terminal" {
  return window.localStorage.getItem(DEFAULT_AGENT_VIEW_KEY) === "terminal" ? "terminal" : "blocks";
}

function readDashboardDensity(): DashboardDensity {
  return window.localStorage.getItem(DASHBOARD_DENSITY_KEY) === "compact" ? "compact" : "extended";
}

function readRecentSessions(): Session[] {
  try {
    const stored = JSON.parse(window.localStorage.getItem(RECENT_SESSIONS_KEY) ?? "[]");
    if (!Array.isArray(stored)) return [];
    return stored.filter((item): item is Session => (
      typeof item?.id === "string"
      && typeof item.name === "string"
      && typeof item.current_command === "string"
      && typeof item.attached === "boolean"
      && typeof item.windows === "number"
      && typeof item.activity_at === "string"
    )).slice(0, 2);
  } catch {
    return [];
  }
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalized);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

const PERMISSION_STATE_ICON: Record<AgentStatus["permission_state"], string> = {
  restricted: "▣",
  standard: "◈",
  elevated: "⚡",
  bypass: "🔓",
  plan: "▤",
  ask: "🔐",
  auto: "A",
  manual: "M",
  accept_edits: "✎",
  dont_ask: "!",
  unknown: "◇",
};

const AGENT_STATE_LEGEND: Array<[AgentStatus["state"], string]> = [
  ["active", "In elaborazione"],
  ["idle", "Completato o inattivo"],
  ["waiting_input", "Attende feedback"],
  ["waiting_authorization", "Attende autorizzazione"],
  ["unknown", "Stato non rilevato"],
];

const PERMISSION_STATE_LEGEND: Array<
  [AgentStatus["permission_state"], string]
> = [
  ["restricted", "Sola lettura"],
  ["ask", "Chiede approvazione"],
  ["auto", "Auto"],
  ["manual", "Manuale"],
  ["accept_edits", "Accetta modifiche"],
  ["dont_ask", "Non chiedere"],
  ["plan", "Plan mode"],
  ["bypass", "Accesso completo"],
  ["unknown", "Non rilevato"],
];

type ChatBlockKind = "user" | "agent" | "activity";

type ChatBlock = {
  kind: ChatBlockKind;
  content: string;
};

const ANSI_SEQUENCE = /\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))/g;

function chatLines(content: string, provider: string): string[] {
  const lines = content.split("\n");
  if (!/claude/i.test(provider)) return lines;
  let end = lines.length;
  const trailingStart = Math.max(0, lines.length - 12);
  let emptyPrompt = -1;
  for (let index = lines.length - 1; index >= trailingStart; index -= 1) {
    if (/^\s*❯\s*$/.test(lines[index])) {
      emptyPrompt = index;
      break;
    }
  }
  if (emptyPrompt >= 0) {
    end = emptyPrompt;
    while (end > 0 && /^\s*─{5,}\s*$/.test(lines[end - 1])) end -= 1;
    while (
      end > 0
      && (/\/clear to save/i.test(lines[end - 1]) || !lines[end - 1].trim())
    ) end -= 1;
  } else if (
    lines.slice(trailingStart).some((line) => /Enter to select.*Esc to cancel/i.test(line))
  ) {
    for (let index = lines.length - 1; index >= trailingStart; index -= 1) {
      if (/^\s*─{5,}\s*$/.test(lines[index])) {
        end = index;
        break;
      }
    }
  }
  return lines.slice(0, end);
}

function chatBlocks(content: string, provider: string): ChatBlock[] {
  const blocks: ChatBlock[] = [];
  let current: ChatBlock | undefined;
  let afterUserBreak = false;
  const codex = /codex/i.test(provider);
  for (const line of chatLines(content, provider)) {
    const visible = line.replace(ANSI_SEQUENCE, "");
    let kind = current?.kind ?? "activity";
    // Codex continua spesso una risposta con ">" dopo il marker iniziale
    // "•". Se il blocco corrente è dell'agente, non deve quindi diventare
    // un finto messaggio dell'utente; il prompt Codex usa invece "›".
    if (/^\s*[›❯]\s*/.test(visible) || (!codex && /^\s*>\s*/.test(visible))) kind = "user";
    else if (/^\s*>\s*/.test(visible) && current?.kind !== "agent") kind = "user";
    else if (/^\s*[•●]\s+/.test(visible)) kind = "agent";
    else if (
      /^\s*(?:✔|✘|✱|✻|✽|⏺|─{3,}|Ran\b|Explored\b|Read\b|Edited\b)/.test(visible)
    ) kind = "activity";
    else if (afterUserBreak && line.trim()) kind = "agent";

    if (!current || (line.trim() && kind !== current.kind)) {
      current = { kind, content: line };
      blocks.push(current);
    } else {
      current.content += `${current.content ? "\n" : ""}${line}`;
    }
    afterUserBreak = current.kind === "user" && !line.trim();
  }
  return blocks.filter((block) => block.content.trim());
}

function formatSize(size: number | null): string {
  if (size === null) return "—";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function formatRateLimitReset(value: number | null): string | null {
  if (value === null) return null;
  const instant = new Date(value * 1000);
  if (!Number.isFinite(instant.getTime())) return null;
  return instant.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

function rateLimitWindowDescription(window: ProviderRateLimitWindow): string | null {
  const reset = formatRateLimitReset(window.resets_at);
  return [window.detail, reset ? `reset ${reset}` : null].filter(Boolean).join(" · ") || null;
}

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}g`;
}

function rateLimitColor(usedPercent: number | null): string | undefined {
  if (usedPercent === null) return undefined;
  const percentage = Math.max(0, Math.min(100, usedPercent));
  return `hsl(${120 - percentage * 1.2} 65% 62%)`;
}

function shellQuote(name: string): string {
  return /^[\w.-]+$/.test(name) ? name : `'${name.replace(/'/g, "'\\''")}'`;
}

async function copyToClipboard(text: string): Promise<boolean> {
  // navigator.clipboard richiede un secure context (HTTPS o localhost); questo
  // deployment gira in HTTP su un IP Tailscale, quindi serve un fallback.
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // prova comunque il fallback legacy
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  document.body.removeChild(textarea);
  return copied;
}

function cleanShareableOutput(text: string): string {
  const lines = text
    .replace(ANSI_SEQUENCE, "")
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/^\s*(?:[•●][ \t]*)?[›❯>][ \t]*/, ""));
  const firstContent = lines.findIndex((line) => line.trim());
  if (firstContent >= 0) lines[firstContent] = lines[firstContent].replace(/^\s*[•●][ \t]*/, "");
  return lines
    .join("\n")
    .split(/\n[ \t]*\n+/)
    .map((paragraph) => paragraph.split("\n").map((line) => line.trim()).join(" ").trim())
    .filter(Boolean)
    .join("\n\n");
}

function joinPath(base: string, name: string): string {
  return base.endsWith("/") ? `${base}${name}` : `${base}/${name}`;
}

const DOWNLOADABLE_FILE = /\.(?:bmp|docx?|gif|jpe?g|pdf|png|tiff?|webp)$/i;

function isDownloadable(name: string): boolean {
  return DOWNLOADABLE_FILE.test(name);
}

function FilePreview({ sessionId, path, onBack }: { sessionId: string; path: string; onBack: () => void }) {
  const [file, setFile] = useState<FileContent | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setFile(null);
    fetchFile(sessionId, path)
      .then((result) => { if (!cancelled) setFile(result); })
      .catch((value) => { if (!cancelled) setError(errorMessage(value)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId, path]);

  return (
    <>
      <header>
        <div>
          <span className="eyebrow">FILE (SOLA LETTURA)</span>
          <h2 className="directory-path" title={path}>{path}</h2>
        </div>
        <button className="modal-close" onClick={onBack} aria-label="Torna all'elenco">‹</button>
      </header>
      {loading && <p className="empty">Caricamento…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && file && (
        <>
          <pre className="file-preview">{file.content || "(file vuoto)"}</pre>
          {file.truncated && <small>Anteprima troncata: il file continua oltre quanto mostrato.</small>}
        </>
      )}
    </>
  );
}

function DirectoryModal({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const [currentPath, setCurrentPath] = useState<string | undefined>(undefined);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [copiedName, setCopiedName] = useState("");
  const [openFile, setOpenFile] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchDirectory(sessionId, currentPath)
      .then((result) => { if (!cancelled) setListing(result); })
      .catch((value) => { if (!cancelled) setError(errorMessage(value)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId, currentPath]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (openFile !== null) setOpenFile(null);
      else onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, openFile]);

  async function copy(entry: DirectoryEntry) {
    const ok = await copyToClipboard(shellQuote(entry.name));
    if (ok) {
      setError("");
      setCopiedName(entry.name);
      window.setTimeout(() => setCopiedName(""), 1500);
    } else {
      setError("Copia negli appunti non riuscita.");
    }
  }

  function openEntry(entry: DirectoryEntry) {
    if (!listing) return;
    const fullPath = joinPath(listing.path, entry.name);
    if (entry.type === "dir") setCurrentPath(fullPath);
    else if (entry.type === "file" && isDownloadable(entry.name)) downloadEntry(entry);
    else if (entry.type === "file") setOpenFile(fullPath);
  }

  function downloadEntry(entry: DirectoryEntry) {
    if (!listing) return;
    const anchor = document.createElement("a");
    anchor.href = fileDownloadUrl(sessionId, joinPath(listing.path, entry.name));
    anchor.download = entry.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="help-modal directory-modal" role="dialog" aria-modal="true" aria-labelledby="directory-title">
        {openFile !== null ? (
          <FilePreview sessionId={sessionId} path={openFile} onBack={() => setOpenFile(null)} />
        ) : (
          <>
            <header>
              <div>
                <span className="eyebrow">CONTENUTO DIRECTORY</span>
                <h2 id="directory-title" className="directory-path" title={listing?.path}>{listing?.path ?? "…"}</h2>
              </div>
              <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
            </header>
            {listing && (
              <div className="directory-nav">
                <button
                  type="button"
                  disabled={!listing.parent}
                  onClick={() => listing.parent && setCurrentPath(listing.parent)}
                >
                  ↑ Su
                </button>
                <button
                  type="button"
                  disabled={listing.path === listing.root}
                  onClick={() => setCurrentPath(listing.root)}
                >
                  ⌂ Root sessione
                </button>
              </div>
            )}
            {loading && <p className="empty">Caricamento…</p>}
            {error && <p className="error">{error}</p>}
            {!loading && !error && listing && (
              <>
                <ul className="directory-list">
                  {listing.entries.map((entry) => (
                    <li key={entry.name} className="directory-entry">
                      <button
                        type="button"
                        className="directory-open"
                        disabled={entry.type === "other"}
                        onClick={() => openEntry(entry)}
                      >
                        <span className={`directory-type ${entry.type}`}>
                          {entry.type === "dir" ? "DIR" : entry.type === "file" ? "FILE" : "?"}
                        </span>
                        <span className="directory-name" title={entry.name}>{entry.name}</span>
                        <span className="directory-meta">{formatSize(entry.size)} · {formatDate(entry.created_at)}</span>
                      </button>
                      <button type="button" className="directory-copy" onClick={() => void copy(entry)}>
                        {copiedName === entry.name ? "Copiato" : "Copy"}
                      </button>
                      {entry.type === "file" && isDownloadable(entry.name) && (
                        <button
                          type="button"
                          className="directory-download"
                          onClick={() => downloadEntry(entry)}
                        >
                          Download
                        </button>
                      )}
                    </li>
                  ))}
                  {listing.entries.length === 0 && <li className="empty">Directory vuota.</li>}
                </ul>
                {listing.truncated && <small>Elenco troncato alle prime 2000 voci.</small>}
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}

const PREVIEWABLE_TEXT_TYPES = new Set([
  "text/plain",
  "text/markdown",
  "application/json",
  "text/csv",
  "text/xml",
  "application/xml",
]);

function isPreviewableImage(mediaType: string): boolean {
  return mediaType.startsWith("image/");
}

function isPreviewableText(mediaType: string): boolean {
  return PREVIEWABLE_TEXT_TYPES.has(mediaType);
}

function isPreviewableArtifact(mediaType: string): boolean {
  return isPreviewableImage(mediaType) || isPreviewableText(mediaType);
}

function ArtifactPreview({ sessionId, item, onBack }: { sessionId: string; item: Artifact; onBack: () => void }) {
  const isImage = isPreviewableImage(item.media_type);
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!isImage);

  useEffect(() => {
    if (isImage) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchArtifactContent(sessionId, item.name)
      .then((text) => { if (!cancelled) setContent(text); })
      .catch((value) => { if (!cancelled) setError(errorMessage(value)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId, item.name, isImage]);

  return (
    <>
      <header>
        <div>
          <span className="eyebrow">ANTEPRIMA</span>
          <h2 className="directory-path" title={item.name}>{item.name}</h2>
        </div>
        <button className="modal-close" onClick={onBack} aria-label="Torna all'elenco">‹</button>
      </header>
      {isImage ? (
        <div className="artifact-preview">
          <img src={artifactDownloadUrl(sessionId, item.name)} alt={item.name} />
        </div>
      ) : (
        <>
          {loading && <p className="empty">Caricamento…</p>}
          {error && <p className="error">{error}</p>}
          {!loading && !error && <pre className="file-preview">{content || "(file vuoto)"}</pre>}
        </>
      )}
    </>
  );
}

function ArtifactsModal({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const [items, setItems] = useState<Artifact[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [previewItem, setPreviewItem] = useState<Artifact | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    listArtifacts(sessionId)
      .then((result) => { if (!cancelled) setItems(result); })
      .catch((value) => { if (!cancelled) setError(errorMessage(value)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (previewItem !== null) setPreviewItem(null);
      else onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, previewItem]);

  function downloadArtifact(item: Artifact) {
    const anchor = document.createElement("a");
    anchor.href = artifactDownloadUrl(sessionId, item.name);
    anchor.download = item.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="help-modal directory-modal" role="dialog" aria-modal="true" aria-labelledby="artifacts-title">
        {previewItem !== null ? (
          <ArtifactPreview sessionId={sessionId} item={previewItem} onBack={() => setPreviewItem(null)} />
        ) : (
          <>
            <header>
              <div>
                <span className="eyebrow">ARTEFATTI CONSEGNATI DALL'AGENTE</span>
                <h2 id="artifacts-title" className="directory-path">Sessione {sessionId}</h2>
              </div>
              <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
            </header>
            {loading && <p className="empty">Caricamento…</p>}
            {error && <p className="error">{error}</p>}
            {!loading && !error && (
              <ul className="directory-list">
                {items.map((item) => (
                  <li key={item.name} className="directory-entry">
                    <button
                      type="button"
                      className="directory-open"
                      disabled={!isPreviewableArtifact(item.media_type)}
                      onClick={() => setPreviewItem(item)}
                    >
                      <span className="directory-type file">FILE</span>
                      <span className="directory-name" title={item.name}>{item.name}</span>
                      <span className="directory-meta">{formatSize(item.size)} · {formatDate(item.modified_at)}</span>
                    </button>
                    <button type="button" className="directory-download" onClick={() => downloadArtifact(item)}>
                      Download
                    </button>
                  </li>
                ))}
                {items.length === 0 && <li className="empty">Nessun artefatto consegnato in questa sessione.</li>}
              </ul>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function suggestedSnapshotMode(session: Session): SnapshotMode {
  const command = session.current_command.toLowerCase();
  if (command.includes("codex")) return "codex";
  if (command.includes("claude")) return "claude";
  if (command.includes("agy") || command.includes("antigravity")) return "antigravity";
  return "shell";
}

function defaultSnapshotName(): string {
  return `Prima del riavvio ${new Date().toLocaleString()}`;
}

function SnapshotModal({
  sessions,
  onClose,
  onRestored,
}: {
  sessions: Session[];
  onClose: () => void;
  onRestored: () => Promise<void>;
}) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [name, setName] = useState(defaultSnapshotName);
  const [selected, setSelected] = useState<Record<string, SnapshotMode>>(
    Object.fromEntries(sessions.map((session) => [session.id, suggestedSnapshotMode(session)])),
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [restoreReport, setRestoreReport] = useState<string[]>([]);

  async function refreshSnapshots() {
    setSnapshots(await listSnapshots());
  }

  useEffect(() => {
    refreshSnapshots()
      .catch((value) => setError(errorMessage(value)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  async function saveSnapshot(event: FormEvent) {
    event.preventDefault();
    const entries = Object.entries(selected).map(([session_id, mode]) => ({ session_id, mode }));
    if (entries.length === 0) {
      setError("Seleziona almeno una sessione.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await createSnapshot(name, entries);
      setName(defaultSnapshotName());
      await refreshSnapshots();
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setSaving(false);
    }
  }

  async function restore(item: Snapshot) {
    if (!window.confirm(`Ripristinare lo snapshot “${item.name}”?`)) return;
    setBusyId(item.id);
    setError("");
    setRestoreReport([]);
    try {
      const results = await restoreSnapshot(item.id);
      setRestoreReport(results.map((result) => (
        `${result.name}: ${result.status} — ${result.detail}`
      )));
      await onRestored();
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusyId("");
    }
  }

  async function remove(item: Snapshot) {
    if (!window.confirm(`Eliminare definitivamente lo snapshot “${item.name}”?`)) return;
    setBusyId(item.id);
    setError("");
    try {
      await deleteSnapshot(item.id);
      await refreshSnapshots();
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusyId("");
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="help-modal snapshot-modal" role="dialog" aria-modal="true" aria-labelledby="snapshot-title">
        <header>
          <div>
            <span className="eyebrow">RIAVVIO VPS</span>
            <h2 id="snapshot-title">Snapshot sessioni</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>

        <form className="snapshot-create" onSubmit={(event) => void saveSnapshot(event)}>
          <label>
            Nome snapshot
            <input required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <div className="snapshot-session-list">
            {sessions.map((session) => {
              const enabled = selected[session.id] !== undefined;
              return (
                <div className="snapshot-session" key={session.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(event) => {
                        setSelected((current) => {
                          const next = { ...current };
                          if (event.target.checked) next[session.id] = suggestedSnapshotMode(session);
                          else delete next[session.id];
                          return next;
                        });
                      }}
                    />
                    <span><strong>{session.name}</strong><small>{session.current_command}</small></span>
                  </label>
                  <select
                    disabled={!enabled}
                    value={selected[session.id] ?? "manual"}
                    onChange={(event) => setSelected((current) => ({
                      ...current,
                      [session.id]: event.target.value as SnapshotMode,
                    }))}
                  >
                    <option value="shell">Solo shell</option>
                    <option value="codex">Codex: selettore resume</option>
                    <option value="claude">Claude: selettore resume</option>
                    <option value="antigravity">Antigravity: avvia agy</option>
                    <option value="manual">Rilancio manuale</option>
                  </select>
                </div>
              );
            })}
            {sessions.length === 0 && <p className="empty">Nessuna sessione attiva da salvare.</p>}
          </div>
          <button type="submit" disabled={saving || sessions.length === 0}>
            {saving ? "Salvataggio…" : "Crea snapshot"}
          </button>
        </form>

        <div className="snapshot-existing">
          <h3>Snapshot salvati</h3>
          {loading && <p className="empty">Caricamento…</p>}
          {!loading && snapshots.map((item) => (
            <article className="snapshot-card" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <small>{new Date(item.created_at).toLocaleString()} · {item.sessions.length} sessioni</small>
              </div>
              <ul>
                {item.sessions.map((session) => (
                  <li key={`${session.name}-${session.directory}`}>
                    {session.name} · {session.mode} · {session.directory}
                  </li>
                ))}
              </ul>
              <div className="snapshot-actions">
                <button disabled={busyId === item.id} onClick={() => void restore(item)}>
                  Ripristina
                </button>
                <button className="danger" disabled={busyId === item.id} onClick={() => void remove(item)}>
                  Elimina
                </button>
              </div>
            </article>
          ))}
          {!loading && snapshots.length === 0 && <p className="empty">Nessuno snapshot salvato.</p>}
        </div>
        {restoreReport.length > 0 && (
          <div className="snapshot-report" role="status">
            <strong>Esito ripristino</strong>
            <ul>{restoreReport.map((line) => <li key={line}>{line}</li>)}</ul>
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}

function ArchiveModal({
  onClose,
  onRestored,
}: {
  onClose: () => void;
  onRestored: () => Promise<void>;
}) {
  const [archives, setArchives] = useState<ArchivedSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setArchives(await listArchives());
  }

  useEffect(() => {
    refresh()
      .catch((value) => setError(errorMessage(value)))
      .finally(() => setLoading(false));
  }, []);

  async function restore(item: ArchivedSession) {
    if (!window.confirm(`Rilanciare la sessione “${item.name}”?`)) return;
    setBusyId(item.id);
    setError("");
    try {
      await restoreArchive(item.id);
      await Promise.all([refresh(), onRestored()]);
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusyId("");
    }
  }

  async function remove(item: ArchivedSession) {
    if (!window.confirm(`Eliminare definitivamente “${item.name}” dall’archivio?`)) return;
    setBusyId(item.id);
    setError("");
    try {
      await deleteArchive(item.id);
      await refresh();
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="help-modal snapshot-modal" role="dialog" aria-modal="true" aria-labelledby="archive-title">
        <header>
          <div><span className="eyebrow">METADATI SESSIONI</span><h2 id="archive-title">Archivio</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        <div className="snapshot-existing">
          {loading && <p className="empty">Caricamento…</p>}
          {!loading && archives.map((item) => (
            <article className="snapshot-card" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <small>{item.profile} · {new Date(item.archived_at).toLocaleString()}</small>
                <small>{item.directory}</small>
                <small>Archiviata da {item.archived_by}</small>
              </div>
              <div className="snapshot-actions">
                <button disabled={busyId === item.id} onClick={() => void restore(item)}>Rilancia</button>
                <button className="danger" disabled={busyId === item.id} onClick={() => void remove(item)}>Elimina</button>
              </div>
            </article>
          ))}
          {!loading && archives.length === 0 && <p className="empty">Nessuna sessione archiviata.</p>}
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}

function HiddenSessionsModal({
  sessions,
  canManage,
  onClose,
  onOpen,
  onRestore,
}: {
  sessions: Session[];
  canManage: boolean;
  onClose: () => void;
  onOpen: (session: Session) => void;
  onRestore: (session: Session) => Promise<void>;
}) {
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  async function restore(session: Session) {
    setBusyId(session.id);
    setError("");
    try {
      await onRestore(session);
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="help-modal snapshot-modal" role="dialog" aria-modal="true" aria-labelledby="hidden-sessions-title">
        <header>
          <div><span className="eyebrow">DASHBOARD</span><h2 id="hidden-sessions-title">Sessioni nascoste</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        <div className="snapshot-existing">
          {sessions.map((session) => (
            <article className="snapshot-card" key={session.id}>
              <div>
                <strong>{session.name}</strong>
                <small>{session.current_command} · {session.windows} window</small>
              </div>
              <div className="snapshot-actions">
                <button onClick={() => { onOpen(session); onClose(); }}>Apri</button>
                {canManage && <button disabled={busyId === session.id} onClick={() => void restore(session)}>Mostra</button>}
              </div>
            </article>
          ))}
          {sessions.length === 0 && <p className="empty">Nessuna sessione nascosta.</p>}
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}

function PreferencesModal({
  onClose,
  dashboardDensity,
  onDashboardDensityChange,
}: {
  onClose: () => void;
  dashboardDensity: DashboardDensity;
  onDashboardDensityChange: (density: DashboardDensity) => void;
}) {
  const [defaultView, setDefaultView] = useState<"blocks" | "terminal">(readDefaultAgentView());

  function choose(view: "blocks" | "terminal") {
    setDefaultView(view);
    window.localStorage.setItem(DEFAULT_AGENT_VIEW_KEY, view);
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="help-modal preferences-modal" role="dialog" aria-modal="true" aria-labelledby="preferences-title">
        <header>
          <div><span className="eyebrow">CONSOLE</span><h2 id="preferences-title">Preferenze</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        <fieldset className="preference-field">
          <legend>Vista predefinita per le sessioni Codex/Claude</legend>
          <label>
            <input
              type="radio"
              name="default-agent-view"
              checked={defaultView === "blocks"}
              onChange={() => choose("blocks")}
            />
            Blocchi
          </label>
          <label>
            <input
              type="radio"
              name="default-agent-view"
              checked={defaultView === "terminal"}
              onChange={() => choose("terminal")}
            />
            Terminale
          </label>
        </fieldset>
        <fieldset className="preference-field">
          <legend>Dashboard</legend>
          <label>
            <input
              type="radio"
              name="dashboard-density"
              checked={dashboardDensity === "extended"}
              onChange={() => onDashboardDensityChange("extended")}
            />
            Estesa
          </label>
          <label>
            <input
              type="radio"
              name="dashboard-density"
              checked={dashboardDensity === "compact"}
              onChange={() => onDashboardDensityChange("compact")}
            />
            Compatta
          </label>
        </fieldset>
        <p className="empty">
          Si applica alla prossima apertura di una sessione Codex/Claude; la
          vista Cronologia resta sempre raggiungibile dal toggle, quando
          abilitata.
        </p>
        <p className="empty">
          La versione compatta agisce solo sulla home: riduce le informazioni
          di servizio per lasciare più spazio all’elenco delle sessioni.
        </p>
      </section>
    </div>
  );
}

// Nomi leggibili per la lista "Funzioni opzionali" (vista Audit, admin-only).
// Pura etichettatura: lo stato acceso/spento arriva da `ConfigView.optional_features`
// (BH-03), un'enunciazione di fatto, mai un giudizio su cosa "dovrebbe" essere
// acceso — un'installazione minima con tutto spento è uno stato valido.
const OPTIONAL_FEATURE_LABEL: Record<string, string> = {
  host_observability_enabled: "Osservabilità host",
  session_usage_enabled: "Attribuzione per sessione",
  session_timeline_enabled: "Timeline dei turni (drill-down)",
  rate_limit_fresh_enabled: "Aggiornamento forzato quota",
  claude_history_enabled: "Storico Claude",
  database_auth_enabled: "Autenticazione con account",
};

function AuditModal({ onClose }: { onClose: () => void }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [optionalFeatures, setOptionalFeatures] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    listAudit()
      .then(setEvents)
      .catch((value) => setError(errorMessage(value)))
      .finally(() => setLoading(false));
    fetchConfig()
      .then((config) => setOptionalFeatures(config.optional_features))
      .catch(() => { /* la sezione resta assente, l'audit degli eventi non dipende da questo */ });
  }, []);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="help-modal snapshot-modal" role="dialog" aria-modal="true" aria-labelledby="audit-title">
        <header>
          <div><span className="eyebrow">SOLA LETTURA</span><h2 id="audit-title">Audit operazioni</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        {optionalFeatures && (
          <div className="audit-optional-features" aria-label="Funzioni opzionali attive">
            <span className="eyebrow">FUNZIONI OPZIONALI</span>
            <ul>
              {Object.entries(optionalFeatures).map(([name, enabled]) => (
                <li key={name}>
                  <span>{OPTIONAL_FEATURE_LABEL[name] ?? name}</span>
                  <strong>{enabled ? "attiva" : "disattiva"}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="snapshot-existing audit-list">
          {loading && <p className="empty">Caricamento…</p>}
          {!loading && events.map((event) => (
            <article className="snapshot-card" key={event.id}>
              <div>
                <strong>{event.action}</strong>
                <small>{event.actor} · HTTP {event.outcome}</small>
                <small>{event.target}</small>
                <small>{new Date(event.created_at).toLocaleString()}</small>
              </div>
            </article>
          ))}
          {!loading && events.length === 0 && <p className="empty">Nessun evento registrato.</p>}
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}

function BackupModal({ onClose }: { onClose: () => void }) {
  const [backups, setBackups] = useState<Backup[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setBackups(await listBackups());
  }

  useEffect(() => {
    refresh()
      .catch((value) => setError(errorMessage(value)))
      .finally(() => setLoading(false));
  }, []);

  async function create() {
    setCreating(true);
    setError("");
    try {
      await createBackup();
      await refresh();
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setCreating(false);
    }
  }

  async function remove(item: Backup) {
    if (!window.confirm(`Eliminare definitivamente il backup del ${formatDate(item.created_at)}?`)) return;
    setBusyId(item.id);
    setError("");
    try {
      await deleteBackup(item.id);
      await refresh();
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="help-modal snapshot-modal" role="dialog" aria-modal="true" aria-labelledby="backup-title">
        <header>
          <div><span className="eyebrow">DATI PERSISTENTI</span><h2 id="backup-title">Backup</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        <p className="empty">Include database applicativo e snapshot. Il restore si esegue offline.</p>
        <button className="new-session backup-create" disabled={creating} onClick={() => void create()}>
          {creating ? "Creazione…" : "Crea backup"}
        </button>
        <div className="snapshot-existing">
          {loading && <p className="empty">Caricamento…</p>}
          {!loading && backups.map((item) => (
            <article className="snapshot-card" key={item.id}>
              <div>
                <strong>{formatDate(item.created_at)}</strong>
                <small>{formatSize(item.size)} · {item.files} file</small>
                <small title={item.sha256}>SHA-256: {item.sha256.slice(0, 16)}…</small>
              </div>
              <div className="snapshot-actions">
                <a className="backup-download" href={backupDownloadUrl(item.id)}>Scarica</a>
                <button className="danger" disabled={busyId === item.id} onClick={() => void remove(item)}>
                  Elimina
                </button>
              </div>
            </article>
          ))}
          {!loading && backups.length === 0 && <p className="empty">Nessun backup disponibile.</p>}
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}

function UserModal({ onClose }: { onClose: () => void }) {
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [error, setError] = useState("");

  async function refresh() {
    setUsers(await listUsers());
  }

  useEffect(() => {
    refresh().catch((value) => setError(errorMessage(value)));
  }, []);

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="help-modal user-modal" role="dialog" aria-modal="true" aria-labelledby="users-title">
        <header>
          <div><span className="eyebrow">ACCESSI</span><h2 id="users-title">Utenti</h2></div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        <form className="user-create" onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          try {
            await createUser(username, password, role);
            setUsername("");
            setPassword("");
            await refresh();
          } catch (value) {
            setError(errorMessage(value));
          }
        }}>
          <input required pattern="[A-Za-z0-9_-]{1,64}" placeholder="Nome utente" value={username} onChange={(event) => setUsername(event.target.value)} />
          <input required minLength={16} type="password" autoComplete="new-password" placeholder="Password (minimo 16 caratteri)" value={password} onChange={(event) => setPassword(event.target.value)} />
          <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
            <option value="viewer">Viewer · sola lettura</option>
            <option value="operator">Operator · controllo sessioni</option>
            <option value="admin">Admin · gestione completa</option>
          </select>
          <button type="submit">Crea utente</button>
        </form>
        {error && <p className="error">{error}</p>}
        <div className="user-list">
          {users.map((user) => (
            <article key={user.username}>
              <span><strong>{user.username}</strong><small>{user.role}</small></span>
              <button type="button" onClick={async () => {
                setError("");
                try {
                  await setUserActive(user.username, !user.active);
                  await refresh();
                } catch (value) {
                  setError(errorMessage(value));
                }
              }}>
                {user.active ? "Disattiva" : "Riattiva"}
              </button>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

const HOST_STATUS_LABEL: Record<HostComponent["status"], string> = {
  ok: "Regolare",
  warning: "Attenzione",
  critical: "Critico",
  unknown: "Parziale",
};

const HOST_REASON_LABEL: Record<string, string> = {
  memory_unavailable: "Memoria non disponibile",
  memory_available_critical: "Memoria disponibile critica",
  memory_available_low: "Memoria disponibile bassa",
  swap_used_critical: "Swap critica",
  swap_used_high: "Swap elevata",
  swap_sample_unavailable: "Campione attività swap non disponibile",
  swap_activity_high: "Attività swap elevata",
  swap_pressure_critical: "Pressione memoria e attività swap critiche",
  load_unavailable: "Carico non disponibile",
  load_critical: "Carico critico",
  load_high: "Carico elevato",
  filesystems_not_configured: "Filesystem non configurati",
  filesystem_used_critical: "Spazio disco critico",
  filesystem_used_high: "Spazio disco in esaurimento",
  filesystem_unavailable: "Filesystem non disponibile",
  processes_unavailable: "Processi non disponibili",
  processes_partial: "Elenco processi parziale",
  process_group_count_critical: "Troppi processi omonimi",
  process_group_count_high: "Molti processi omonimi",
  process_policy_count_critical: "Policy numero processi violata, livello critico",
  process_policy_count_high: "Policy numero processi violata, livello attenzione",
  process_policy_rss_critical: "Policy memoria aggregata violata, livello critico",
  process_policy_rss_high: "Policy memoria aggregata violata, livello attenzione",
  listeners_unavailable: "Porte in ascolto non disponibili",
  listeners_partial: "Elenco porte parziale",
  wildcard_listener_unexpected: "Porta wildcard inattesa",
  tcp_listener_unexpected: "Porta TCP inattesa",
  docker_disabled: "Docker disabilitato",
  docker_unavailable: "Docker non disponibile",
  docker_output_excessive: "Risposta Docker troppo grande",
  docker_output_invalid: "Risposta Docker non valida",
  containers_problematic: "Container con problemi",
};

const HOST_PROCESS_POLICY_LABEL = {
  not_configured: "Policy locale non configurata",
  within_limits: "Entro i limiti della policy locale",
  violated: "Policy locale violata",
} as const;

const HOST_LISTENER_POLICY_LABEL = {
  not_configured: "Policy locale non configurata",
  allowed: "Bind consentito dalla policy locale",
  violated: "Policy locale violata",
} as const;

const HOST_EMPTY_ASSESSMENT_LABEL: Record<HostComponent["status"], string> = {
  ok: "Nessuna anomalia rilevata dai controlli disponibili.",
  warning: "Attenzione rilevata; il collector non ha fornito un dettaglio della valutazione.",
  critical: "Stato critico rilevato; il collector non ha fornito un dettaglio della valutazione.",
  unknown: "Valutazione non disponibile: l’esito non è accertato.",
};

function HostStatusBadge({ status }: { status: HostComponent["status"] }) {
  return <span className={`host-status ${status}`}>{HOST_STATUS_LABEL[status]}</span>;
}

function HostReasons({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <ul className="host-reasons" aria-label="Dettagli stato">
      {reasons.map((reason) => (
        <li key={reason}>{HOST_REASON_LABEL[reason] ?? reason.replaceAll("_", " ")}</li>
      ))}
    </ul>
  );
}

function HostCard({
  title,
  component,
  children,
}: {
  title: string;
  component: HostComponent;
  children: ReactNode;
}) {
  return (
    <details className={`host-card status-${component.status}`}>
      <summary>
        <h2>{title}</h2>
        <HostStatusBadge status={component.status} />
      </summary>
      <div className="host-card-body">
        <div className="host-assessment" aria-label={`Valutazione ${title}`}>
          <span className="eyebrow">VALUTAZIONE</span>
          {component.reasons.length > 0 ? (
            <HostReasons reasons={component.reasons} />
          ) : (
            <p>{HOST_EMPTY_ASSESSMENT_LABEL[component.status]}</p>
          )}
        </div>
        <h3 className="host-facts-heading">Fatti locali</h3>
        {children}
      </div>
    </details>
  );
}

function HostMetric({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

type BudgetHoursOption = 6 | 24 | 168;

// Colore categorico per serie, assegnato per posizione e mai ciclato. Nel
// grafico l'asse verticale codifica gia' la percentuale: colorare anche la
// linea in base al valore spenderebbe il canale colore per un'informazione
// gia' mostrata dalla posizione, sottraendolo all'identita' della serie, che
// non ha nessun'altra codifica. Il risultato era che uno stesso 5h cambiava
// tinta attraversando un reset e sembrava una terza serie senza legenda.
// Tinte validate sulla superficie #101713 del grafico: separazione per
// daltonismo ΔE 26.8, visione normale 31.8, contrasto oltre 3:1.
const BUDGET_SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500"];
const BUDGET_SERIES_FALLBACK = "#8fa397";

function budgetSeriesColor(index: number): string {
  return BUDGET_SERIES_COLORS[index] ?? BUDGET_SERIES_FALLBACK;
}

const BUDGET_RANGE_OPTIONS: { label: string; hours: BudgetHoursOption }[] = [
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7g", hours: 168 },
];

// Etichette privilegiate quando si sceglie quali due finestre disegnare: il
// contratto ammette anche "primaria"/"secondaria" per provider diversi da
// Claude, quindi la selezione resta dinamica (vedi budgetSeriesLabels) e
// queste sono solo l'ordine preferito quando presenti entrambe.
const BUDGET_WINDOW_LABELS = ["5h", "7d"];

type BudgetPoint = {
  t: number;
  y: number;
  resetsAt: number | null;
  stale: boolean;
};

type BudgetChain = {
  points: BudgetPoint[];
  stale: boolean;
};

function budgetSeriesLabels(samples: RateLimitHistorySample[]): string[] {
  const seen = new Set<string>();
  for (const sample of samples) {
    for (const window of sample.windows) seen.add(window.label);
  }
  const ordered = BUDGET_WINDOW_LABELS.filter((label) => seen.has(label));
  for (const label of seen) if (!ordered.includes(label)) ordered.push(label);
  return ordered.slice(0, 2);
}

function budgetPointsForLabel(samples: RateLimitHistorySample[], label: string): BudgetPoint[] {
  const points: BudgetPoint[] = [];
  for (const sample of samples) {
    const window = sample.windows.find((item) => item.label === label);
    if (!window || window.used_percent === null) continue;
    const t = new Date(sample.sampled_at).getTime();
    if (!Number.isFinite(t)) continue;
    points.push({ t, y: window.used_percent, resetsAt: window.resets_at, stale: sample.stale });
  }
  return points;
}

// Costruisce le spezzate da disegnare per una finestra di quota (5h/7d):
// interrompe la linea quando `resets_at` cambia, perché la finestra
// scorrevole riparte da zero e la sua discesa fisiologica non deve leggersi
// come un calo di consumo (contratto storico budget v1, sezione "serie
// storica della quota"). All'interno di uno stesso reset isola invece i
// tratti che toccano un campione stantio: restano collegati (stesso reset,
// continuità fisica) ma sono marcati per il tratteggio, perché un campione
// stantio descrive un'osservazione vecchia e non va mai interpolato come se
// fosse una misura corrente.
function buildBudgetChains(points: BudgetPoint[]): BudgetChain[] {
  const chains: BudgetChain[] = [];
  let current: BudgetPoint[] = [];
  let currentStale = false;
  for (const point of points) {
    if (current.length === 0) {
      current = [point];
      continue;
    }
    const previous = current[current.length - 1];
    const sameReset = previous.resetsAt === point.resetsAt;
    if (!sameReset) {
      chains.push({ points: current, stale: currentStale });
      current = [point];
      currentStale = false;
      continue;
    }
    const edgeStale = previous.stale || point.stale;
    if (current.length > 1 && edgeStale !== currentStale) {
      chains.push({ points: current, stale: currentStale });
      current = [previous, point];
      currentStale = edgeStale;
      continue;
    }
    currentStale = edgeStale;
    current.push(point);
  }
  if (current.length > 0) chains.push({ points: current, stale: currentStale });
  return chains;
}

// Crescita della quota dall'ultimo reset osservato, non sull'intero
// intervallo scelto: un delta calcolato attraverso reset multipli (la
// finestra 5h può resettarsi più volte in 24h/7g) sottostimerebbe la
// crescita reale, esattamente l'errore di lettura che la segmentazione del
// grafico evita di mostrare (contratto storico budget v1).
function growthForLabel(samples: RateLimitHistorySample[], label: string): number | null {
  const points = budgetPointsForLabel(samples, label);
  if (points.length === 0) return null;
  const lastResetsAt = points[points.length - 1].resetsAt;
  let start = points.length - 1;
  while (start > 0 && points[start - 1].resetsAt === lastResetsAt) start -= 1;
  const run = points.slice(start);
  if (run.length < 2) return null;
  return run[run.length - 1].y - run[0].y;
}

function formatSignedPercent(value: number | null): string {
  if (value === null) return "n/d";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)} pt`;
}

const BUDGET_CHART_WIDTH = 320;
const BUDGET_CHART_HEIGHT = 130;
const BUDGET_CHART_PAD = { top: 10, right: 8, bottom: 8, left: 26 };

function BudgetProviderChart({
  provider,
  samples,
}: {
  provider: string;
  samples: RateLimitHistorySample[];
}) {
  const labels = useMemo(() => budgetSeriesLabels(samples), [samples]);
  const series = useMemo(
    () => labels.map((label) => ({ label, points: budgetPointsForLabel(samples, label) })),
    [labels, samples],
  );
  const allPoints = series.flatMap((item) => item.points);
  if (allPoints.length === 0) return null;
  // Stesso principio del badge `stale`: riferisce un fatto sulla riga più
  // recente ("il fallback testuale è attivo per questo provider"), non un
  // giudizio. `null`/assente (righe pre-BH-03) non genera l'avviso: "non
  // noto" non è "testuale".
  const latestParseMode = samples.length > 0 ? samples[samples.length - 1].parse_mode : null;
  const textFallbackActive = latestParseMode === "text";

  const minT = Math.min(...allPoints.map((point) => point.t));
  const maxT = Math.max(...allPoints.map((point) => point.t));
  const innerWidth = BUDGET_CHART_WIDTH - BUDGET_CHART_PAD.left - BUDGET_CHART_PAD.right;
  const innerHeight = BUDGET_CHART_HEIGHT - BUDGET_CHART_PAD.top - BUDGET_CHART_PAD.bottom;
  const x = (t: number) => (
    BUDGET_CHART_PAD.left + (maxT === minT ? innerWidth / 2 : ((t - minT) / (maxT - minT)) * innerWidth)
  );
  const y = (value: number) => (
    BUDGET_CHART_PAD.top + (1 - Math.max(0, Math.min(100, value)) / 100) * innerHeight
  );

  return (
    <figure className="budget-chart" aria-label={`Andamento quota ${provider}`}>
      <figcaption>{provider}</figcaption>
      <svg
        viewBox={`0 0 ${BUDGET_CHART_WIDTH} ${BUDGET_CHART_HEIGHT}`}
        role="img"
        aria-label={`Grafico quota ${provider}: percentuale utilizzata nel tempo, per finestra`}
      >
        {[0, 50, 100].map((tick) => (
          <g key={tick}>
            <line
              x1={BUDGET_CHART_PAD.left}
              x2={BUDGET_CHART_WIDTH - BUDGET_CHART_PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              className="budget-chart-grid"
            />
            <text x={1} y={y(tick) + 3} className="budget-chart-tick">{tick}</text>
          </g>
        ))}
        {series.map((item, index) => (
          <g key={item.label} className={`budget-line budget-line-${index}`}>
            {buildBudgetChains(item.points).map((chain, chainIndex) => (
              chain.points.length > 1 ? (
                <polyline
                  key={chainIndex}
                  points={chain.points.map((point) => `${x(point.t)},${y(point.y)}`).join(" ")}
                  fill="none"
                  className={chain.stale ? "budget-segment-stale" : "budget-segment"}
                  stroke={chain.stale ? undefined : budgetSeriesColor(index)}
                >
                  <title>
                    {`${item.label}: ${chain.points[chain.points.length - 1].y.toFixed(1)}% · `
                      + `${new Date(chain.points[chain.points.length - 1].t).toLocaleString()}`
                      + (chain.stale ? " · dato non recente, non interpolato" : "")}
                  </title>
                </polyline>
              ) : (
                <circle
                  key={chainIndex}
                  cx={x(chain.points[0].t)}
                  cy={y(chain.points[0].y)}
                  r={2.4}
                  className={chain.stale ? "budget-segment-stale" : "budget-segment"}
                  fill={chain.stale ? undefined : budgetSeriesColor(index)}
                />
              )
            ))}
          </g>
        ))}
      </svg>
      <div className="budget-chart-legend">
        {series.map((item, index) => (
          <span key={item.label} className={`budget-line-${index}`}>
            <i aria-hidden="true" style={{ background: budgetSeriesColor(index) }} /> {item.label}
            {item.points.length > 0 && (
              <strong style={{ color: rateLimitColor(item.points[item.points.length - 1].y) }}>
                {" "}{item.points[item.points.length - 1].y.toFixed(1)}%
              </strong>
            )}
          </span>
        ))}
        <span className="budget-legend-stale"><i aria-hidden="true" /> dato non recente (non interpolato)</span>
      </div>
      {textFallbackActive && (
        <p className="budget-note budget-parse-mode-note">
          Fallback testuale attivo per questo provider: l'ultimo campione non proviene dalla forma strutturata.
        </p>
      )}
    </figure>
  );
}

function hasBudgetUsage(totals: SessionUsageTotals): boolean {
  return totals.turns > 0
    || totals.input_tokens > 0
    || totals.cache_creation_input_tokens > 0
    || totals.cache_read_input_tokens > 0
    || totals.output_tokens > 0;
}

function BudgetTotalsRow({
  label,
  totals,
  emphasis,
}: {
  label: string;
  totals: SessionUsageTotals;
  emphasis?: boolean;
}) {
  return (
    <div className={`budget-totals-row${emphasis ? " emphasis" : ""}`}>
      <span className="budget-totals-label">{label}</span>
      <span className="budget-totals-figures">
        <span title="Turni (risposte del modello, deduplicate)">{totals.turns} turni</span>
        <span title="Token di input">in {totals.input_tokens.toLocaleString("it-IT")}</span>
        <span title="Token di scrittura cache">cache scritta {totals.cache_creation_input_tokens.toLocaleString("it-IT")}</span>
        <span title="Token di rilettura cache">cache letta {totals.cache_read_input_tokens.toLocaleString("it-IT")}</span>
        <span title="Token di output">out {totals.output_tokens.toLocaleString("it-IT")}</span>
      </span>
    </div>
  );
}

function BudgetRankingItem({
  entry,
  sessionsById,
  onOpenSession,
  peakBucket,
  onOpenTimeline,
}: {
  entry: SessionUsageEntry;
  sessionsById: Map<string, Session>;
  onOpenSession: (session: Session) => void;
  peakBucket: SessionUsageBucket | null;
  onOpenTimeline: (bucket: SessionUsageBucket) => void;
}) {
  const linkedSession = entry.tmux_session_id ? sessionsById.get(entry.tmux_session_id) : undefined;
  return (
    <article className="budget-rank-item">
      <header>
        <span className="budget-rank-project">{entry.project || "progetto non registrato"}</span>
        <span className={`budget-origin-badge origin-${entry.origin === "mac" ? "mac" : "headless"}`}>
          {entry.origin === "mac" ? "MAC" : "headless"}
        </span>
      </header>
      <small className="budget-rank-models">
        {entry.models.length > 0 ? entry.models.join(", ") : "modello non registrato"}
      </small>
      {/* Il fan-out di subagent va mostrato annidato sotto la sessione madre
          (blocco `subagents`), perché può pesare più della sessione che lo
          genera: è il punto di valore della classifica (contratto storico
          budget v1). Nessuna percentuale di quota per riga: non è
          ricostruibile dai contatori di token, si mostrano solo i token. */}
      <div className="budget-rank-totals">
        <BudgetTotalsRow label="Sessione" totals={entry.own} />
        {hasBudgetUsage(entry.subagents) && (
          <div className="budget-subagent-row">
            <BudgetTotalsRow label="↳ Subagent" totals={entry.subagents} />
          </div>
        )}
        <BudgetTotalsRow label="Totale" totals={entry.total} emphasis />
      </div>
      <div className="budget-rank-actions">
        {entry.origin === "mac" && linkedSession && (
          <button type="button" className="budget-open-console" onClick={() => onOpenSession(linkedSession)}>
            Apri console
          </button>
        )}
        {peakBucket && (
          <button
            type="button"
            className="budget-open-timeline"
            onClick={() => onOpenTimeline(peakBucket)}
          >
            Vedi il picco dei turni
          </button>
        )}
      </div>
    </article>
  );
}

const TOOL_CATEGORY_LABEL: Record<string, string> = {
  file_read: "Lettura file",
  file_write: "Scrittura file",
  exec: "Esecuzione comandi",
  network: "Rete/Web",
  task_management: "Gestione task",
  subagent_orchestration: "Orchestrazione subagent",
  other: "Altro",
};

function SessionTimelineModal({
  bucket,
  onClose,
}: {
  bucket: SessionUsageBucket;
  onClose: () => void;
}) {
  const [timeline, setTimeline] = useState<SessionTimelineWindow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setTimeline(null);
    fetchSessionTimeline(bucket.provider, bucket.session_uuid, bucket.bucket_start)
      .then((next) => {
        if (active) setTimeline(next);
      })
      .catch((value) => {
        if (active) setError(errorMessage(value));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [bucket.provider, bucket.session_uuid, bucket.bucket_start]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const isEmpty = timeline?.available
    && timeline.turns.length === 0
    && timeline.compactions.length === 0
    && timeline.subagent_spawns.length === 0;

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="help-modal snapshot-modal session-timeline-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-timeline-title"
      >
        <header>
          <div>
            <span className="eyebrow">DRILL-DOWN TURNI · SOLO METADATI</span>
            <h2 id="session-timeline-title" ref={headingRef} tabIndex={-1} className="host-focus-target">
              Picco {formatDate(bucket.bucket_start)}
            </h2>
            <small>{bucket.project || "progetto non registrato"} · {bucket.provider}</small>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Chiudi">×</button>
        </header>
        <p aria-live="polite" role="status" className="session-timeline-status">
          {loading && "Caricamento timeline…"}
          {!loading && !error && timeline && !timeline.available
            && "Transcript non più disponibile per questo bucket (ruotato o rimosso)."}
          {!loading && !error && isEmpty && "Nessun turno registrato in questa finestra di 5 minuti."}
        </p>
        {error && <p className="error" role="alert">{error}</p>}
        {!loading && !error && timeline && timeline.available && !isEmpty && (
          <div className="session-timeline-body">
            {timeline.turns.length > 0 && (
              <ul className="session-timeline-turns">
                {timeline.turns.map((turn, index) => (
                  <li key={`${turn.timestamp}-${index}`}>
                    <strong>{new Date(turn.timestamp).toLocaleTimeString("it-IT")}</strong>
                    <span>{turn.model || "modello non registrato"}</span>
                    <span className="session-timeline-tokens">
                      in {turn.input_tokens.toLocaleString("it-IT")} · cache scritta{" "}
                      {turn.cache_creation_input_tokens.toLocaleString("it-IT")} · cache letta{" "}
                      {turn.cache_read_input_tokens.toLocaleString("it-IT")} · out{" "}
                      {turn.output_tokens.toLocaleString("it-IT")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {Object.keys(timeline.tool_counts).length > 0 && (
              <div className="session-timeline-tools">
                <h3>Strumenti usati (per categoria, mai il nome grezzo)</h3>
                <ul>
                  {Object.entries(timeline.tool_counts).map(([category, count]) => (
                    <li key={category}>
                      <span>{TOOL_CATEGORY_LABEL[category] ?? category}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {timeline.compactions.length > 0 && (
              <div className="session-timeline-events">
                <h3>Compattazioni del contesto</h3>
                <ul>
                  {timeline.compactions.map((item, index) => (
                    <li key={index}>
                      {new Date(item.timestamp).toLocaleTimeString("it-IT")}
                      {item.pre_tokens !== null && item.post_tokens !== null
                        ? ` · ${item.pre_tokens.toLocaleString("it-IT")} → ${item.post_tokens.toLocaleString("it-IT")} token`
                        : " · delta token non disponibile per questo provider"}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {timeline.subagent_spawns.length > 0 && (
              <div className="session-timeline-events">
                <h3>Spawn di subagent</h3>
                <ul>
                  {timeline.subagent_spawns.map((item, index) => (
                    <li key={index}>{new Date(item.timestamp).toLocaleTimeString("it-IT")}</li>
                  ))}
                </ul>
              </div>
            )}
            {timeline.truncated && (
              <p className="budget-note">
                Il transcript è stato letto solo in parte (limite di dimensione): i dati sopra potrebbero
                essere incompleti.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function BudgetView({
  onBack,
  sessions,
  onOpenSession,
  rateLimitFreshEnabled,
  sessionUsageEnabled,
  sessionTimelineEnabled,
}: {
  onBack: () => void;
  sessions: Session[];
  onOpenSession: (session: Session) => void;
  rateLimitFreshEnabled: boolean;
  sessionUsageEnabled: boolean;
  sessionTimelineEnabled: boolean;
}) {
  const [hours, setHours] = useState<BudgetHoursOption>(24);
  const [history, setHistory] = useState<RateLimitHistory | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [usage, setUsage] = useState<SessionUsageReport | null>(null);
  const [usageError, setUsageError] = useState("");
  const [usageDisabled, setUsageDisabled] = useState(false);
  const [usageLoading, setUsageLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const [openTimelineBucket, setOpenTimelineBucket] = useState<SessionUsageBucket | null>(null);
  const mounted = useRef(false);
  const historyVersion = useRef(0);
  const usageVersion = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);

  async function loadHistory(rangeHours: BudgetHoursOption) {
    const version = ++historyVersion.current;
    if (mounted.current) {
      setHistoryLoading(true);
      setHistoryError("");
    }
    try {
      const next = await fetchRateLimitHistory(rangeHours, 3000);
      if (mounted.current && version === historyVersion.current) setHistory(next);
    } catch (value) {
      if (mounted.current && version === historyVersion.current) setHistoryError(errorMessage(value));
    } finally {
      if (mounted.current && version === historyVersion.current) setHistoryLoading(false);
    }
  }

  async function loadUsage(rangeHours: BudgetHoursOption) {
    const version = ++usageVersion.current;
    // Il flag di config è noto in anticipo (non serve una risposta 404 per
    // scoprirlo): risparmia la richiesta quando l'attribuzione è disattivata.
    // Il ramo 404 sotto resta comunque come fallback per un flag non ancora
    // propagato o un endpoint temporaneamente indietro rispetto al config.
    if (!sessionUsageEnabled) {
      if (mounted.current && version === usageVersion.current) {
        setUsageDisabled(true);
        setUsage(null);
      }
      return;
    }
    if (mounted.current) {
      setUsageLoading(true);
      setUsageError("");
    }
    try {
      const next = await fetchSessionUsage(rangeHours, 50);
      if (mounted.current && version === usageVersion.current) {
        setUsage(next);
        setUsageDisabled(false);
      }
    } catch (value) {
      if (mounted.current && version === usageVersion.current) {
        // 404: l'attribuzione per sessione può non essere ancora abilitata
        // lato backend (endpoint in corso su un altro modulo) — degradare
        // mostrando comunque il grafico "quando", non un errore.
        if (value instanceof ApiError && value.status === 404) {
          setUsageDisabled(true);
          setUsage(null);
        } else {
          setUsageError(errorMessage(value));
        }
      }
    } finally {
      if (mounted.current && version === usageVersion.current) setUsageLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      historyVersion.current += 1;
      usageVersion.current += 1;
    };
  }, []);

  useEffect(() => {
    void loadHistory(hours);
    void loadUsage(hours);
    // Ricarica quando cambia l'intervallo scelto dall'utente o quando il
    // flag di abilitazione arriva (in genere già noto, ma il fetch di
    // /api/v1/config può risolversi dopo il primo montaggio della vista).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, sessionUsageEnabled]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  async function forceRefresh() {
    setRefreshing(true);
    setRefreshMessage("");
    try {
      await refreshRateLimits();
      if (mounted.current) setRefreshMessage("Campione fresco raccolto: storico aggiornato.");
      await loadHistory(hours);
    } catch (value) {
      if (!mounted.current) return;
      if (value instanceof ApiError && value.status === 429) {
        setRefreshMessage("Troppi aggiornamenti ravvicinati: attendi qualche secondo e riprova.");
      } else if (value instanceof ApiError && value.status === 503) {
        setRefreshMessage("Il collector della quota non è raggiungibile sull'host. Riprova più tardi.");
      } else if (value instanceof ApiError && value.status === 504) {
        setRefreshMessage("Il collector della quota ha impiegato troppo tempo a rispondere. Riprova più tardi.");
      } else {
        setRefreshMessage(errorMessage(value));
      }
    } finally {
      if (mounted.current) setRefreshing(false);
    }
  }

  const sessionsById = useMemo(() => {
    const map = new Map<string, Session>();
    for (const session of sessions) map.set(session.id, session);
    return map;
  }, [sessions]);

  const providers = useMemo(() => {
    const ordered: string[] = [];
    for (const sample of history?.samples ?? []) {
      if (!ordered.includes(sample.provider)) ordered.push(sample.provider);
    }
    return ordered;
  }, [history]);

  const providerGrowth = useMemo(() => (
    providers.map((provider) => {
      const providerSamples = (history?.samples ?? []).filter((sample) => sample.provider === provider);
      const labels = budgetSeriesLabels(providerSamples);
      return {
        provider,
        series: labels.map((label) => ({ label, growth: growthForLabel(providerSamples, label) })),
      };
    })
  ), [providers, history]);

  // Bucket di picco per sessione: entry point del drill-down BH-04. Ordinato
  // con la stessa chiave della classifica (`ranking_tokens`, contratto
  // storico budget v1: input + cache di scrittura + output, esclusa la
  // rilettura di cache per non far dominare il picco da un contesto grande
  // e statico).
  const peakBucketByEntry = useMemo(() => {
    const peaks = new Map<string, SessionUsageBucket>();
    for (const row of usage?.buckets ?? []) {
      const current = peaks.get(row.session_uuid);
      const rowRanking = row.input_tokens + row.cache_creation_input_tokens + row.output_tokens;
      const currentRanking = current
        ? current.input_tokens + current.cache_creation_input_tokens + current.output_tokens
        : -1;
      if (!current || rowRanking > currentRanking) peaks.set(row.session_uuid, row);
    }
    return peaks;
  }, [usage]);

  const rankedEntries = usage?.entries ?? [];
  const totalTurnsAttributed = rankedEntries.reduce((sum, entry) => sum + entry.total.turns, 0);
  const totalTokensAttributed = rankedEntries.reduce(
    (sum, entry) => sum + entry.total.input_tokens + entry.total.cache_creation_input_tokens
      + entry.total.cache_read_input_tokens + entry.total.output_tokens,
    0,
  );

  return (
    <main className="shell budget-view">
      <header className="host-topbar">
        <button className="icon-button" onClick={onBack} aria-label="Torna alle sessioni">‹</button>
        <div>
          <span className="eyebrow">BUDGET PROVIDER</span>
          <h1 ref={headingRef} className="host-focus-target" tabIndex={-1}>Budget</h1>
          <small>Quando è stato consumato e chi lo ha consumato</small>
        </div>
        <button
          className="host-refresh"
          onClick={() => { void loadHistory(hours); void loadUsage(hours); }}
          disabled={historyLoading || usageLoading}
          aria-label="Aggiorna vista budget"
        >
          {historyLoading || usageLoading ? "Aggiorno…" : "Aggiorna"}
        </button>
      </header>

      <div className="budget-range-selector" role="group" aria-label="Intervallo">
        {BUDGET_RANGE_OPTIONS.map((option) => (
          <button
            key={option.hours}
            type="button"
            aria-pressed={hours === option.hours}
            onClick={() => setHours(option.hours)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="budget-content">
        <section className="budget-section" aria-label="Quando è stato consumato il budget">
          <h2>Quando</h2>
          {historyLoading && !history && <p role="status">Caricamento storico quota…</p>}
          {historyError && <p className="error" role="alert">{historyError}</p>}
          {!historyError && history && history.samples.length === 0 && (
            <p className="budget-empty">
              Ancora nessun campione nell'intervallo selezionato: i campioni si stanno accumulando.
            </p>
          )}
          {!historyError && history && history.samples.length > 0 && (
            <div className="budget-charts">
              {providers.map((provider) => (
                <BudgetProviderChart
                  key={provider}
                  provider={provider}
                  samples={history.samples.filter((sample) => sample.provider === provider)}
                />
              ))}
            </div>
          )}
          {rateLimitFreshEnabled && (
            <div className="budget-force-refresh">
              <button type="button" onClick={() => void forceRefresh()} disabled={refreshing}>
                {refreshing ? "Aggiorno…" : "Aggiorna adesso"}
              </button>
              {refreshMessage && <p className="budget-refresh-message" aria-live="polite">{refreshMessage}</p>}
            </div>
          )}
        </section>

        <section className="budget-section" aria-label="Chi ha consumato il budget">
          <h2>Chi</h2>
          {usageLoading && !usage && !usageDisabled && <p role="status">Caricamento consumo per sessione…</p>}
          {usageDisabled && (
            <p className="budget-empty">
              L'attribuzione del consumo per sessione non è abilitata su questo backend: resta visibile solo
              l'andamento della quota qui sopra.
            </p>
          )}
          {usageError && <p className="error" role="alert">{usageError}</p>}
          {!usageDisabled && !usageError && usage && rankedEntries.length === 0 && (
            <p className="budget-empty">Nessun consumo attribuito nell'intervallo selezionato.</p>
          )}
          {!usageDisabled && !usageError && rankedEntries.length > 0 && (
            <>
              <div className="budget-rank-list">
                {rankedEntries.map((entry) => (
                  <BudgetRankingItem
                    key={entry.session_uuid}
                    entry={entry}
                    sessionsById={sessionsById}
                    onOpenSession={onOpenSession}
                    peakBucket={
                      sessionTimelineEnabled
                        ? peakBucketByEntry.get(entry.session_uuid) ?? null
                        : null
                    }
                    onOpenTimeline={setOpenTimelineBucket}
                  />
                ))}
              </div>
              <div className="budget-residual" aria-label="Residuo non attribuito">
                <h3>Residuo</h3>
                <p>
                  Crescita osservata della quota dall'ultimo reset:{" "}
                  {providerGrowth.map(({ provider, series }) => (
                    <span key={provider} className="budget-residual-figure">
                      <strong>{provider}</strong>{" "}
                      {series.map((item) => `${item.label} ${formatSignedPercent(item.growth)}`).join(" · ")}
                    </span>
                  ))}
                </p>
                <p>
                  Consumo attribuito nello stesso intervallo: {totalTurnsAttributed} turni,{" "}
                  {totalTokensAttributed.toLocaleString("it-IT")} token complessivi su {rankedEntries.length}{" "}
                  session{rankedEntries.length === 1 ? "e" : "i"}.
                </p>
                <p className="budget-note">
                  Percentuale di quota e conteggio di token non sono convertibili nella stessa unità (contratto
                  storico budget v1): non esiste quindi un residuo numerico unico. Quando la crescita della quota
                  non è spiegata per intero dalle sessioni elencate sopra, la differenza è consumo proveniente da
                  altre macchine sullo stesso account o da client non osservati — non un difetto della raccolta.
                </p>
              </div>
            </>
          )}
        </section>
      </div>
      {openTimelineBucket && (
        <SessionTimelineModal
          bucket={openTimelineBucket}
          onClose={() => setOpenTimelineBucket(null)}
        />
      )}
    </main>
  );
}

function HostView({ onBack }: { onBack: () => void }) {
  const [snapshot, setSnapshot] = useState<HostObservabilitySnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copyFeedback, setCopyFeedback] = useState("");
  const mounted = useRef(false);
  const requestVersion = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const jsonTextareaRef = useRef<HTMLTextAreaElement>(null);

  async function refresh() {
    const version = ++requestVersion.current;
    if (mounted.current) {
      setLoading(true);
      setError("");
    }
    try {
      const next = await fetchHostObservability();
      if (mounted.current && version === requestVersion.current) {
        setSnapshot(next);
        setCopyFeedback("");
      }
    } catch (value) {
      if (mounted.current && version === requestVersion.current) setError(errorMessage(value));
    } finally {
      if (mounted.current && version === requestVersion.current) setLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      requestVersion.current += 1;
    };
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const displayedListeners = snapshot ? (
    snapshot.schema_version === 2
      ? snapshot.listeners.items
      : snapshot.listeners.items.filter((item) => !item.expected)
  ) : [];
  const collectedAt = snapshot ? new Date(snapshot.collected_at).getTime() : 0;
  const stale = snapshot !== null && (
    Boolean(error) || !Number.isFinite(collectedAt) || Date.now() - collectedAt > 2 * 60_000
  );
  const snapshotJson = snapshot ? JSON.stringify(snapshot, null, 2) : "";

  function selectJsonForManualCopy() {
    const textarea = jsonTextareaRef.current;
    if (!textarea) return;
    textarea.focus({ preventScroll: true });
    textarea.select();
    setCopyFeedback("Copia automatica non disponibile. JSON selezionato: usa il comando Copia del dispositivo.");
  }

  async function copySnapshotJson() {
    if (!navigator.clipboard?.writeText) {
      selectJsonForManualCopy();
      return;
    }
    try {
      await navigator.clipboard.writeText(snapshotJson);
      if (mounted.current) setCopyFeedback("JSON copiato negli appunti.");
    } catch {
      if (mounted.current) selectJsonForManualCopy();
    }
  }

  return (
    <main
      className="shell host-view"
      data-observability-version={snapshot?.schema_version ?? "loading"}
    >
      <header className="host-topbar">
        <button className="icon-button" onClick={onBack} aria-label="Torna alle sessioni">‹</button>
        <div>
          <span className="eyebrow">OSSERVABILITÀ HOST</span>
          <h1 ref={headingRef} className="host-focus-target" tabIndex={-1}>Host</h1>
          <small>{snapshot ? `Fotografia ${formatDate(snapshot.collected_at)}` : "Fotografia su richiesta"}</small>
        </div>
        <button
          className="host-refresh"
          onClick={() => void refresh()}
          disabled={loading}
          aria-label="Aggiorna osservabilità host"
        >
          {loading ? "Aggiorno…" : "Aggiorna"}
        </button>
      </header>

      <div className="host-live" aria-live="polite" aria-atomic="true">
        {loading && !snapshot && <p role="status">Caricamento fotografia host…</p>}
        {loading && snapshot && <p role="status">Aggiornamento in corso; i dati correnti restano visibili.</p>}
        {error && (
          <div className="host-fetch-error" role="alert">
            <strong>Aggiornamento non riuscito.</strong>
            <span>{error}</span>
            {snapshot && <small>Mostro l’ultima fotografia valida.</small>}
            {!snapshot && <button onClick={() => void refresh()}>Riprova</button>}
          </div>
        )}
        {stale && <p className="host-stale">Dati non recenti: aggiorna prima di prendere decisioni operative.</p>}
      </div>

      {snapshot && (
        <div className="host-content">
          <section className={`host-summary status-${snapshot.status}`} aria-labelledby="host-summary-title">
            <div>
              <span className="eyebrow">STATO COMPLESSIVO</span>
              <h2 id="host-summary-title">{HOST_STATUS_LABEL[snapshot.status]}</h2>
              <small>
                Contratto {snapshot.schema_version === 1 ? "v1 legacy" : "v2"} · Raccolta in {snapshot.duration_ms} ms
              </small>
            </div>
            <HostStatusBadge status={snapshot.status} />
            <HostReasons reasons={snapshot.reasons} />
            <div className="host-component-statuses" aria-label="Stato componenti">
              {([
                ["Memoria", snapshot.memory],
                ["Carico", snapshot.load],
                ["Dischi", snapshot.filesystems],
                ["Processi", snapshot.processes],
                ["Porte", snapshot.listeners],
                ["Docker", snapshot.docker],
              ] as Array<[string, HostComponent]>).map(([label, component]) => (
                <span key={label}><i className={component.status} aria-hidden="true" />{label}: {HOST_STATUS_LABEL[component.status]}</span>
              ))}
            </div>
          </section>

          <details className="host-reading-guide">
            <summary id="host-reading-guide-title">Come leggere la fotografia</summary>
            <dl aria-labelledby="host-reading-guide-title">
              <div><dt>Fatti locali</dt><dd>Misure raccolte sull’host e scope di bind osservati.</dd></div>
              <div><dt>Valutazione</dt><dd>Esito derivato dalle soglie e dalle policy locali disponibili.</dd></div>
              <div><dt>Non accertato</dt><dd>Dato non raccolto o non verificato; non esprime un esito positivo.</dd></div>
            </dl>
          </details>

          <details
            className={`host-json-export${snapshot.status === "critical" ? " status-critical" : ""}`}
          >
            <summary>
              <span>Esporta snapshot JSON</span>
              {snapshot.status === "critical" && <strong>Stato critico</strong>}
            </summary>
            <div className="host-json-export-body">
              <p>È lo stesso snapshot sanitizzato mostrato in questa vista.</p>
              <textarea
                ref={jsonTextareaRef}
                value={snapshotJson}
                readOnly
                spellCheck={false}
                aria-label="JSON snapshot osservabilità host"
              />
              <button type="button" onClick={() => void copySnapshotJson()}>Copia JSON</button>
              <p className="host-copy-feedback" aria-live="polite" aria-atomic="true">{copyFeedback}</p>
            </div>
          </details>

          <div className="host-grid">
            <HostCard title="Memoria e swap" component={snapshot.memory}>
              <dl className="host-metrics">
                <HostMetric label="Disponibile" value={`${formatSize(snapshot.memory.available_bytes)} · ${formatPercent(snapshot.memory.available_percent)}`} />
                <HostMetric label="Totale" value={formatSize(snapshot.memory.total_bytes)} />
                <HostMetric label="Swap usata" value={`${formatSize(snapshot.memory.swap_used_bytes)} · ${formatPercent(snapshot.memory.swap_used_percent)}`} />
                <HostMetric label="Swap totale" value={formatSize(snapshot.memory.swap_total_bytes)} />
              </dl>
              {snapshot.schema_version === 2 && (
                <section className="host-sample" aria-label="Campione attività swap">
                  <h4>Campione attività swap</h4>
                  {snapshot.memory.swap_io_sample.available ? (
                    <dl>
                      <HostMetric label="Durata" value={`${snapshot.memory.swap_io_sample.duration_ms ?? "—"} ms`} />
                      <HostMetric label="Pagine lette" value={`${snapshot.memory.swap_io_sample.pages_in_delta ?? "—"}`} />
                      <HostMetric label="Pagine scritte" value={`${snapshot.memory.swap_io_sample.pages_out_delta ?? "—"}`} />
                    </dl>
                  ) : (
                    <p><strong>Non accertato.</strong> Il campione non è disponibile e non viene interpretato come attività zero.</p>
                  )}
                </section>
              )}
            </HostCard>

            <HostCard title="Carico" component={snapshot.load}>
              <dl className="host-metrics">
                <HostMetric label="1 minuto" value={snapshot.load.one?.toFixed(2) ?? "—"} />
                <HostMetric label="5 minuti" value={snapshot.load.five?.toFixed(2) ?? "—"} />
                <HostMetric label="15 minuti" value={snapshot.load.fifteen?.toFixed(2) ?? "—"} />
                <HostMetric label="1 min / CPU" value={snapshot.load.normalized_one?.toFixed(2) ?? "—"} />
              </dl>
              <p className="host-note">{snapshot.load.cpu_count === null ? "CPU non disponibile" : `${snapshot.load.cpu_count} CPU logiche`}</p>
            </HostCard>
          </div>

          <HostCard title="Filesystem" component={snapshot.filesystems}>
            {snapshot.filesystems.items.length === 0 ? <p className="host-empty">Nessun filesystem configurato.</p> : (
              <div className="host-item-grid">
                {snapshot.filesystems.items.map((item) => (
                  <article key={item.label} className={`host-item status-${item.status}`}>
                    <header><strong>{item.label}</strong><HostStatusBadge status={item.status} /></header>
                    <span>{formatPercent(item.used_percent)} usato</span>
                    <small>{formatSize(item.available_bytes)} disponibili su {formatSize(item.total_bytes)}</small>
                    <HostReasons reasons={item.reasons} />
                  </article>
                ))}
              </div>
            )}
          </HostCard>

          <HostCard title="Gruppi di processi" component={snapshot.processes}>
            <p className="host-note">{snapshot.processes.scanned} processi analizzati{snapshot.processes.truncated ? " · elenco troncato" : ""}</p>
            {snapshot.processes.groups.length === 0 ? <p className="host-empty">Nessun gruppo disponibile.</p> : (
              <div className="host-process-list">
                {snapshot.processes.groups.map((group) => (
                  <article key={group.name}>
                    <span><strong>{group.label ?? group.name}</strong><small>{group.label ? group.name : null}</small></span>
                    <span><strong>{group.count}×</strong><small>{formatSize(group.rss_bytes)} · più vecchio {formatAge(group.oldest_age_seconds)}</small></span>
                    {snapshot.schema_version === 2 && group.policy_status && (
                      <p className={`host-policy policy-${group.policy_status}`}>
                        Valutazione policy: {HOST_PROCESS_POLICY_LABEL[group.policy_status]}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </HostCard>

          <HostCard title="Processi con più memoria" component={snapshot.processes}>
            {snapshot.processes.top.length === 0 ? <p className="host-empty">Nessun processo disponibile.</p> : (
              <div className="host-process-list">
                {snapshot.processes.top.map((process) => (
                  <article key={process.pid}>
                    <span><strong>{process.label ?? process.name}</strong><small>{process.label ? process.name : `PID ${process.pid}`}</small></span>
                    <span><strong>{formatSize(process.rss_bytes)}</strong><small>attivo da {formatAge(process.age_seconds)}</small></span>
                  </article>
                ))}
              </div>
            )}
          </HostCard>

          <HostCard
            title={snapshot.schema_version === 2 ? "Listener TCP" : "Porte inattese"}
            component={snapshot.listeners}
          >
            {displayedListeners.length === 0 ? (
              <p className="host-empty">
                {snapshot.schema_version === 2 ? "Nessun listener TCP rilevato." : "Nessuna porta inattesa rilevata."}
              </p>
            ) : (
              <div className="host-item-grid">
                {displayedListeners.map((listener) => (
                  <article key={`${listener.port}-${"address_scope" in listener ? listener.address_scope : listener.bind_scope}-${listener.process_name ?? "unknown"}`} className={`host-item status-${listener.status}`}>
                    <header><strong>TCP {listener.port}</strong><HostStatusBadge status={listener.status} /></header>
                    <span>Bind locale: {"address_scope" in listener ? listener.address_scope : listener.bind_scope}</span>
                    <small>{listener.process_label ?? listener.process_name ?? "Processo non identificato"}</small>
                    {"policy_status" in listener && (
                      <small className={`host-policy policy-${listener.policy_status}`}>
                        Valutazione policy: {HOST_LISTENER_POLICY_LABEL[listener.policy_status]}
                      </small>
                    )}
                    {"external_reachability" in listener && (
                      <small className="host-not-assessed">
                        Raggiungibilità esterna: non accertata
                      </small>
                    )}
                  </article>
                ))}
              </div>
            )}
            <p className="host-note">
              {snapshot.schema_version === 2
                ? "La fotografia osserva il bind locale; non verifica la raggiungibilità dalla rete esterna."
                : "Snapshot legacy v1: policy locale e raggiungibilità esterna non sono disponibili."}
            </p>
            {snapshot.listeners.truncated && <p className="host-note">Elenco listener troncato: potrebbero mancare altre porte.</p>}
          </HostCard>

          <HostCard title="Container problematici" component={snapshot.docker}>
            {!snapshot.docker.available && <p className="host-empty">Stato Docker non disponibile.</p>}
            {snapshot.docker.available && snapshot.docker.problematic.length === 0 && snapshot.docker.unmapped_problematic_count === 0 && (
              <p className="host-empty">Nessun container problematico.</p>
            )}
            {snapshot.docker.problematic.length > 0 && (
              <div className="host-item-grid">
                {snapshot.docker.problematic.map((container) => (
                  <article key={container.label} className={`host-item status-${container.status}`}>
                    <header><strong>{container.label}</strong><HostStatusBadge status={container.status} /></header>
                    <small>{HOST_REASON_LABEL[container.reason] ?? container.reason.replaceAll("_", " ")}</small>
                  </article>
                ))}
              </div>
            )}
            {snapshot.docker.unmapped_problematic_count > 0 && (
              <p className="host-note">Altri container problematici senza label: {snapshot.docker.unmapped_problematic_count}</p>
            )}
          </HostCard>
        </div>
      )}
    </main>
  );
}

function SessionList({
  onOpen,
  identity,
}: {
  onOpen: (session: Session) => void;
  identity: Identity;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [profile, setProfile] = useState<"shell" | "codex" | "claude" | "antigravity">("shell");
  const [presets, setPresets] = useState<[string, string][]>([]);
  const [customDirectory, setCustomDirectory] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showSnapshots, setShowSnapshots] = useState(false);
  const [showArchives, setShowArchives] = useState(false);
  const [showAudit, setShowAudit] = useState(false);
  const [showBackups, setShowBackups] = useState(false);
  const [showUsers, setShowUsers] = useState(false);
  const [showPreferences, setShowPreferences] = useState(false);
  const [showDashboardActions, setShowDashboardActions] = useState(false);
  const [showHiddenSessions, setShowHiddenSessions] = useState(false);
  const [showHost, setShowHost] = useState(false);
  const [restoreHostFocus, setRestoreHostFocus] = useState(false);
  const [hostObservabilityEnabled, setHostObservabilityEnabled] = useState(false);
  const hostTriggerRef = useRef<HTMLButtonElement>(null);
  const [showBudget, setShowBudget] = useState(false);
  const [restoreBudgetFocus, setRestoreBudgetFocus] = useState(false);
  const [rateLimitFreshEnabled, setRateLimitFreshEnabled] = useState(false);
  const [sessionUsageEnabled, setSessionUsageEnabled] = useState(false);
  const [sessionTimelineEnabled, setSessionTimelineEnabled] = useState(false);
  const budgetTriggerRef = useRef<HTMLButtonElement>(null);
  const [dashboardDensity, setDashboardDensity] = useState<DashboardDensity>(readDashboardDensity);
  const [openActionsId, setOpenActionsId] = useState<string | null>(null);
  const [providerLimits, setProviderLimits] = useState<ProviderRateLimits | null>(null);
  const [orchestratorState, setOrchestratorState] = useState<OrchestratorState | null>(null);
  const [agentStatusBySession, setAgentStatusBySession] = useState<Record<string, AgentStatus>>({});
  const [notifyEnabled, setNotifyEnabled] = useState(false);
  const [notifyError, setNotifyError] = useState("");
  const notifySupported = typeof Notification !== "undefined" && "serviceWorker" in navigator;
  const [searchQuery, setSearchQuery] = useState("");

  const compactDashboard = dashboardDensity === "compact";

  const dashboardSessions = useMemo(() => sessions.filter((session) => !session.hidden), [sessions]);
  const hiddenSessions = useMemo(() => sessions.filter((session) => session.hidden), [sessions]);

  const filteredSessions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return dashboardSessions;
    return dashboardSessions.filter((session) => {
      const status = agentStatusBySession[session.id];
      const stateLabel = status
        ? AGENT_STATE_LEGEND.find(([state]) => state === status.state)?.[1]
        : undefined;
      const haystack = [
        session.name,
        session.current_command,
        status?.provider,
        stateLabel,
        status?.summary,
      ]
        .filter((value): value is string => Boolean(value))
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [dashboardSessions, searchQuery, agentStatusBySession]);
  const visibleSessions = compactDashboard ? dashboardSessions : filteredSessions;

  function chooseDashboardDensity(density: DashboardDensity) {
    window.localStorage.setItem(DASHBOARD_DENSITY_KEY, density);
    setDashboardDensity(density);
    if (density === "compact") setSearchQuery("");
  }

  useEffect(() => {
    if (!notifySupported) return;
    navigator.serviceWorker.ready
      .then((registration) => registration.pushManager.getSubscription())
      .then((subscription) => setNotifyEnabled(subscription !== null))
      .catch(() => { /* stato push non disponibile, resta disattivato */ });
  }, [notifySupported]);

  useEffect(() => {
    listSessions().then(setSessions).catch((value) => {
      // Il 401 è già gestito globalmente (setUnauthorizedHandler in App).
      if (!(value instanceof ApiError && value.status === 401)) setError(errorMessage(value));
    });
    fetchConfig()
      .then((config) => {
        const entries = Object.entries(config.workspace_presets);
        setPresets(entries);
        setDirectory((value) => value || entries[0]?.[1] || config.allowed_roots[0] || "");
        setHostObservabilityEnabled(
          identity.role === "admin" && config.host_observability_enabled,
        );
        setRateLimitFreshEnabled(
          identity.role === "admin" && config.rate_limit_fresh_enabled,
        );
        setSessionUsageEnabled(config.session_usage_enabled);
        // Come host-observability: già filtrato per ruolo lato backend
        // (nullo/false per i non-admin), ma il controllo del ruolo qui
        // resta la stessa difesa in profondità già in uso per gli altri
        // flag admin-only.
        setSessionTimelineEnabled(
          identity.role === "admin" && config.session_timeline_enabled,
        );
      })
      .catch(() => { /* il campo resta vuoto, l'utente può digitare */ });
  }, [identity.role]);

  useEffect(() => {
    if (showHost) return;
    if (showBudget) return;
    let active = true;
    const refresh = () => {
      listAgentStatuses()
        .then((statuses) => {
          if (!active) return;
          setAgentStatusBySession(
            Object.fromEntries(statuses.map((status) => [status.session_id, status])),
          );
        })
        .catch(() => { /* lo stato euristico non blocca la dashboard */ });
    };
    refresh();
    const interval = window.setInterval(refresh, 3_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [showHost, showBudget]);

  useEffect(() => {
    if (showHost || !restoreHostFocus) return;
    const frame = window.requestAnimationFrame(() => {
      hostTriggerRef.current?.focus({ preventScroll: true });
      setRestoreHostFocus(false);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [restoreHostFocus, showHost]);

  useEffect(() => {
    if (showBudget || !restoreBudgetFocus) return;
    const frame = window.requestAnimationFrame(() => {
      budgetTriggerRef.current?.focus({ preventScroll: true });
      setRestoreBudgetFocus(false);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [restoreBudgetFocus, showBudget]);

  useEffect(() => {
    if (showHost) return;
    if (showBudget) return;
    let active = true;
    const refresh = () => {
      fetchOrchestratorState()
        .then((value) => { if (active) setOrchestratorState(value); })
        .catch(() => { /* il collector dell'orchestratore è opzionale */ });
    };
    refresh();
    const interval = window.setInterval(refresh, 30_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [showHost, showBudget]);

  useEffect(() => {
    if (showHost) return;
    if (showBudget) return;
    let active = true;
    const refresh = () => {
      fetchProviderRateLimits()
        .then((value) => {
          if (active) setProviderLimits(value);
        })
        .catch(() => { /* le sessioni restano utilizzabili se il collector manca */ });
    };
    refresh();
    const interval = window.setInterval(refresh, 60_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [showHost, showBudget]);

  useEffect(() => {
    if (!showHelp) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowHelp(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showHelp]);

  async function refreshSessions() {
    setSessions(await listSessions());
  }

  async function renameListedSession(session: Session) {
    const promptedName = window.prompt("Nuovo nome della sessione", session.name);
    if (promptedName === null) return;
    const nextName = promptedName.trim().normalize("NFC");
    if (!nextName || nextName === session.name) return;
    if (nextName.length > 64 || !SESSION_NAME_PATTERN.test(nextName)) {
      setError(SESSION_NAME_HINT);
      return;
    }
    setError("");
    try {
      await renameSession(session.id, nextName);
      setSessions((items) => items.map((item) => (
        item.id === session.id ? { ...item, name: nextName } : item
      )));
      setOpenActionsId(null);
    } catch (value) {
      setError(errorMessage(value));
    }
  }

  async function terminateListedSession(session: Session) {
    const confirmed = window.confirm(
      `Terminare definitivamente la sessione “${session.name}”?`,
    );
    if (!confirmed) return;
    setError("");
    try {
      await terminateSession(session.id);
      setSessions((items) => items.filter((item) => item.id !== session.id));
      setOpenActionsId(null);
    } catch (value) {
      setError(errorMessage(value));
    }
  }

  async function archiveListedSession(session: Session) {
    const confirmed = window.confirm(
      `Archiviare “${session.name}”? I metadati saranno conservati e la sessione tmux verrà terminata.`,
    );
    if (!confirmed) return;
    setError("");
    try {
      await archiveSession(session.id);
      setSessions((items) => items.filter((item) => item.id !== session.id));
      setOpenActionsId(null);
    } catch (value) {
      setError(errorMessage(value));
    }
  }

  async function hideListedSession(session: Session) {
    setError("");
    try {
      await setSessionVisibility(session.id, true);
      setSessions((items) => items.map((item) => (
        item.id === session.id ? { ...item, hidden: true } : item
      )));
      setOpenActionsId(null);
    } catch (value) {
      setError(errorMessage(value));
    }
  }

  async function restoreHiddenSession(session: Session) {
    await setSessionVisibility(session.id, false);
    setSessions((items) => items.map((item) => (
      item.id === session.id ? { ...item, hidden: false } : item
    )));
  }

  async function toggleNotifications() {
    setNotifyError("");
    try {
      const registration = await navigator.serviceWorker.ready;
      if (notifyEnabled) {
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
          await unsubscribePush(subscription.endpoint);
          await subscription.unsubscribe();
        }
        setNotifyEnabled(false);
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return;
      const publicKey = await fetchPushPublicKey();
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
      await subscribePush(subscription.toJSON() as PushSubscriptionJSON);
      setNotifyEnabled(true);
    } catch (value) {
      setNotifyError(errorMessage(value));
    }
  }

  if (showHost && identity.role === "admin" && hostObservabilityEnabled) {
    return <HostView onBack={() => {
      setRestoreHostFocus(true);
      setShowHost(false);
    }} />;
  }

  if (showBudget) {
    return (
      <BudgetView
        onBack={() => {
          setRestoreBudgetFocus(true);
          setShowBudget(false);
        }}
        sessions={sessions}
        onOpenSession={onOpen}
        rateLimitFreshEnabled={rateLimitFreshEnabled}
        sessionUsageEnabled={sessionUsageEnabled}
        sessionTimelineEnabled={sessionTimelineEnabled}
      />
    );
  }

  return (
    <main className={`shell ${compactDashboard ? "compact-dashboard" : ""}`}>
      <header className="topbar">
        <div><span className="eyebrow">TMUX / PRIVATE NETWORK</span><h1>Sessions</h1></div>
        <div className="topbar-actions">
          <button className="help-button" onClick={() => setShowHelp(true)} aria-label="Apri guida">
            ?
          </button>
          <span className="count">
            {searchQuery.trim() ? `${filteredSessions.length}/${sessions.length}` : sessions.length}
          </span>
        </div>
      </header>
      <div className="dashboard-actions">
        {identity.role !== "viewer" && (
          <button
            className="new-session"
            onClick={() => setCreating((value) => !value)}
            aria-label={compactDashboard ? "Nuova sessione" : undefined}
            title={compactDashboard ? "Nuova sessione" : undefined}
          >
            {compactDashboard ? "＋" : "+ Nuova sessione"}
          </button>
        )}
        {notifySupported && (
          <button
            className="snapshot-button"
            onClick={() => void toggleNotifications()}
            disabled={!notifyEnabled && Notification.permission === "denied"}
            title={
              Notification.permission === "denied"
                ? "Notifiche bloccate dal browser per questo sito"
                : "Avvisa quando una sessione attende feedback o autorizzazione, anche ad app chiusa"
            }
          >
            {compactDashboard ? (notifyEnabled ? "🔔" : "🔕") : (notifyEnabled ? "Notifiche: on" : "Notifiche: off")}
          </button>
        )}
        <button
          className="snapshot-button dashboard-more-actions"
          aria-expanded={showDashboardActions}
          aria-controls="dashboard-secondary-actions"
          aria-label={compactDashboard ? (showDashboardActions ? "Nascondi altre azioni" : "Mostra altre azioni") : undefined}
          title={compactDashboard ? (showDashboardActions ? "Meno azioni" : "Altre azioni") : undefined}
          onClick={() => setShowDashboardActions((value) => !value)}
        >
          {compactDashboard ? "⋯" : (showDashboardActions ? "Meno azioni" : "Altre azioni")}
        </button>
      </div>
      {showDashboardActions && (
        <div className="dashboard-secondary-actions" id="dashboard-secondary-actions" role="group" aria-label="Altre azioni">
          <button className="snapshot-button" onClick={() => setShowPreferences(true)} aria-label="Preferenze" title="Preferenze">{compactDashboard ? "⚙" : "Preferenze"}</button>
          {identity.role !== "viewer" && (
            <button className="snapshot-button" onClick={() => setShowSnapshots(true)} aria-label="Snapshot" title="Snapshot">{compactDashboard ? "◫" : "Snapshot"}</button>
          )}
          {identity.role !== "viewer" && (
            <button className="snapshot-button" onClick={() => setShowArchives(true)} aria-label="Archivio" title="Archivio">{compactDashboard ? "▣" : "Archivio"}</button>
          )}
          <button className="snapshot-button" onClick={() => setShowHiddenSessions(true)} aria-label="Sessioni nascoste" title="Sessioni nascoste">{compactDashboard ? "◌" : "Sessioni nascoste"}</button>
          <button ref={budgetTriggerRef} className="snapshot-button" onClick={() => setShowBudget(true)} aria-label="Budget" title="Budget">{compactDashboard ? "◔" : "Budget"}</button>
          {identity.role === "admin" && (
            <button className="snapshot-button" onClick={() => setShowUsers(true)} aria-label="Utenti" title="Utenti">{compactDashboard ? "♟" : "Utenti"}</button>
          )}
          {identity.role === "admin" && (
            <button className="snapshot-button" onClick={() => setShowAudit(true)} aria-label="Audit" title="Audit">{compactDashboard ? "≡" : "Audit"}</button>
          )}
          {identity.role === "admin" && (
            <button className="snapshot-button" onClick={() => setShowBackups(true)} aria-label="Backup" title="Backup">{compactDashboard ? "⇩" : "Backup"}</button>
          )}
          {identity.role === "admin" && hostObservabilityEnabled && (
            <button ref={hostTriggerRef} className="snapshot-button" onClick={() => setShowHost(true)} aria-label="Osservabilità host" title="Osservabilità host">{compactDashboard ? "▥" : "Host"}</button>
          )}
        </div>
      )}
      {creating && <form className="create-form" onSubmit={async (event) => {
        event.preventDefault();
        const normalizedName = name.trim().normalize("NFC");
        if (!SESSION_NAME_PATTERN.test(normalizedName)) {
          setError(SESSION_NAME_HINT);
          return;
        }
        try {
          await createSession(normalizedName, directory, profile);
          const updatedSessions = await listSessions();
          setCreating(false); setName(""); setProfile("shell"); setError("");
          setSessions(updatedSessions);
          const createdSession = updatedSessions.find((session) => session.name === normalizedName);
          if (createdSession) onOpen(createdSession);
        } catch (value) {
          setError(errorMessage(value));
        }
      }}>
        <input
          required
          pattern="[\\p{L}\\p{N}_-]+( [\\p{L}\\p{N}_-]+)*"
          maxLength={64}
          title={SESSION_NAME_HINT}
          placeholder="Nome sessione"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {presets.length > 0 && !customDirectory ? (
          <select value={directory} onChange={(event) => {
            if (event.target.value === "__custom__") setCustomDirectory(true);
            else setDirectory(event.target.value);
          }}>
            {presets.map(([label, path]) => <option key={label} value={path}>{label} — {path}</option>)}
            <option value="__custom__">Directory personalizzata…</option>
          </select>
        ) : (
          <input required placeholder="Directory consentita" value={directory} onChange={(event) => setDirectory(event.target.value)} />
        )}
        <select
          aria-label="Profilo sessione"
          value={profile}
          onChange={(event) => setProfile(event.target.value as "shell" | "codex" | "claude" | "antigravity")}
        >
          <option value="shell">Shell</option>
          <option value="codex">Codex</option>
          <option value="claude">Claude</option>
          <option value="antigravity">Antigravity (agy)</option>
        </select>
        <button type="submit">Crea sessione</button>
      </form>}
      {(providerLimits || orchestratorState) && (
        <div className={`dashboard-service-summary ${compactDashboard ? "compact" : ""}`}>
      {providerLimits && (
        <section className={`provider-limits ${compactDashboard ? "compact" : ""}`} aria-label="Quote provider">
          {providerLimits.providers.map((provider) => (
            <article key={provider.provider}>
              <header>
                <strong>{provider.provider}</strong>
                {!compactDashboard && <small>{provider.observed_at ? formatDate(provider.observed_at) : "non disponibile"}</small>}
              </header>
              {provider.available ? (
                <div className={`provider-windows ${compactDashboard ? "compact" : ""}`}>
                  {provider.windows.slice(0, compactDashboard ? 2 : undefined).map((window) => (
                    <span key={window.label} title={rateLimitWindowDescription(window) ?? undefined}>
                      {!compactDashboard && <small>{window.label}</small>}
                      <strong style={{ color: rateLimitColor(window.used_percent) }}>
                        {window.used_percent === null ? "n/d" : `${Math.round(window.used_percent)}%`}
                      </strong>
                      {!compactDashboard && window.detail && <em>{window.detail}</em>}
                      {formatRateLimitReset(window.resets_at) && (
                        <em className="provider-reset">reset {formatRateLimitReset(window.resets_at)}</em>
                      )}
                    </span>
                  ))}
                </div>
              ) : (
                <small className="provider-unavailable">{provider.error ?? "Dati non disponibili"}</small>
              )}
            </article>
          ))}
        </section>
      )}
      {orchestratorState && (
        <section className={`orchestrator-state ${compactDashboard ? "compact" : ""}`} aria-label="Task orchestratore">
          <header>
            <strong>{compactDashboard ? "Task" : "Task schedulati"}</strong>
            <small>{compactDashboard ? orchestratorState.tasks.length : `${orchestratorState.tasks.length} attivi · aggiornato ${formatDate(orchestratorState.collected_at)}`}</small>
          </header>
          {!compactDashboard && (orchestratorState.tasks.length === 0 ? (
            <small>Nessun task schedulato attivo.</small>
          ) : (
            <div className="orchestrator-tasks">
              {orchestratorState.tasks.map((task) => (
                <article key={task.task_id}>
                  <strong>{task.task_kind}</strong>
                  <small>{task.provider} · {task.status.replace("_", " ")}</small>
                  {task.phase && <small>Fase {task.phase.index + 1}/{task.phase.total}: {task.phase.name}</small>}
                  {task.capacity_paused && <em>In pausa per capacità{task.next_attempt_at ? ` · riprova ${formatDate(task.next_attempt_at)}` : ""}</em>}
                  {!task.capacity_paused && task.fallback_providers.length > 0 && <small>Fallback: {task.fallback_providers.join(" → ")}</small>}
                </article>
              ))}
            </div>
          ))}
        </section>
      )}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {notifyError && <p className="error">{notifyError}</p>}
      {!compactDashboard && dashboardSessions.length > 0 && (
        <input
          type="search"
          className="session-search"
          placeholder="Cerca per nome, comando o stato…"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          aria-label="Cerca sessioni"
        />
      )}
      <section className="session-list">
        {visibleSessions.map((session) => (
          <article className="session-item" key={session.id}>
            <div className="session-row">
              <button className="session-card" onClick={() => onOpen(session)}>
                <span className="session-icon">&gt;_</span>
                <span className="session-copy">
                  <strong>
                    {session.name}
                    {agentStatusBySession[session.id] && (
                      <>
                        <span
                          className={`agent-state ${agentStatusBySession[session.id].state}`}
                          aria-label={`${agentStatusBySession[session.id].provider}: ${agentStatusBySession[session.id].detail}`}
                          title={`${agentStatusBySession[session.id].provider}: ${agentStatusBySession[session.id].detail}`}
                        >
                          {AGENT_STATE_ICON[agentStatusBySession[session.id].state]}
                        </span>
                        <span
                          className={`permission-state ${agentStatusBySession[session.id].permission_state}`}
                          aria-label={`Permessi: ${agentStatusBySession[session.id].permission_detail}`}
                          title={`Permessi: ${agentStatusBySession[session.id].permission_detail}`}
                        >
                          {PERMISSION_STATE_ICON[agentStatusBySession[session.id].permission_state]}
                        </span>
                      </>
                    )}
                  </strong>
                  <small>
                    {session.current_command}
                    {agentStatusBySession[session.id]?.context_used_percent != null && (
                      <span
                        className="context-usage"
                        style={{
                          color: rateLimitColor(
                            agentStatusBySession[session.id].context_used_percent!,
                          ),
                        }}
                        title="Finestra di contesto utilizzata"
                      >
                        ctx {Math.round(agentStatusBySession[session.id].context_used_percent!)}%
                      </span>
                    )}
                    {" · "}{session.windows} window
                  </small>
                  {agentStatusBySession[session.id]?.summary && (
                    <small className="session-summary">
                      {agentStatusBySession[session.id].summary}
                    </small>
                  )}
                </span>
                <span className="chevron">›</span>
              </button>
              {identity.role !== "viewer" && <button
                type="button"
                className="session-menu"
                aria-label={`Azioni per ${session.name}`}
                aria-expanded={openActionsId === session.id}
                onClick={() => setOpenActionsId((value) => value === session.id ? null : session.id)}
              >
                ⋮
              </button>}
            </div>
            {openActionsId === session.id && (
              <div className="session-toolbar" role="toolbar" aria-label={`Azioni per ${session.name}`}>
                <button type="button" onClick={() => void renameListedSession(session)}>
                  Rinomina
                </button>
                <button type="button" onClick={() => void archiveListedSession(session)}>
                  Archivia
                </button>
                <button type="button" onClick={() => void hideListedSession(session)}>
                  Nascondi
                </button>
                <button type="button" className="danger" onClick={() => void terminateListedSession(session)}>
                  Termina
                </button>
              </div>
            )}
          </article>
        ))}
        {!error && dashboardSessions.length === 0 && <p className="empty">Nessuna sessione visibile sulla dashboard.</p>}
        {!error && !compactDashboard && dashboardSessions.length > 0 && filteredSessions.length === 0 && (
          <p className="empty">Nessuna sessione corrisponde alla ricerca.</p>
        )}
      </section>
      <footer className="agent-legend" aria-label="Legenda stati agentici">
        <section>
          <strong>Stato agente</strong>
          <div>
            {AGENT_STATE_LEGEND.map(([state, label]) => (
              <span key={state}>
                <i className={`agent-state ${state}`} aria-hidden="true">
                  {AGENT_STATE_ICON[state]}
                </i>
                {label}
              </span>
            ))}
          </div>
        </section>
        <section>
          <strong>Permessi</strong>
          <div>
            {PERMISSION_STATE_LEGEND.map(([state, label]) => (
              <span key={state}>
                <i className={`permission-state ${state}`} aria-hidden="true">
                  {PERMISSION_STATE_ICON[state]}
                </i>
                {label}
              </span>
            ))}
          </div>
        </section>
      </footer>
      {showHelp && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowHelp(false);
          }}
        >
          <section className="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-title">
            <header>
              <div>
                <span className="eyebrow">GUIDA RAPIDA</span>
                <h2 id="help-title">Mobile Agent Console</h2>
              </div>
              <button className="modal-close" onClick={() => setShowHelp(false)} aria-label="Chiudi">
                ×
              </button>
            </header>
            <ol>
              <li><strong>Crea o apri una sessione.</strong> Le sessioni continuano a vivere in tmux.</li>
              <li><strong>Invia il prompt.</strong> Il testo e il tasto Enter restano azioni separate.</li>
              <li><strong>Allega file.</strong> Immagini e documenti vengono referenziati tramite path.</li>
              <li><strong>Controlla l’agente.</strong> Up, Down ed Esc sono disponibili nelle funzioni speciali.</li>
              <li><strong>Consulta la directory.</strong> "Contenuto directory" elenca file e cartelle della sessione con copy rapido per nome.</li>
              <li><strong>Interrompi con cautela.</strong> Ctrl-C ferma il processo; Termina chiude tutta la sessione.</li>
            </ol>
            <aside className="whats-new">
              <span className="eyebrow">WHAT’S NEW</span>
              <h3>{LATEST_RELEASE.title}</h3>
              <p>{LATEST_RELEASE.description}</p>
            </aside>
          </section>
        </div>
      )}
      {showSnapshots && (
        <SnapshotModal
          sessions={sessions}
          onClose={() => setShowSnapshots(false)}
          onRestored={refreshSessions}
        />
      )}
      {showUsers && <UserModal onClose={() => setShowUsers(false)} />}
      {showAudit && <AuditModal onClose={() => setShowAudit(false)} />}
      {showBackups && <BackupModal onClose={() => setShowBackups(false)} />}
      {showHiddenSessions && (
        <HiddenSessionsModal
          sessions={hiddenSessions}
          canManage={identity.role !== "viewer"}
          onClose={() => setShowHiddenSessions(false)}
          onOpen={onOpen}
          onRestore={restoreHiddenSession}
        />
      )}
      {showPreferences && (
        <PreferencesModal
          onClose={() => setShowPreferences(false)}
          dashboardDensity={dashboardDensity}
          onDashboardDensityChange={chooseDashboardDensity}
        />
      )}
      {showArchives && (
        <ArchiveModal
          onClose={() => setShowArchives(false)}
          onRestored={refreshSessions}
        />
      )}
    </main>
  );
}

function Console({
  session,
  onBack,
  onSwitch,
  recentSessions,
  identity,
  draft,
  onDraftChange,
}: {
  session: Session;
  onBack: () => void;
  onSwitch: (session: Session) => void;
  recentSessions: Session[];
  identity: Identity;
  draft: string;
  onDraftChange: (draft: string) => void;
}) {
  const [content, setContent] = useState("");
  const contentRef = useRef(content);
  useEffect(() => { contentRef.current = content; }, [content]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingAttachmentId, setDeletingAttachmentId] = useState("");
  const [followingOutput, setFollowingOutput] = useState(true);
  const [showSpecialKeys, setShowSpecialKeys] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [sendingArtifactPrompt, setSendingArtifactPrompt] = useState(false);
  const [showDirectory, setShowDirectory] = useState(false);
  const [showArtifacts, setShowArtifacts] = useState(false);
  const [fullscreenOutput, setFullscreenOutput] = useState(false);
  const [controlError, setControlError] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachmentError, setAttachmentError] = useState("");
  const [panes, setPanes] = useState<Pane[]>([]);
  const [paneId, setPaneId] = useState("");
  const [splittingPane, setSplittingPane] = useState(false);
  const [closingPane, setClosingPane] = useState(false);
  const agentic = /codex|claude|agy|antigravity/i.test(session.current_command);
  const claude = /claude/i.test(session.current_command);
  const [historyEnabled, setHistoryEnabled] = useState(false);
  const [history, setHistory] = useState<ClaudeHistory | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [copiedAgentBlock, setCopiedAgentBlock] = useState("");
  const [outputMode, setOutputMode] = useState<"terminal" | "blocks" | "history">(
    agentic ? readDefaultAgentView() : "terminal",
  );
  const outputRef = useRef<HTMLPreElement | HTMLDivElement>(null);
  const outputLinesRef = useRef<string[]>([]);
  const outputSequenceRef = useRef(0);
  const [contentRevision, setContentRevision] = useState(0);
  const [terminalLoading, setTerminalLoading] = useState(false);
  const [terminalLines, setTerminalLines] = useState(500);
  const [loadingMoreHistory, setLoadingMoreHistory] = useState(false);
  const [historyExhausted, setHistoryExhausted] = useState(false);
  const pendingHistoryRestoreRef = useRef<number | null>(null);
  const terminalLinesRef = useRef(terminalLines);
  const loadingMoreHistoryRef = useRef(loadingMoreHistory);
  const historyExhaustedRef = useRef(historyExhausted);
  useEffect(() => { terminalLinesRef.current = terminalLines; }, [terminalLines]);
  useEffect(() => { loadingMoreHistoryRef.current = loadingMoreHistory; }, [loadingMoreHistory]);
  useEffect(() => { historyExhaustedRef.current = historyExhausted; }, [historyExhausted]);
  useEffect(() => {
    if (!fullscreenOutput) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreenOutput(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [fullscreenOutput]);

  async function copyAgentBlock(blockKey: string, text: string) {
    if (!await copyToClipboard(cleanShareableOutput(text))) return;
    setCopiedAgentBlock(blockKey);
    window.setTimeout(() => setCopiedAgentBlock((value) => value === blockKey ? "" : value), 2_000);
  }
  const fileInputRef = useRef<HTMLInputElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const terminalContainerRef = useRef<HTMLDivElement | null>(null);
  const previousFitRef = useRef("");
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [switcherSessions, setSwitcherSessions] = useState<Session[]>([]);
  const [agentStatusBySession, setAgentStatusBySession] = useState<Record<string, AgentStatus>>({});
  const [providerLimits, setProviderLimits] = useState<ProviderRateLimits | null>(null);
  const ownStatus = agentStatusBySession[session.id];

  // Stato/permessi per il menu di cambio rapido e per il badge contesto
  // qui sotto condividono lo stesso poll: la sessione agentica lo vuole
  // sempre attivo, il menu solo mentre è aperto.
  useEffect(() => {
    if (!agentic && !showSwitcher) return;
    let active = true;
    const refresh = () => {
      listAgentStatuses()
        .then((statuses) => {
          if (!active) return;
          setAgentStatusBySession(Object.fromEntries(statuses.map((status) => [status.session_id, status])));
        })
        .catch(() => { /* lo stato euristico non blocca la console */ });
    };
    refresh();
    const interval = window.setInterval(refresh, 3_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [agentic, showSwitcher]);

  useEffect(() => {
    if (!showSwitcher) return;
    let active = true;
    const refresh = () => {
      listSessions()
        .then((items) => { if (active) setSwitcherSessions(items); })
        .catch(() => { /* il menu resta con l'ultimo elenco noto */ });
    };
    refresh();
    const interval = window.setInterval(refresh, 5_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [showSwitcher]);

  useEffect(() => {
    if (!agentic) return;
    let active = true;
    const refresh = () => {
      fetchProviderRateLimits()
        .then((value) => { if (active) setProviderLimits(value); })
        .catch(() => { /* la console resta utilizzabile senza le quote provider */ });
    };
    refresh();
    const interval = window.setInterval(refresh, 60_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [agentic]);

  const inferredProvider = /codex/i.test(session.current_command) ? "codex"
    : /claude/i.test(session.current_command) ? "claude"
    : /agy|antigravity/i.test(session.current_command) ? "antigravity"
    : null;
  const ownProviderLimit = providerLimits?.providers.find(
    (provider) => provider.provider === (ownStatus?.provider ?? inferredProvider),
  );

  useEffect(() => {
    let cancelled = false;
    if (!claude) return;
    fetchConfig()
      .then((config) => {
        if (!cancelled) setHistoryEnabled(config.claude_history_enabled);
      })
      .catch(() => {
        if (!cancelled) setHistoryEnabled(false);
      });
    return () => { cancelled = true; };
  }, [claude]);

  useEffect(() => {
    if (outputMode !== "history" || !historyEnabled) return;
    let cancelled = false;
    let timer: number | undefined;
    const refresh = () => {
      fetchClaudeHistory(session.id)
        .then((result) => {
          if (cancelled) return;
          setHistory(result);
          setHistoryError("");
        })
        .catch((value) => {
          if (cancelled) return;
          if (value instanceof ApiError && value.status === 404) {
            setHistoryEnabled(false);
            setOutputMode("blocks");
            setControlError("Cronologia Claude non disponibile: ripristinata la vista live.");
            return;
          }
          setHistoryError(errorMessage(value));
        })
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(refresh, 5000);
        });
    };
    refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [historyEnabled, outputMode, session.id]);

  useEffect(() => {
    let cancelled = false;
    listPanes(session.id)
      .then((items) => {
        if (cancelled) return;
        setPanes(items);
        setPaneId((current) => (
          items.some((pane) => pane.id === current)
            ? current
            : (items.find((pane) => pane.active) ?? items[0])?.id ?? ""
        ));
      })
      .catch((value) => { if (!cancelled) setControlError(errorMessage(value)); });
    return () => { cancelled = true; };
  }, [session.id]);

  useEffect(() => {
    setTerminalLines(500);
    setLoadingMoreHistory(false);
    setHistoryExhausted(false);
    pendingHistoryRestoreRef.current = null;
  }, [session.id, paneId]);

  useEffect(() => {
    if (!paneId) return;
    let socket: WebSocket | undefined;
    let timer: number | undefined;
    let stopped = false;
    let attempts = 0;
    const connect = () => {
      if (stopped) return;
      setConnection("connecting");
      socket = new WebSocket(
        streamUrl(session.id, paneId, outputMode === "terminal", outputMode === "terminal" ? terminalLines : undefined),
      );
      socket.onopen = () => { attempts = 0; setConnection("online"); };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "snapshot") {
          outputLinesRef.current = message.content.match(/[^\n]*\n|[^\n]+$/g) ?? [];
          outputSequenceRef.current = message.sequence_id;
          setContent(message.content);
          // setContent con una stringa identica alla precedente (es. il
          // pane ha meno righe di quelle richieste) non ri-renderizza:
          // questo contatore forza comunque l'effetto di scrittura del
          // terminale a rieseguire, altrimenti un load-more in corso
          // resterebbe bloccato per sempre in attesa di un content diverso.
          setContentRevision((value) => value + 1);
        }
        if (message.type === "delta") {
          if (message.base_sequence_id !== outputSequenceRef.current) {
            socket?.close();
            return;
          }
          outputLinesRef.current.splice(message.start, message.delete_count, ...message.lines);
          outputSequenceRef.current = message.sequence_id;
          setContent(outputLinesRef.current.join(""));
        }
        if (message.type === "session_closed") {
          stopped = true;
          if (timer) clearTimeout(timer);
          setConnection("closed");
          socket?.close();
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        setConnection("offline");
        attempts += 1;
        const delay = Math.min(15000, 750 * 2 ** attempts) + Math.random() * 500;
        timer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [session.id, paneId, outputMode === "terminal", terminalLines]);

  useEffect(() => {
    if (outputMode !== "blocks") return;
    const output = outputRef.current;
    if (!output || !paneId || typeof ResizeObserver === "undefined") return;
    let timer: number | undefined;
    const pane = panes.find((item) => item.id === paneId);
    let previous = pane ? `${pane.width}x${pane.height}` : "";
    const observer = new ResizeObserver(([entry]) => {
      const columns = Math.max(MIN_PANE_COLUMNS, Math.min(500, Math.floor(entry.contentRect.width / 8)));
      const rows = Math.max(5, Math.min(300, Math.floor(entry.contentRect.height / 20)));
      const dimensions = `${columns}x${rows}`;
      if (dimensions === previous) return;
      previous = dimensions;
      if (timer) clearTimeout(timer);
      timer = window.setTimeout(() => {
        resizePane(session.id, paneId, columns, rows).catch((value) => {
          setControlError(errorMessage(value));
        });
      }, 750);
    });
    observer.observe(output);
    return () => {
      observer.disconnect();
      if (timer) clearTimeout(timer);
    };
  }, [session.id, paneId, panes, outputMode]);

  // Vista Terminale: xterm.js in sola visualizzazione (disableStdin — l'input
  // resta il compose-poi-invia esistente). Ogni snapshot è autorevole (vedi
  // docs/architecture.md, sezione Streaming): si ridisegna da zero invece di
  // tentare un aggiornamento incrementale del buffer.
  useEffect(() => {
    if (outputMode !== "terminal") return;
    const container = terminalContainerRef.current;
    if (!container) return;
    let cancelled = false;
    let disposeInner: (() => void) | undefined;
    // xterm.js + addon-fit/webgl pesano parecchio: caricati solo qui, non
    // nel bundle iniziale, così una sessione che resta su Blocchi/Cronologia
    // non li scarica mai. Al primo utilizzo il download richiede qualche
    // secondo: lo spinner evita che il riquadro sembri vuoto/rotto.
    setTerminalLoading(true);
    void (async () => {
      const [{ Terminal }, { FitAddon }, { WebglAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
        import("@xterm/addon-webgl"),
      ]);
      if (cancelled) return;
      setTerminalLoading(false);
      const terminal = new Terminal({
        disableStdin: true,
        convertEol: true,
        fontSize: 13,
        // Di default (0) xterm.js scrolla a scatti, riga per riga, invece di
        // animare — specie percepibile col drag touch su mobile.
        smoothScrollDuration: 120,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        theme: {
          background: "#101713",
          foreground: "#e9f2ec",
          cursor: "#9be5b3",
          selectionBackground: "#41664d88",
        },
      });
      const fitAddon = new FitAddon();
      terminal.loadAddon(fitAddon);
      terminal.open(container);
      terminalRef.current = terminal;
      fitAddonRef.current = fitAddon;
      // Uno snapshot può già essere arrivato (setContent) mentre il chunk
      // xterm.js era ancora in scaricamento: l'effetto di scrittura lo
      // avrebbe ignorato perché terminalRef.current era ancora nullo, e
      // senza nuovi contenuti (sessione ferma in attesa) non si sarebbe
      // mai riscritto. Scrivilo qui una volta, ora che il terminale esiste.
      if (contentRef.current) terminal.write(contentRef.current);
      // Il renderer DOM di default non tiene il passo col ridisegno durante
      // lo scroll touch su mobile (percepito come "a scatti"); il renderer
      // WebGL è accelerato via GPU. Se non disponibile (o perso a runtime),
      // si torna silenziosamente al renderer DOM di default.
      try {
        const webglAddon = new WebglAddon();
        webglAddon.onContextLoss(() => webglAddon.dispose());
        terminal.loadAddon(webglAddon);
      } catch {
        /* WebGL non disponibile: resta il renderer DOM di default */
      }

      let resizeTimer: number | undefined;
      const applyFit = () => {
        fitAddon.fit();
        if (!paneId) return;
        // ResizePaneInput impone 20-500 colonne e 5-300 righe (schemas.py);
        // durante un resize in corso FitAddon può calcolare valori transitori
        // fuori range prima che il layout si stabilizzi.
        const columns = Math.max(20, Math.min(500, terminal.cols));
        const rows = Math.max(5, Math.min(300, terminal.rows));
        const dimensions = `${columns}x${rows}`;
        if (dimensions === previousFitRef.current) return;
        previousFitRef.current = dimensions;
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => {
          resizePane(session.id, paneId, columns, rows).catch((value) => {
            setControlError(errorMessage(value));
          });
        }, 750);
      };
      applyFit();
      const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(applyFit);
      observer?.observe(container);

      const scrollDisposable = terminal.onScroll(() => {
        const buffer = terminal.buffer.active;
        setFollowingOutput(buffer.viewportY >= buffer.baseY);
        // In cima al buffer caricato: richiedi altre righe più vecchie
        // aumentando la profondità della cattura tmux e riconnettendo il
        // WebSocket (vedi useEffect su terminalLines). Uno snapshot più
        // grande resta l'unica fonte autorevole, niente merge manuale.
        if (
          buffer.viewportY === 0
          && !loadingMoreHistoryRef.current
          && !historyExhaustedRef.current
          && terminalLinesRef.current < MAX_TERMINAL_LINES
        ) {
          pendingHistoryRestoreRef.current = buffer.length;
          setLoadingMoreHistory(true);
          setTerminalLines((value) => Math.min(MAX_TERMINAL_LINES, value + LOAD_MORE_STEP_LINES));
        }
      });

      disposeInner = () => {
        observer?.disconnect();
        scrollDisposable.dispose();
        if (resizeTimer) clearTimeout(resizeTimer);
        terminal.dispose();
        terminalRef.current = null;
        fitAddonRef.current = null;
      };
    })();

    return () => {
      cancelled = true;
      setTerminalLoading(false);
      disposeInner?.();
    };
  }, [outputMode, session.id, paneId]);

  useEffect(() => {
    if (outputMode !== "terminal" || !terminalRef.current) return;
    const terminal = terminalRef.current;
    const pendingOldLength = pendingHistoryRestoreRef.current;
    terminal.reset();
    // write() è asincrono: il buffer è affidabile solo dentro la callback.
    terminal.write(content, () => {
      if (pendingOldLength === null) return;
      const delta = terminal.buffer.active.length - pendingOldLength;
      if (delta > 0) terminal.scrollToLine(delta);
      else setHistoryExhausted(true);
      pendingHistoryRestoreRef.current = null;
      setLoadingMoreHistory(false);
    });
  }, [content, contentRevision, outputMode]);

  useEffect(() => {
    if (outputMode === "terminal") return;
    if (followingOutput && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [content, history, followingOutput, outputMode]);

  function updateScrollMode() {
    const output = outputRef.current;
    if (!output) return;
    const distanceFromBottom = output.scrollHeight - output.scrollTop - output.clientHeight;
    setFollowingOutput(distanceFromBottom < 48);
  }

  function resumeFollowingOutput() {
    setFollowingOutput(true);
    if (terminalRef.current) terminalRef.current.scrollToBottom();
    else if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if ((!draft && attachments.length === 0) || sending || uploading) return;
    setSending(true);
    try {
      await sendText(
        session.id,
        draft,
        attachments.map((attachment) => attachment.id),
        paneId || undefined,
      );
      onDraftChange("");
      setAttachments([]);
      setControlError("");
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setSending(false);
    }
  }

  async function selectFiles(files: FileList | null) {
    if (!files?.length) return;
    const availableSlots = 5 - attachments.length;
    if (files.length > availableSlots) {
      setAttachmentError("Puoi allegare al massimo 5 file per prompt.");
      return;
    }
    setUploading(true);
    setAttachmentError("");
    try {
      for (const file of Array.from(files)) {
        const uploaded = await uploadAttachment(session.id, file);
        setAttachments((current) => [...current, uploaded]);
      }
    } catch (value) {
      setAttachmentError(errorMessage(value));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function removeAttachment(attachment: Attachment) {
    setDeletingAttachmentId(attachment.id);
    setAttachmentError("");
    try {
      await deleteAttachment(session.id, attachment.id);
      setAttachments((items) => items.filter((item) => item.id !== attachment.id));
    } catch (value) {
      setAttachmentError(errorMessage(value));
    } finally {
      setDeletingAttachmentId("");
    }
  }

  async function pressSpecialKey(key: "Up" | "Down" | "Escape" | "C-c" | "Shift-Tab") {
    const confirmed = key !== "C-c" || window.confirm(
      "Inviare Ctrl-C? Il processo attivo potrebbe essere interrotto.",
    );
    if (!confirmed) return;
    setControlError("");
    try {
      await sendKey(session.id, key, key === "C-c", paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    }
  }

  async function openCodexPermissions() {
    setControlError("");
    try {
      await sendText(session.id, "/permissions", [], paneId || undefined);
      await sendEnter(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    }
  }

  async function runCompact() {
    setCompacting(true);
    setControlError("");
    try {
      await sendText(session.id, "/compact", [], paneId || undefined);
      await sendEnter(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setCompacting(false);
    }
  }

  async function runClear() {
    setClearing(true);
    setControlError("");
    try {
      await sendText(session.id, "/clear", [], paneId || undefined);
      await sendEnter(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setClearing(false);
    }
  }

  async function sendArtifactInstructions() {
    setSendingArtifactPrompt(true);
    setControlError("");
    try {
      await sendArtifactPrompt(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setSendingArtifactPrompt(false);
    }
  }

  async function pressEnter() {
    setControlError("");
    try {
      await sendEnter(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    }
  }

  async function createPane(direction: "horizontal" | "vertical") {
    setSplittingPane(true);
    setControlError("");
    try {
      const created = await splitPane(session.id, paneId || undefined, direction);
      const items = await listPanes(session.id);
      setPanes(items);
      setPaneId(created.id);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setSplittingPane(false);
    }
  }

  async function closePane() {
    if (!paneId) return;
    if (!window.confirm("Chiudere questo pane? Il processo al suo interno verrà terminato.")) return;
    setClosingPane(true);
    setControlError("");
    try {
      await killPane(session.id, paneId);
      const items = await listPanes(session.id);
      setPanes(items);
      setPaneId(items[0]?.id ?? "");
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setClosingPane(false);
    }
  }

  return (
    <main className="console">
      <header className="console-header">
        <button className="icon-button" onClick={onBack} aria-label="Indietro">‹</button>
        <div className="session-header-copy">
          <strong>{session.name}</strong>
          <small>{session.current_command}</small>
          {recentSessions.length > 0 && (
            <nav className="recent-sessions" aria-label="Sessioni visitate di recente">
              {recentSessions.map((recent) => (
                <button key={recent.id} type="button" onClick={() => onSwitch(recent)} title={`Apri ${recent.name}`}>
                  ↶ {recent.name}
                </button>
              ))}
            </nav>
          )}
        </div>
        <button
          type="button"
          className="icon-button session-switcher-toggle"
          onClick={() => setShowSwitcher(true)}
          aria-label="Cambia sessione"
          aria-haspopup="true"
          aria-expanded={showSwitcher}
        >
          ☰
        </button>
        <span className={`status ${connection}`}>{CONNECTION_LABEL[connection]}</span>
      </header>
      {agentic && (ownStatus || ownProviderLimit) && (
        <section className="agent-info-bar" aria-label="Stato agente">
          {ownStatus && (
            <span className="agent-info-state" title={`${ownStatus.provider}: ${ownStatus.detail}`}>
              <i className={`agent-state ${ownStatus.state}`}>{AGENT_STATE_ICON[ownStatus.state]}</i>
              {ownStatus.detail}
            </span>
          )}
          {ownStatus?.context_used_percent != null && (
            <span
              className="context-usage"
              style={{ color: rateLimitColor(ownStatus.context_used_percent) }}
              title="Finestra di contesto utilizzata"
            >
              ctx {Math.round(ownStatus.context_used_percent)}%
            </span>
          )}
          {ownProviderLimit?.available && ownProviderLimit.windows.map((window) => (
            <span
              key={window.label}
              className="agent-info-limit"
              title={rateLimitWindowDescription(window) ?? undefined}
            >
              <small>{window.label}</small>{" "}
              <strong style={{ color: rateLimitColor(window.used_percent) }}>
                {window.used_percent === null ? "n/d" : `${Math.round(window.used_percent)}%`}
              </strong>
              {formatRateLimitReset(window.resets_at) && (
                <small className="agent-info-reset">reset {formatRateLimitReset(window.resets_at)}</small>
              )}
            </span>
          ))}
        </section>
      )}
      {showSwitcher && (
        <div
          className="modal-backdrop switcher-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowSwitcher(false);
          }}
        >
          <section className="session-switcher" role="dialog" aria-modal="true" aria-label="Cambia sessione">
            <header>
              <strong>Sessioni</strong>
              <button className="modal-close" onClick={() => setShowSwitcher(false)} aria-label="Chiudi">×</button>
            </header>
            <div className="session-switcher-list">
              {switcherSessions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`session-switcher-item ${item.id === session.id ? "current" : ""}`}
                  onClick={() => {
                    setShowSwitcher(false);
                    if (item.id !== session.id) onSwitch(item);
                  }}
                >
                  <span className="session-copy">
                    <strong>
                      {item.name}
                      {agentStatusBySession[item.id] && (
                        <span
                          className={`agent-state ${agentStatusBySession[item.id].state}`}
                          title={`${agentStatusBySession[item.id].provider}: ${agentStatusBySession[item.id].detail}`}
                        >
                          {AGENT_STATE_ICON[agentStatusBySession[item.id].state]}
                        </span>
                      )}
                    </strong>
                    <small>{item.current_command}</small>
                  </span>
                </button>
              ))}
              {switcherSessions.length === 0 && <p className="empty">Nessuna sessione.</p>}
            </div>
          </section>
        </div>
      )}
      <section className={`output-wrap ${fullscreenOutput ? "fullscreen" : ""}`}>
        <div className="output-label">
          <div className="output-controls">
            <button
              type="button"
              className="fullscreen-toggle"
              aria-pressed={fullscreenOutput}
              aria-label={fullscreenOutput ? "Riduci output" : "Espandi output a schermo intero"}
              onClick={() => setFullscreenOutput((value) => !value)}
            >
              {fullscreenOutput ? "⤡" : "⤢"}
            </button>
            {agentic && (
              <span className="output-mode" role="group" aria-label="Vista output">
                <button
                  type="button"
                  aria-pressed={outputMode === "blocks"}
                  onClick={() => setOutputMode("blocks")}
                >
                  Blocchi
                </button>
                <button
                  type="button"
                  aria-pressed={outputMode === "terminal"}
                  onClick={() => setOutputMode("terminal")}
                >
                  Terminale
                </button>
                {claude && historyEnabled && (
                  <button
                    type="button"
                    aria-pressed={outputMode === "history"}
                    onClick={() => setOutputMode("history")}
                  >
                    Cronologia
                  </button>
                )}
              </span>
            )}
            {panes.length > 1 ? (
              <select
                className="pane-selector"
                aria-label="Pane tmux"
                value={paneId}
                onChange={(event) => setPaneId(event.target.value)}
              >
                {panes.map((pane) => (
                  <option value={pane.id} key={pane.id}>
                    {pane.window_index}.{pane.pane_index} · {pane.command}
                  </option>
                ))}
              </select>
            ) : (
              <span>{panes[0] ? `tmux ${panes[0].window_index}.${panes[0].pane_index}` : "tmux"}</span>
            )}
          </div>
        </div>
        {connection === "closed" && (
          <div className="session-closed-banner" role="alert">
            La sessione tmux è stata chiusa. Torna alla dashboard.
          </div>
        )}
        {outputMode === "history" && claude ? (
          <div
            ref={(element) => { outputRef.current = element; }}
            className="output chat-blocks history-blocks"
            onScroll={updateScrollMode}
          >
            {historyError && <p className="error">{historyError}</p>}
            {history?.truncated && (
              <p className="history-notice">
                Cronologia parziale: sono mostrati i messaggi più recenti.
              </p>
            )}
            {history?.messages.map((message) => (
              <article
                className={`chat-block ${
                  message.kind === "activity" ? "activity" : message.role === "user" ? "user" : "agent"
                }`}
                key={message.id}
              >
                <small>
                  {message.kind === "activity"
                    ? "Attività"
                    : message.role === "user"
                      ? "Tu"
                      : session.current_command}
                  {" · "}{new Date(message.timestamp).toLocaleString("it-IT")}
                </small>
                <pre>
                  {message.kind === "activity"
                    ? `${message.pending ? "⏳ " : "🔧 "}${message.content}${message.pending ? " (in corso o in attesa di conferma)" : ""}`
                    : message.content}
                </pre>
              </article>
            ))}
            {!history && !historyError && (
              <p className="output-waiting">Caricamento cronologia…</p>
            )}
            {history && history.messages.length === 0 && (
              <p className="output-waiting">Nessun messaggio testuale disponibile.</p>
            )}
          </div>
        ) : outputMode === "blocks" && agentic ? (
          <div
            ref={(element) => { outputRef.current = element; }}
            className="output chat-blocks"
            onScroll={updateScrollMode}
          >
            {content ? chatBlocks(content, session.current_command).map((block, index) => {
              const blockKey = `${index}-${block.content.slice(0, 20)}`;
              return (
                <article className={`chat-block ${block.kind}`} key={blockKey}>
                  <div className="chat-block-header">
                    <small>
                      {block.kind === "user"
                        ? "Tu"
                        : block.kind === "agent"
                          ? session.current_command
                          : "Attività"}
                    </small>
                    {block.kind === "agent" && (
                      <button
                        type="button"
                        className="chat-copy"
                        onClick={() => void copyAgentBlock(blockKey, block.content)}
                      >
                        {copiedAgentBlock === blockKey ? "Copiato" : "Copia pulito"}
                      </button>
                    )}
                  </div>
                  <pre>{block.content}</pre>
                </article>
              );
            }) : (
              <p className="output-waiting">In attesa dell'output…</p>
            )}
          </div>
        ) : (
          <div className="output terminal-xterm" ref={terminalContainerRef} />
        )}
        {outputMode === "terminal" && terminalLoading && (
          <p className="output-waiting terminal-loading">Carico il terminale…</p>
        )}
        {outputMode === "terminal" && loadingMoreHistory && (
          <div className="history-loading" role="status">Carico righe precedenti…</div>
        )}
        {!followingOutput && (
          <button className="follow-output" type="button" onClick={resumeFollowingOutput}>
            ↓ Segui output
          </button>
        )}
      </section>
      <form className={`composer ${identity.role === "viewer" ? "viewer" : ""}`} onSubmit={submit}>
        {attachments.length > 0 && (
          <div className="attachments" aria-label="Allegati al prompt">
            {attachments.map((attachment) => (
              <span className="attachment-chip" key={attachment.id}>
                {attachment.media_type.startsWith("image/") && (
                  <img
                    className="attachment-thumb"
                    src={attachmentPreviewUrl(session.id, attachment.id)}
                    alt=""
                    aria-hidden="true"
                    onError={(event) => { event.currentTarget.style.display = "none"; }}
                  />
                )}
                <span title={attachment.path}>{attachment.name}</span>
                <button
                  type="button"
                  aria-label={`Rimuovi ${attachment.name}`}
                  disabled={deletingAttachmentId === attachment.id}
                  onClick={() => void removeAttachment(attachment)}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <textarea
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          placeholder="Scrivi o incolla un prompt…"
          rows={3}
          maxLength={65536}
          disabled={connection === "closed"}
        />
        <input
          ref={fileInputRef}
          className="file-input"
          type="file"
          multiple
          accept=".csv,.json,.md,.markdown,.pdf,.txt,.xml,image/jpeg,image/png,image/webp"
          onChange={(event) => void selectFiles(event.target.files)}
        />
        {showSpecialKeys && (
          <div className="special-actions" aria-label="Funzioni speciali">
            <button
              disabled={connection === "closed"}
              type="button"
              onClick={() => setShowDirectory(true)}
            >
              Contenuto directory
            </button>
            <button
              disabled={connection === "closed"}
              type="button"
              onClick={() => setShowArtifacts(true)}
            >
              Artefatti
            </button>
            <button
              disabled={connection === "closed" || sendingArtifactPrompt}
              type="button"
              onClick={() => void sendArtifactInstructions()}
            >
              {sendingArtifactPrompt ? "Invio istruzioni…" : "Consegna artefatto"}
            </button>
            {agentic && (
              <>
                <button
                  disabled={connection === "closed" || compacting || clearing}
                  type="button"
                  onClick={() => void runCompact()}
                >
                  {compacting ? "Compact…" : "Compact"}
                </button>
                <button
                  disabled={connection === "closed" || compacting || clearing}
                  type="button"
                  onClick={() => void runClear()}
                >
                  {clearing ? "Clear…" : "Clear"}
                </button>
              </>
            )}
            <button disabled={connection === "closed"} type="button" onClick={() => void pressSpecialKey("Up")}>↑ Up</button>
            <button disabled={connection === "closed"} type="button" onClick={() => void pressSpecialKey("Down")}>↓ Down</button>
            <button disabled={connection === "closed"} type="button" onClick={() => void pressSpecialKey("Escape")}>Esc</button>
            <button disabled={connection === "closed"} type="button" className="danger" onClick={() => void pressSpecialKey("C-c")}>
              Ctrl-C
            </button>
            {(session.current_command.toLowerCase().includes("claude")
              || /agy|antigravity/i.test(session.current_command)) && (
              <button
                disabled={connection === "closed"}
                type="button"
                onClick={() => void pressSpecialKey("Shift-Tab")}
              >
                {/agy|antigravity/i.test(session.current_command) ? "AGY" : "Claude"} · cambia permessi
              </button>
            )}
            {session.current_command.toLowerCase().includes("codex") && (
              <button
                disabled={connection === "closed"}
                type="button"
                onClick={() => void openCodexPermissions()}
              >
                Codex · permessi
              </button>
            )}
            <button
              disabled={connection === "closed" || splittingPane}
              type="button"
              onClick={() => void createPane("horizontal")}
            >
              {splittingPane ? "Divisione…" : "Dividi orizzontale"}
            </button>
            <button
              disabled={connection === "closed" || splittingPane}
              type="button"
              onClick={() => void createPane("vertical")}
            >
              {splittingPane ? "Divisione…" : "Dividi verticale"}
            </button>
            {panes.length > 1 && (
              <button
                disabled={connection === "closed" || closingPane || !paneId}
                type="button"
                className="danger"
                onClick={() => void closePane()}
              >
                {closingPane ? "Chiusura…" : "Chiudi pane"}
              </button>
            )}
          </div>
        )}
        {showDirectory && (
          <DirectoryModal sessionId={session.id} onClose={() => setShowDirectory(false)} />
        )}
        {showArtifacts && (
          <ArtifactsModal sessionId={session.id} onClose={() => setShowArtifacts(false)} />
        )}
        <div className="actions">
          <button
            type="button"
            className="secondary special-toggle"
            disabled={connection === "closed"}
            aria-expanded={showSpecialKeys}
            aria-label="Funzioni speciali"
            onClick={() => setShowSpecialKeys((value) => !value)}
          >
            Funzioni
          </button>
          <button
            type="button"
            className="secondary attach-button"
            disabled={connection === "closed" || uploading || attachments.length >= 5}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? "Caricamento…" : "＋ Allega"}
          </button>
          <button
            type="button"
            className="secondary enter-button"
            disabled={connection === "closed"}
            onClick={() => void pressEnter()}
          >
            ↵ Enter
          </button>
          <button
            type="submit"
            disabled={
              connection === "closed"
              || (!draft && attachments.length === 0)
              || sending
              || uploading
            }
          >
            Invia testo
          </button>
        </div>
        {controlError && <small className="attachment-error">{controlError}</small>}
        {attachmentError && <small className="attachment-error">{attachmentError}</small>}
        <small>Il testo non invia Enter automaticamente.</small>
      </form>
    </main>
  );
}

export default function App() {
  const online = useOnlineStatus();
  const [active, setActive] = useState<Session | null>(null);
  const [draftsBySession, setDraftsBySession] = useState<Record<string, string>>({});
  const [recentSessions, setRecentSessions] = useState<Session[]>(readRecentSessions);
  const [identity, setIdentity] = useState<Identity | null | undefined>(undefined);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  useEffect(() => {
    window.localStorage.setItem(RECENT_SESSIONS_KEY, JSON.stringify(recentSessions));
  }, [recentSessions]);
  useEffect(() => {
    restoreSession().then(setIdentity).catch(() => setIdentity(null));
  }, []);
  function rememberSession(session: Session) {
    setRecentSessions((current) => {
      return [session, ...current.filter((item) => item.id !== session.id)].slice(0, 2);
    });
  }
  function openSession(next: Session) {
    if (active && active.id !== next.id) rememberSession(active);
    setActive(next);
  }
  function closeSession() {
    if (active) rememberSession(active);
    setActive(null);
  }
  function setSessionDraft(sessionId: string, draft: string) {
    setDraftsBySession((current) => {
      if (!draft) {
        const { [sessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return { ...current, [sessionId]: draft };
    });
  }
  useEffect(() => {
    // Copre anche Console (WS/polling), non solo la lista sessioni: una
    // sessione scaduta mentre si è dentro una console (es. scheda rimasta
    // dormiente a lungo) deve comunque riportare al login.
    setUnauthorizedHandler(() => setIdentity(null));
    return () => setUnauthorizedHandler(null);
  }, []);
  let content: ReactNode;
  if (identity === undefined) {
    content = <main className="login"><p>Verifica sessione…</p></main>;
  } else if (identity === null) {
    content = (
      <main className="login">
        <form onSubmit={async (event) => {
          event.preventDefault();
          try {
            setIdentity(await login(username, password));
            setLoginError("");
          } catch {
            setLoginError("Credenziali non valide");
          }
        }}>
          <span className="eyebrow">PRIVATE CONSOLE</span>
          <h1>Accedi</h1>
          <p>Le credenziali sono verificate dal server e non vengono incluse nell'app.</p>
          <input
            type="text"
            autoComplete="username"
            aria-label="Nome utente"
            placeholder="Nome utente"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <button type="submit">Continua</button>
          {loginError && <p className="error">{loginError}</p>}
        </form>
      </main>
    );
  } else {
    content = active
      ? (
        <Console
          key={active.id}
          session={active}
          identity={identity}
          onBack={closeSession}
          onSwitch={openSession}
          recentSessions={recentSessions.filter((item) => item.id !== active.id)}
          draft={draftsBySession[active.id] ?? ""}
          onDraftChange={(draft) => setSessionDraft(active.id, draft)}
        />
      )
      : <SessionList identity={identity} onOpen={openSession} />;
  }
  return (
    <>
      {!online && (
        <p className="offline-banner" role="status">
          Connessione assente: in attesa di rete, alcune funzioni sono sospese.
        </p>
      )}
      {content}
    </>
  );
}
