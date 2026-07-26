import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ApiError,
  ArchivedSession,
  Attachment,
  archiveSession,
  createUser,
  createSnapshot,
  createSession,
  deleteArchive,
  deleteSnapshot,
  deleteAttachment,
  DirectoryEntry,
  DirectoryListing,
  fetchConfig,
  fetchDirectory,
  fetchFile,
  fileDownloadUrl,
  FileContent,
  errorMessage,
  login,
  Identity,
  listSessions,
  listArchives,
  listPanes,
  listSnapshots,
  listUsers,
  Pane,
  renameSession,
  restoreSession,
  restoreArchive,
  restoreSnapshot,
  Role,
  resizePane,
  sendEnter,
  sendKey,
  sendText,
  Session,
  setUserActive,
  Snapshot,
  SnapshotMode,
  splitPane,
  streamUrl,
  terminateSession,
  uploadAttachment,
  UserAccount,
} from "./api";

type Connection = "connecting" | "online" | "offline" | "closed";

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: "connessione",
  online: "online",
  offline: "offline",
  closed: "chiusa",
};

const LATEST_RELEASE = {
  title: "Archivio sessioni",
  description:
    "Archivia una sessione e rilanciala in seguito; Codex e Claude riaprono il proprio selettore di resume.",
};

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
  onUnauthorized,
  identity,
}: {
  onOpen: (session: Session) => void;
  onUnauthorized: () => void;
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
  const [showUsers, setShowUsers] = useState(false);
  const [openActionsId, setOpenActionsId] = useState<string | null>(null);

  useEffect(() => {
    listSessions().then(setSessions).catch((value) => {
      if (value instanceof ApiError && value.status === 401) onUnauthorized();
      else setError(errorMessage(value));
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

  return (
    <main className="shell">
      <header className="topbar">
        <div><span className="eyebrow">TMUX / PRIVATE NETWORK</span><h1>Sessions</h1></div>
        <div className="topbar-actions">
          <button className="help-button" onClick={() => setShowHelp(true)} aria-label="Apri guida">
            ?
          </button>
          <span className="count">{sessions.length}</span>
        </div>
      </header>
      <div className="dashboard-actions">
        {identity.role !== "viewer" && (
          <button className="new-session" onClick={() => setCreating((value) => !value)}>+ Nuova sessione</button>
        )}
        {identity.role !== "viewer" && (
          <button className="snapshot-button" onClick={() => setShowSnapshots(true)}>Snapshot</button>
        )}
        {identity.role !== "viewer" && (
          <button className="snapshot-button" onClick={() => setShowArchives(true)}>Archivio</button>
        )}
        {identity.role === "admin" && (
          <button className="snapshot-button" onClick={() => setShowUsers(true)}>Utenti</button>
        )}
      </div>
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
      <section className="session-list">
        {sessions.map((session) => (
          <article className="session-item" key={session.id}>
            <div className="session-row">
              <button className="session-card" onClick={() => onOpen(session)}>
                <span className="session-icon">&gt;_</span>
                <span className="session-copy">
                  <strong>{session.name}</strong>
                  <small>{session.current_command} · {session.windows} window</small>
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
      </section>
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
  identity,
}: {
  session: Session;
  onBack: () => void;
  identity: Identity;
}) {
  const [content, setContent] = useState("");
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
  const outputRef = useRef<HTMLPreElement>(null);
  const outputLinesRef = useRef<string[]>([]);
  const outputSequenceRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    if (!paneId) return;
    let socket: WebSocket | undefined;
    let timer: number | undefined;
    let stopped = false;
    let attempts = 0;
    const connect = () => {
      if (stopped) return;
      setConnection("connecting");
      socket = new WebSocket(streamUrl(session.id, paneId));
      socket.onopen = () => { attempts = 0; setConnection("online"); };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "snapshot") {
          outputLinesRef.current = message.content.match(/[^\n]*\n|[^\n]+$/g) ?? [];
          outputSequenceRef.current = message.sequence_id;
          setContent(message.content);
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
  }, [session.id, paneId]);

  useEffect(() => {
    const output = outputRef.current;
    if (!output || !paneId || typeof ResizeObserver === "undefined") return;
    let timer: number | undefined;
    const pane = panes.find((item) => item.id === paneId);
    let previous = pane ? `${pane.width}x${pane.height}` : "";
    const observer = new ResizeObserver(([entry]) => {
      const columns = Math.max(20, Math.min(500, Math.floor(entry.contentRect.width / 8)));
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
  }, [session.id, paneId, panes]);

  useEffect(() => {
    if (followingOutput && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [content, followingOutput]);

  function updateScrollMode() {
    const output = outputRef.current;
    if (!output) return;
    const distanceFromBottom = output.scrollHeight - output.scrollTop - output.clientHeight;
    setFollowingOutput(distanceFromBottom < 48);
  }

  function resumeFollowingOutput() {
    setFollowingOutput(true);
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
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

  async function pressSpecialKey(key: "Up" | "Down" | "Escape" | "C-c") {
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

  async function pressEnter() {
    setControlError("");
    try {
      await sendEnter(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    }
  }

  async function createPane() {
    setSplittingPane(true);
    setControlError("");
    try {
      const created = await splitPane(session.id, paneId || undefined);
      const items = await listPanes(session.id);
      setPanes(items);
      setPaneId(created.id);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setSplittingPane(false);
    }
  }

  return (
    <main className="console">
      <header className="console-header">
        <button className="icon-button" onClick={onBack} aria-label="Indietro">‹</button>
        <div><strong>{session.name}</strong><small>{session.current_command}</small></div>
        <span className={`status ${connection}`}>{CONNECTION_LABEL[connection]}</span>
      </header>
      <section className="output-wrap">
        <div className="output-label">
          <span>OUTPUT RECENTE</span>
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
        {connection === "closed" && (
          <div className="session-closed-banner" role="alert">
            La sessione tmux è stata chiusa. Torna alla dashboard.
          </div>
        )}
        <pre ref={outputRef} className="output" onScroll={updateScrollMode}>
          {content || "In attesa dell'output…"}
        </pre>
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
            <button
              disabled={connection === "closed" || splittingPane}
              type="button"
              onClick={() => void createPane()}
            >
              {splittingPane ? "Divisione…" : "Dividi pane"}
            </button>
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
  const [active, setActive] = useState<Session | null>(null);
  const [identity, setIdentity] = useState<Identity | null | undefined>(undefined);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  useEffect(() => {
    restoreSession().then(setIdentity).catch(() => setIdentity(null));
  }, []);
  if (identity === undefined) {
    return <main className="login"><p>Verifica sessione…</p></main>;
  }
  if (identity === null) {
    return (
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
  }
  return active
    ? <Console session={active} identity={identity} onBack={() => setActive(null)} />
    : <SessionList identity={identity} onOpen={setActive} onUnauthorized={() => setIdentity(null)} />;
}
