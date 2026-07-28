import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import {
  ApiError,
  AgentStatus,
  ArchivedSession,
  AuditEvent,
  Attachment,
  Backup,
  ClaudeHistory,
  archiveSession,
  attachmentPreviewUrl,
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
  fetchProviderRateLimits,
  fetchPushPublicKey,
  fileDownloadUrl,
  FileContent,
  errorMessage,
  login,
  Identity,
  killPane,
  listSessions,
  listArchives,
  listAgentStatuses,
  listAudit,
  listBackups,
  listPanes,
  listSnapshots,
  listUsers,
  Pane,
  ProviderRateLimits,
  renameSession,
  restoreSession,
  setUnauthorizedHandler,
  restoreArchive,
  restoreSnapshot,
  Role,
  resizePane,
  sendEnter,
  sendKey,
  sendText,
  Session,
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

const LATEST_RELEASE = {
  title: "Preferenze: vista predefinita",
  description:
    "Scegli se le sessioni Codex/Claude si aprono di default in Blocchi o Terminale, dal nuovo pulsante Preferenze nella dashboard.",
};

const AGENT_STATE_ICON: Record<AgentStatus["state"], string> = {
  active: "◌",
  idle: "✓",
  waiting_input: "!",
  waiting_authorization: "🔒",
  unknown: "?",
};

const DEFAULT_AGENT_VIEW_KEY = "mac-default-agent-view";

function readDefaultAgentView(): "blocks" | "terminal" {
  return window.localStorage.getItem(DEFAULT_AGENT_VIEW_KEY) === "terminal" ? "terminal" : "blocks";
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
  for (const line of chatLines(content, provider)) {
    const visible = line.replace(ANSI_SEQUENCE, "");
    let kind = current?.kind ?? "activity";
    if (/^\s*[›❯>]\s*/.test(visible)) kind = "user";
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

function suggestedSnapshotMode(session: Session): SnapshotMode {
  const command = session.current_command.toLowerCase();
  if (command.includes("codex")) return "codex";
  if (command.includes("claude")) return "claude";
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

function PreferencesModal({ onClose }: { onClose: () => void }) {
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
        <p className="empty">
          Si applica alla prossima apertura di una sessione Codex/Claude; la
          vista Cronologia resta sempre raggiungibile dal toggle, quando
          abilitata.
        </p>
      </section>
    </div>
  );
}

function AuditModal({ onClose }: { onClose: () => void }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    listAudit()
      .then(setEvents)
      .catch((value) => setError(errorMessage(value)))
      .finally(() => setLoading(false));
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
  const [profile, setProfile] = useState<"shell" | "codex" | "claude">("shell");
  const [presets, setPresets] = useState<[string, string][]>([]);
  const [customDirectory, setCustomDirectory] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showSnapshots, setShowSnapshots] = useState(false);
  const [showArchives, setShowArchives] = useState(false);
  const [showAudit, setShowAudit] = useState(false);
  const [showBackups, setShowBackups] = useState(false);
  const [showUsers, setShowUsers] = useState(false);
  const [showPreferences, setShowPreferences] = useState(false);
  const [openActionsId, setOpenActionsId] = useState<string | null>(null);
  const [providerLimits, setProviderLimits] = useState<ProviderRateLimits | null>(null);
  const [agentStatusBySession, setAgentStatusBySession] = useState<Record<string, AgentStatus>>({});
  const [notifyEnabled, setNotifyEnabled] = useState(false);
  const [notifyError, setNotifyError] = useState("");
  const notifySupported = typeof Notification !== "undefined" && "serviceWorker" in navigator;
  const [searchQuery, setSearchQuery] = useState("");

  const filteredSessions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return sessions;
    return sessions.filter((session) => {
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
  }, [sessions, searchQuery, agentStatusBySession]);

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
      })
      .catch(() => { /* il campo resta vuoto, l'utente può digitare */ });
  }, []);

  useEffect(() => {
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
  }, []);

  useEffect(() => {
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
  }, []);

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
    const nextName = window.prompt("Nuovo nome della sessione", session.name)?.trim();
    if (!nextName || nextName === session.name) return;
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

  return (
    <main className="shell">
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
          <button className="new-session" onClick={() => setCreating((value) => !value)}>+ Nuova sessione</button>
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
            {notifyEnabled ? "Notifiche: on" : "Notifiche: off"}
          </button>
        )}
        <button className="snapshot-button" onClick={() => setShowPreferences(true)}>Preferenze</button>
        {identity.role !== "viewer" && (
          <button className="snapshot-button" onClick={() => setShowSnapshots(true)}>Snapshot</button>
        )}
        {identity.role !== "viewer" && (
          <button className="snapshot-button" onClick={() => setShowArchives(true)}>Archivio</button>
        )}
        {identity.role === "admin" && (
          <button className="snapshot-button" onClick={() => setShowUsers(true)}>Utenti</button>
        )}
        {identity.role === "admin" && (
          <button className="snapshot-button" onClick={() => setShowAudit(true)}>Audit</button>
        )}
        {identity.role === "admin" && (
          <button className="snapshot-button" onClick={() => setShowBackups(true)}>Backup</button>
        )}
      </div>
      {providerLimits && (
        <section className="provider-limits" aria-label="Quote provider">
          {providerLimits.providers.map((provider) => (
            <article key={provider.provider}>
              <header>
                <strong>{provider.provider}</strong>
                <small>{provider.observed_at ? formatDate(provider.observed_at) : "non disponibile"}</small>
              </header>
              {provider.available ? (
                <div className="provider-windows">
                  {provider.windows.map((window) => (
                    <span key={window.label} title={window.detail ?? undefined}>
                      <small>{window.label}</small>
                      <strong style={{ color: rateLimitColor(window.used_percent) }}>
                        {window.used_percent === null ? "n/d" : `${Math.round(window.used_percent)}%`}
                      </strong>
                      {window.detail && <em>{window.detail}</em>}
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
      {creating && <form className="create-form" onSubmit={async (event) => {
        event.preventDefault();
        try {
          await createSession(name, directory, profile);
          setCreating(false); setName(""); setProfile("shell"); setError("");
          setSessions(await listSessions());
        } catch (value) {
          setError(errorMessage(value));
        }
      }}>
        <input
          required
          pattern="[A-Za-z0-9_-]+( [A-Za-z0-9_-]+)*"
          maxLength={64}
          title="Usa lettere, numeri, trattini e spazi singoli tra le parole"
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
          onChange={(event) => setProfile(event.target.value as "shell" | "codex" | "claude")}
        >
          <option value="shell">Shell</option>
          <option value="codex">Codex</option>
          <option value="claude">Claude</option>
        </select>
        <button type="submit">Crea sessione</button>
      </form>}
      {error && <p className="error">{error}</p>}
      {notifyError && <p className="error">{notifyError}</p>}
      {sessions.length > 0 && (
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
        {filteredSessions.map((session) => (
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
                <button type="button" className="danger" onClick={() => void terminateListedSession(session)}>
                  Termina
                </button>
              </div>
            )}
          </article>
        ))}
        {!error && sessions.length === 0 && <p className="empty">Nessuna sessione sul socket configurato.</p>}
        {!error && sessions.length > 0 && filteredSessions.length === 0 && (
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
      {showPreferences && <PreferencesModal onClose={() => setShowPreferences(false)} />}
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
  identity,
}: {
  session: Session;
  onBack: () => void;
  onSwitch: (session: Session) => void;
  identity: Identity;
}) {
  const [content, setContent] = useState("");
  const contentRef = useRef(content);
  useEffect(() => { contentRef.current = content; }, [content]);
  const [draft, setDraft] = useState("");
  const [connection, setConnection] = useState<Connection>("connecting");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingAttachmentId, setDeletingAttachmentId] = useState("");
  const [followingOutput, setFollowingOutput] = useState(true);
  const [showSpecialKeys, setShowSpecialKeys] = useState(false);
  const [showDirectory, setShowDirectory] = useState(false);
  const [controlError, setControlError] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachmentError, setAttachmentError] = useState("");
  const [panes, setPanes] = useState<Pane[]>([]);
  const [paneId, setPaneId] = useState("");
  const [splittingPane, setSplittingPane] = useState(false);
  const [closingPane, setClosingPane] = useState(false);
  const agentic = /codex|claude/i.test(session.current_command);
  const claude = /claude/i.test(session.current_command);
  const [historyEnabled, setHistoryEnabled] = useState(false);
  const [history, setHistory] = useState<ClaudeHistory | null>(null);
  const [historyError, setHistoryError] = useState("");
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

  const ownProviderLimit = providerLimits?.providers.find(
    (provider) => provider.provider === ownStatus?.provider,
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
      setDraft("");
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
        <div><strong>{session.name}</strong><small>{session.current_command}</small></div>
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
            <span key={window.label} title={window.detail ?? undefined}>
              <small>{window.label}</small>{" "}
              <strong style={{ color: rateLimitColor(window.used_percent) }}>
                {window.used_percent === null ? "n/d" : `${Math.round(window.used_percent)}%`}
              </strong>
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
      <section className="output-wrap">
        <div className="output-label">
          <div className="output-controls">
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
            {content ? chatBlocks(content, session.current_command).map((block, index) => (
              <article className={`chat-block ${block.kind}`} key={`${index}-${block.content.slice(0, 20)}`}>
                <small>
                  {block.kind === "user"
                    ? "Tu"
                    : block.kind === "agent"
                      ? session.current_command
                      : "Attività"}
                </small>
                <pre>{block.content}</pre>
              </article>
            )) : (
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
          onChange={(event) => setDraft(event.target.value)}
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
        <div className="utility-actions">
          <button
            type="button"
            className="secondary"
            disabled={connection === "closed"}
            aria-expanded={showSpecialKeys}
            onClick={() => setShowSpecialKeys((value) => !value)}
          >
            Funzioni speciali
          </button>
          <button
            type="button"
            className="secondary"
            disabled={connection === "closed"}
            onClick={() => setShowDirectory(true)}
          >
            Contenuto directory
          </button>
        </div>
        {showSpecialKeys && (
          <div className="special-actions" aria-label="Funzioni speciali">
            <button disabled={connection === "closed"} type="button" onClick={() => void pressSpecialKey("Up")}>↑ Up</button>
            <button disabled={connection === "closed"} type="button" onClick={() => void pressSpecialKey("Down")}>↓ Down</button>
            <button disabled={connection === "closed"} type="button" onClick={() => void pressSpecialKey("Escape")}>Esc</button>
            <button disabled={connection === "closed"} type="button" className="danger" onClick={() => void pressSpecialKey("C-c")}>
              Ctrl-C
            </button>
            {session.current_command.toLowerCase().includes("claude") && (
              <button
                disabled={connection === "closed"}
                type="button"
                onClick={() => void pressSpecialKey("Shift-Tab")}
              >
                Claude · cambia permessi
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
        <div className="actions">
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
            className="secondary"
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
  const [identity, setIdentity] = useState<Identity | null | undefined>(undefined);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  useEffect(() => {
    restoreSession().then(setIdentity).catch(() => setIdentity(null));
  }, []);
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
          onBack={() => setActive(null)}
          onSwitch={setActive}
        />
      )
      : <SessionList identity={identity} onOpen={setActive} />;
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
