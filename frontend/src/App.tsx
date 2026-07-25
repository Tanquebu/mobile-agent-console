import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Attachment,
  createSession,
  deleteAttachment,
  DirectoryEntry,
  DirectoryListing,
  fetchConfig,
  fetchDirectory,
  fetchFile,
  FileContent,
  login,
  listSessions,
  renameSession,
  restoreSession,
  sendEnter,
  sendKey,
  sendText,
  Session,
  streamUrl,
  terminateSession,
  uploadAttachment,
} from "./api";

type Connection = "connecting" | "online" | "offline";

const LATEST_RELEASE = {
  title: "Rinomina sessioni",
  description:
    "Le sessioni possono essere rinominate dalla console e i nomi possono contenere spazi tra le parole.",
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
      .catch((value) => { if (!cancelled) setError(value instanceof Error ? value.message : String(value)); })
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
      .catch((value) => { if (!cancelled) setError(value instanceof Error ? value.message : String(value)); })
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
    else if (entry.type === "file") setOpenFile(fullPath);
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

function SessionList({ onOpen, onUnauthorized }: { onOpen: (session: Session) => void; onUnauthorized: () => void }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [presets, setPresets] = useState<[string, string][]>([]);
  const [customDirectory, setCustomDirectory] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    listSessions().then(setSessions).catch((value) => {
      if (String(value).includes("401")) onUnauthorized();
      else setError(String(value));
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
      <button className="new-session" onClick={() => setCreating((value) => !value)}>+ Nuova sessione</button>
      {creating && <form className="create-form" onSubmit={async (event) => {
        event.preventDefault();
        try {
          await createSession(name, directory);
          setCreating(false); setName(""); setError(""); setSessions(await listSessions());
        } catch (value) {
          setError(value instanceof Error ? value.message : String(value));
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
        <button type="submit">Crea shell</button>
      </form>}
      {error && <p className="error">{error}</p>}
      <section className="session-list">
        {sessions.map((session) => (
          <button className="session-card" key={session.id} onClick={() => onOpen(session)}>
            <span className="session-icon">&gt;_</span>
            <span className="session-copy">
              <strong>{session.name}</strong>
              <small>{session.current_command} · {session.windows} window</small>
            </span>
            <span className="chevron">›</span>
          </button>
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
    </main>
  );
}

function Console({ session, onBack }: { session: Session; onBack: () => void }) {
  const [sessionName, setSessionName] = useState(session.name);
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
  const outputRef = useRef<HTMLPreElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let timer: number | undefined;
    let stopped = false;
    let attempts = 0;
    const connect = () => {
      if (stopped) return;
      setConnection("connecting");
      socket = new WebSocket(streamUrl(session.id));
      socket.onopen = () => { attempts = 0; setConnection("online"); };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "snapshot") setContent(message.content);
        if (message.type === "session_closed") setConnection("offline");
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
  }, [session.id]);

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
      await sendText(session.id, draft, attachments.map((attachment) => attachment.id));
      setDraft("");
      setAttachments([]);
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
      setAttachmentError(value instanceof Error ? value.message : String(value));
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
      setAttachmentError(value instanceof Error ? value.message : String(value));
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
      await sendKey(session.id, key, key === "C-c");
    } catch (value) {
      setControlError(value instanceof Error ? value.message : String(value));
    }
  }

  async function terminateCurrentSession() {
    const confirmed = window.confirm(
      `Terminare definitivamente la sessione “${sessionName}”?`,
    );
    if (!confirmed) return;
    setControlError("");
    try {
      await terminateSession(session.id);
      onBack();
    } catch (value) {
      setControlError(value instanceof Error ? value.message : String(value));
    }
  }

  async function renameCurrentSession() {
    const nextName = window.prompt("Nuovo nome della sessione", sessionName)?.trim();
    if (!nextName || nextName === sessionName) return;
    setControlError("");
    try {
      await renameSession(session.id, nextName);
      setSessionName(nextName);
    } catch (value) {
      setControlError(value instanceof Error ? value.message : String(value));
    }
  }

  return (
    <main className="console">
      <header className="console-header">
        <button className="icon-button" onClick={onBack} aria-label="Indietro">‹</button>
        <div><strong>{sessionName}</strong><small>{session.current_command}</small></div>
        <span className={`status ${connection}`}>{connection}</span>
      </header>
      <section className="output-wrap">
        <div className="output-label"><span>OUTPUT RECENTE</span><span>tmux :0.0</span></div>
        <pre ref={outputRef} className="output" onScroll={updateScrollMode}>
          {content || "In attesa dell'output…"}
        </pre>
        {!followingOutput && (
          <button className="follow-output" type="button" onClick={resumeFollowingOutput}>
            ↓ Segui output
          </button>
        )}
      </section>
      <form className="composer" onSubmit={submit}>
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
            aria-expanded={showSpecialKeys}
            onClick={() => setShowSpecialKeys((value) => !value)}
          >
            Funzioni speciali
          </button>
          <button type="button" className="secondary" onClick={() => setShowDirectory(true)}>
            Contenuto directory
          </button>
          <button type="button" className="secondary full-width" onClick={() => void renameCurrentSession()}>
            Rinomina sessione
          </button>
          <button type="button" className="danger full-width" onClick={() => void terminateCurrentSession()}>
            Termina sessione
          </button>
        </div>
        {showSpecialKeys && (
          <div className="special-actions" aria-label="Funzioni speciali">
            <button type="button" onClick={() => void pressSpecialKey("Up")}>↑ Up</button>
            <button type="button" onClick={() => void pressSpecialKey("Down")}>↓ Down</button>
            <button type="button" onClick={() => void pressSpecialKey("Escape")}>Esc</button>
            <button type="button" className="danger" onClick={() => void pressSpecialKey("C-c")}>
              Ctrl-C
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
            disabled={uploading || attachments.length >= 5}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? "Caricamento…" : "＋ Allega"}
          </button>
          <button type="button" className="secondary" onClick={() => sendEnter(session.id)}>↵ Enter</button>
          <button
            type="submit"
            disabled={(!draft && attachments.length === 0) || sending || uploading}
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
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  useEffect(() => {
    restoreSession().then(() => setAuthenticated(true)).catch(() => setAuthenticated(false));
  }, []);
  if (authenticated === null) {
    return <main className="login"><p>Verifica sessione…</p></main>;
  }
  if (!authenticated) {
    return (
      <main className="login">
        <form onSubmit={async (event) => {
          event.preventDefault();
          try {
            await login(password);
            setAuthenticated(true);
            setLoginError("");
          } catch {
            setLoginError("Credenziali non valide");
          }
        }}>
          <span className="eyebrow">PRIVATE CONSOLE</span>
          <h1>Accedi</h1>
          <p>La password resta sul server e non viene inclusa nell'app.</p>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <button type="submit">Continua</button>
          {loginError && <p className="error">{loginError}</p>}
        </form>
      </main>
    );
  }
  return active
    ? <Console session={active} onBack={() => setActive(null)} />
    : <SessionList onOpen={setActive} onUnauthorized={() => setAuthenticated(false)} />;
}
