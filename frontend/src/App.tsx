import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Attachment,
  createSession,
  deleteAttachment,
  fetchConfig,
  login,
  listSessions,
  restoreSession,
  sendEnter,
  sendText,
  Session,
  streamUrl,
  uploadAttachment,
} from "./api";

type Connection = "connecting" | "online" | "offline";

function SessionList({ onOpen, onUnauthorized }: { onOpen: (session: Session) => void; onUnauthorized: () => void }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [presets, setPresets] = useState<[string, string][]>([]);
  const [customDirectory, setCustomDirectory] = useState(false);

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

  return (
    <main className="shell">
      <header className="topbar">
        <div><span className="eyebrow">TMUX / PRIVATE NETWORK</span><h1>Sessions</h1></div>
        <span className="count">{sessions.length}</span>
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
        <input required pattern="[A-Za-z0-9_-]{1,64}" placeholder="Nome sessione" value={name} onChange={(event) => setName(event.target.value)} />
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
    </main>
  );
}

function Console({ session, onBack }: { session: Session; onBack: () => void }) {
  const [content, setContent] = useState("");
  const [draft, setDraft] = useState("");
  const [connection, setConnection] = useState<Connection>("connecting");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingAttachmentId, setDeletingAttachmentId] = useState("");
  const [followingOutput, setFollowingOutput] = useState(true);
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

  return (
    <main className="console">
      <header className="console-header">
        <button className="icon-button" onClick={onBack} aria-label="Indietro">‹</button>
        <div><strong>{session.name}</strong><small>{session.current_command}</small></div>
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
