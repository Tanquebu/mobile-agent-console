import { FormEvent, ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
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
  fetchArtifactDirectory,
  fetchArchiveDraft,
  backupDownloadUrl,
  createBackup,
  createUser,
  createSnapshot,
  createSession,
  deleteArchive,
  deleteSnapshot,
  deleteAttachment,
  deleteBackup,
  AppConfig,
  DirectoryEntry,
  DirectoryListing,
  fetchConfig,
  fetchClaudeHistory,
  fetchOpencodeHistory,
  fetchDirectory,
  uploadDirectoryFile,
  fetchFile,
  fetchFileMetadata,
  fetchHostObservability,
  fetchOrchestratorState,
  fetchProviderRateLimits,
  fetchPushPublicKey,
  fetchRateLimitHistory,
  fetchSessionUsage,
  fetchSessionTimeline,
  fileDownloadUrl,
  filePreviewUrl,
  FileMetadata,
  errorMessage,
  login,
  logout,
  Identity,
  HostComponent,
  HostObservabilitySnapshot,
  HostServiceItem,
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
  OpencodeHistory,
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
  scrollPane,
  sendEnter,
  sendArtifactPrompt,
  sendArchiveSummaryPrompt,
  sendKey,
  sendText,
  Session,
  SessionProfile,
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
  streamUrl,
  terminateSession,
  uploadAttachment,
  UserAccount,
} from "./api";

import { Language, readLanguage, writeLanguage, translations } from "./i18n";

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
// Swipe naturale -> scroll-wheel remoto sul pane (POST .../scroll, vedi
// api.ts#scrollPane): ogni SWIPE_PX_PER_TICK px trascinati equivalgono a un
// "tick" di rotellina inviato al processo nel pane (es. il pager interno di
// Claude Code), non al buffer locale di xterm.js. Cap basso per chiamata
// (SWIPE_MAX_TICKS_PER_REQUEST) perché l'accumulo viene svuotato più volte
// durante un drag continuo, non tutto insieme al rilascio del dito.
const SWIPE_PX_PER_TICK = 32;
const SWIPE_MAX_TICKS_PER_REQUEST = 5;
const SESSION_NAME_PATTERN = /^[\p{L}\p{N}_-]+(?: [\p{L}\p{N}_-]+)*$/u;
const SESSION_NAME_HINT = "Usa lettere (anche accentate), numeri, trattini e spazi singoli; massimo 64 caratteri";

const LATEST_RELEASE = {
  title: "Anteprima zero-flicker, chip filtri e riepilogo directory",
  description:
    "Navigazione anteprime fluida con skeleton loader e progress bar senza sfarfallio, chip di filtro rapido per categoria (Cartelle, Codice, Media, Documenti) e badge di riepilogo con conteggio e peso file.",
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
const ORCHESTRATOR_EXPANDED_KEY = "mac-orchestrator-expanded";

type DashboardDensity = "extended" | "compact";
type ProjectSort = "name-asc" | "name-desc";

function readDefaultAgentView(): "blocks" | "terminal" {
  return window.localStorage.getItem(DEFAULT_AGENT_VIEW_KEY) === "terminal" ? "terminal" : "blocks";
}

function readDashboardDensity(): DashboardDensity {
  return window.localStorage.getItem(DASHBOARD_DENSITY_KEY) === "compact" ? "compact" : "extended";
}

function readOrchestratorExpanded(): boolean {
  try {
    return window.sessionStorage.getItem(ORCHESTRATOR_EXPANDED_KEY) === "true";
  } catch {
    return false;
  }
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
    )).map((item) => ({
      ...item,
      // Gli item salvati prima dell'introduzione di `profile` non lo hanno:
      // lo normalizziamo a null senza scartare la sessione.
      profile: typeof item.profile === "string" ? item.profile : null,
    })).slice(0, 2);
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

function getAgentStateLegend(): Array<[AgentStatus["state"], string]> {
  const t = translations[readLanguage()];
  return [
    ["active", t.stateActive],
    ["idle", t.stateIdle],
    ["waiting_input", t.stateWaitingInput],
    ["waiting_authorization", t.stateWaitingAuth],
    ["unknown", t.stateUnknown],
  ];
}

function getPermissionStateLegend(): Array<[AgentStatus["permission_state"], string]> {
  const t = translations[readLanguage()];
  return [
    ["restricted", t.permRestricted],
    ["ask", t.permAsk],
    ["auto", t.permAuto],
    ["manual", t.permManual],
    ["accept_edits", t.permAcceptEdits],
    ["dont_ask", t.permDontAsk],
    ["plan", t.permPlan],
    ["bypass", t.permBypass],
    ["unknown", t.permUnknown],
  ];
}

type ChatBlockKind = "user" | "agent" | "activity";

type ChatBlock = {
  kind: ChatBlockKind;
  content: string;
  collapsed?: boolean;
};

const BLOCK_COLLAPSE_THRESHOLD = 500;

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

// Righe di chrome della TUI OpenCode da escludere dai blocchi: logo ASCII,
// separatore della barra di stato, suggerimenti tastiera, barra percorso/versione
// e barra di contesto. La TUI vive su schermo alternativo e ripete questo chrome
// in ogni frame (stessa condizione già vista per Antigravity), quindi va filtrato
// in modo esplicito, non dato per scontato. Verificato sulle fixture reali in
// backend/tests/fixtures/opencode-tui/.
function opencodeChrome(text: string): boolean {
  return /^╹▀+$/.test(text)
    || /^[█▀▄ ]+$/.test(text)
    || /ctrl\+p commands/.test(text)
    || /tab agents/.test(text)
    || /esc interrupt|esc again to interrupt/.test(text)
    || /● Tip|Run \/connect/.test(text)
    || /^\/\S+\s+\d+\.\d+\.\d+\s*$/.test(text)
    || /^\/\S+\s+.*\(\d+%\)/.test(text);
}

function opencodeChatBlocks(content: string): ChatBlock[] {
  const blocks: ChatBlock[] = [];
  let current: ChatBlock | undefined;
  let boxTexts: string[] | null = null;
  const append = (kind: ChatBlockKind, text: string) => {
    if (!current || kind !== current.kind) {
      current = { kind, content: text, collapsed: text.length > BLOCK_COLLAPSE_THRESHOLD };
      blocks.push(current);
    } else {
      current.content += `\n${text}`;
      if (!current.collapsed && current.content.length > BLOCK_COLLAPSE_THRESHOLD) {
        current.collapsed = true;
      }
    }
  };
  // La TUI OpenCode incornicia sia i messaggi utente sia le esecuzioni di tool
  // con lo stesso bordo "┃": si accumula l'intera cornice e la si classifica a
  // fine box, perché il marcatore discriminante ("$", "Click to expand",
  // "Permission required") può comparire su qualunque riga della cornice.
  const flushBox = () => {
    if (boxTexts === null) return;
    const body = boxTexts.map((text) => text.trim()).filter(Boolean);
    boxTexts = null;
    if (body.length === 0) return;
    const joined = body.join("\n");
    if (
      /\$ /.test(joined)
      || /Click to expand/.test(joined)
      || /Permission required/.test(joined)
      || /Allow once/.test(joined)
      || /Allow always/.test(joined)
      || /Reject\b/.test(joined)
    ) {
      append("activity", joined);
    } else if (/Ask anything|OpenCode Zen|Build · Big Pickle/.test(joined)) {
      // Placeholder dell'input o status dentro la cornice: chrome, non contenuto.
    } else {
      append("user", joined);
    }
  };
  for (const line of content.split("\n")) {
    const raw = line.replace(ANSI_SEQUENCE, "");
    const trimmed = raw.trim();
    if (/^\s*┃/.test(raw)) {
      boxTexts = boxTexts ?? [];
      boxTexts.push(raw.replace(/^\s*┃\s*/, ""));
      continue;
    }
    flushBox();
    if (!trimmed || opencodeChrome(trimmed)) continue;
    append(/^(?:▣|⠏|\+ Thought:|\$ )/.test(trimmed) ? "activity" : "agent", trimmed);
  }
  flushBox();
  return blocks.filter((block) => block.content.trim());
}

function chatBlocks(content: string, provider: string): ChatBlock[] {
  if (/opencode/i.test(provider)) return opencodeChatBlocks(content);
  const blocks: ChatBlock[] = [];
  let current: ChatBlock | undefined;
  let afterUserBreak = false;
  const codex = /codex/i.test(provider);
  const append = (kind: ChatBlockKind, text: string) => {
    if (!current || kind !== current.kind) {
      current = { kind, content: text, collapsed: text.length > BLOCK_COLLAPSE_THRESHOLD };
      blocks.push(current);
    } else {
      current.content += `${current.content ? "\n" : ""}${text}`;
      if (!current.collapsed && current.content.length > BLOCK_COLLAPSE_THRESHOLD) {
        current.collapsed = true;
      }
    }
  };
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
    else if (afterUserBreak && visible.trim()) kind = "agent";

    if (!current || (visible.trim() && kind !== current.kind)) {
      append(kind, visible);
    } else {
      current.content += `${current.content ? "\n" : ""}${visible}`;
      if (!current.collapsed && current.content.length > BLOCK_COLLAPSE_THRESHOLD) {
        current.collapsed = true;
      }
    }
    if (current) {
      afterUserBreak = current.kind === "user" && !visible.trim();
    }
  }
  return blocks.filter((block) => block.content.trim());
}

type InlineToken =
  | { type: "text"; value: string }
  | { type: "bold"; value: string }
  | { type: "italic"; value: string }
  | { type: "code"; value: string }
  | { type: "link"; text: string; href: string }
  | { type: "url"; href: string };

type PreviewPathHandler = (path: string) => void;

const BLOCK_PREVIEW_PATH_RE = /\/[^\s<>"'`()\[\]{}]+?\.(?:md|markdown|mp3|m4a|mp4|jpe?g|png|webp)(?=$|[\s,.;:!?"'`)\]}])/gi;
const EXACT_BLOCK_PREVIEW_PATH_RE = /^\/[^\n\0]+\.(?:md|markdown|mp3|m4a|mp4|jpe?g|png|webp)$/i;

function previewPathParts(text: string) {
  const parts: Array<{ value: string; path: string | null }> = [];
  let lastIndex = 0;
  BLOCK_PREVIEW_PATH_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = BLOCK_PREVIEW_PATH_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ value: text.slice(lastIndex, match.index), path: null });
    }
    parts.push({ value: match[0], path: match[0] });
    lastIndex = BLOCK_PREVIEW_PATH_RE.lastIndex;
  }
  if (lastIndex < text.length) parts.push({ value: text.slice(lastIndex), path: null });
  return parts;
}

function PreviewPathText({
  text,
  onPreviewPath,
}: {
  text: string;
  onPreviewPath?: PreviewPathHandler;
}) {
  if (!onPreviewPath) return <>{text}</>;
  const t = translations[readLanguage()];
  return previewPathParts(text).map((part, index) => part.path ? (
    <button
      type="button"
      className="block-preview-link"
      key={`${index}-${part.path}`}
      onClick={() => onPreviewPath(part.path!)}
      aria-label={`${t.openFilePreview}: ${part.path}`}
      title={t.openFilePreview}
    >
      {part.value}
    </button>
  ) : <span key={index}>{part.value}</span>);
}

function parseInlineTokens(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  const regex = /(```[^`\n]+```)|(`[^`\n]+`)|(\[[^\]\n]+\]\([^)\n]+\))|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(https?:\/\/[^\s<>"')]+)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }
    const [full, tripleCode, code, link, bold, italic, url] = match;
    if (tripleCode) {
      tokens.push({ type: "code", value: tripleCode.slice(3, -3) });
    } else if (code) {
      tokens.push({ type: "code", value: code.slice(1, -1) });
    } else if (link) {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(link);
      if (
        linkMatch &&
        (linkMatch[2].startsWith("http://") ||
          linkMatch[2].startsWith("https://") ||
          linkMatch[2].startsWith("/") ||
          linkMatch[2].startsWith("#"))
      ) {
        tokens.push({ type: "link", text: linkMatch[1], href: linkMatch[2] });
      } else {
        tokens.push({ type: "text", value: link });
      }
    } else if (bold) {
      tokens.push({ type: "bold", value: bold.slice(2, -2) });
    } else if (italic) {
      tokens.push({ type: "italic", value: italic.slice(1, -1) });
    } else if (url) {
      tokens.push({ type: "url", href: url });
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    tokens.push({ type: "text", value: text.slice(lastIndex) });
  }
  return tokens;
}

// Genera uno slug "alla GitHub" a partire dal testo di un header: minuscolo,
// senza punteggiatura (lettere/numeri unicode, spazi e trattini preservati),
// spazi collassati in trattini singoli.
function githubSlug(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N} -]/gu, "")
    .replace(/\s+/g, "-");
}

// Gestisce il click su un link interno (`#slug`) verso un header nello stesso
// blocco markdown: niente modifica dell'hash della SPA, solo scroll fluido
// verso il target, cercato dentro l'istanza corrente di `.chat-markdown` (non
// `document.getElementById`) per restare scoped quando più blocchi condividono
// lo stesso slug.
function handleHashLinkClick(event: React.MouseEvent<HTMLAnchorElement>, href: string) {
  event.preventDefault();
  const container = event.currentTarget.closest(".chat-markdown");
  if (!container) return;
  const slug = href.slice(1);
  if (!slug) return;
  const target = container.querySelector(`#${CSS.escape(slug)}`);
  target?.scrollIntoView({ block: "start", behavior: "smooth" });
}

function MarkdownInline({ text, onPreviewPath }: { text: string; onPreviewPath?: PreviewPathHandler }) {
  const tokens = parseInlineTokens(text);
  return (
    <>
      {tokens.map((token, idx) => {
        if (token.type === "code") {
          if (onPreviewPath && EXACT_BLOCK_PREVIEW_PATH_RE.test(token.value)) {
            return (
              <button
                type="button"
                className="block-preview-link code"
                key={idx}
                onClick={() => onPreviewPath(token.value)}
                aria-label={`${translations[readLanguage()].openFilePreview}: ${token.value}`}
              >
                <code>{token.value}</code>
              </button>
            );
          }
          return <code key={idx}>{token.value}</code>;
        }
        if (token.type === "bold") return <strong key={idx}><PreviewPathText text={token.value} onPreviewPath={onPreviewPath} /></strong>;
        if (token.type === "italic") return <em key={idx}><PreviewPathText text={token.value} onPreviewPath={onPreviewPath} /></em>;
        if (token.type === "link") {
          const isHash = token.href.startsWith("#");
          if (onPreviewPath && EXACT_BLOCK_PREVIEW_PATH_RE.test(token.href)) {
            return (
              <button
                type="button"
                className="block-preview-link"
                key={idx}
                onClick={() => onPreviewPath(token.href)}
                aria-label={`${translations[readLanguage()].openFilePreview}: ${token.href}`}
              >
                {token.text}
              </button>
            );
          }
          return (
            <a
              key={idx}
              href={token.href}
              target={isHash ? undefined : "_blank"}
              rel={isHash ? undefined : "noopener noreferrer"}
              onClick={isHash ? (event) => handleHashLinkClick(event, token.href) : undefined}
            >
              {token.text}
            </a>
          );
        }
        if (token.type === "url") {
          return (
            <a key={idx} href={token.href} target="_blank" rel="noopener noreferrer">
              {token.href}
            </a>
          );
        }
        return <PreviewPathText key={idx} text={token.value} onPreviewPath={onPreviewPath} />;
      })}
    </>
  );
}

function MarkdownCodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    if (await copyToClipboard(code)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  };
  return (
    <div className="chat-code-block">
      <div className="chat-code-header">
        <span>{lang || "code"}</span>
        <button type="button" className="chat-code-copy" onClick={handleCopy}>
          {copied ? "Copiato" : "Copia"}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

type TableAlign = "left" | "center" | "right";

type MarkdownBlockItem =
  | { type: "code_block"; lang: string; code: string }
  | { type: "heading"; level: number; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "quote"; text: string }
  | { type: "hr" }
  | { type: "table"; header: string[]; rows: string[][]; align: TableAlign[] }
  | { type: "paragraph"; text: string };

function parseMarkdownBlocks(text: string): MarkdownBlockItem[] {
  const blocks: MarkdownBlockItem[] = [];
  const lines = text.split("\n");
  let i = 0;

  // Separatore GFM di una tabella (`| --- | :---: | ---: |`, pipe iniziale e
  // finale opzionali): le colonne definiscono solo l'allineamento, mai testo.
  const tableSeparatorRe = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/;
  // Riga di tabella: deve iniziare con una pipe (il separatore arriva dopo).
  const tableRowRe = /^\s*\|/;
  // Riga orizzontale (`---`, `***`, `___`), ma non `- ` di un elenco né `- - -`.
  const horizontalRuleRe = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;

  function splitTableRow(line: string): string[] {
    const sentinel = "\u0000";
    const cells = line
      .trim()
      .replace(/\\\|/g, sentinel)
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.replace(sentinel, "|").trim());
    return cells;
  }

  function parseTableSeparator(line: string): TableAlign[] {
    return splitTableRow(line).map((cell) => {
      const left = cell.startsWith(":");
      const right = cell.endsWith(":");
      if (left && right) return "center";
      if (right) return "right";
      return "left";
    });
  }

  function nextNonEmptyIndex(lines: string[], start: number): number {
    for (let index = start; index < lines.length; index += 1) {
      if (lines[index].trim()) return index;
    }
    return -1;
  }

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block: deve essere esattamente ``` con linguaggio opzionale sulla stessa riga
    const fenceMatch = line.match(/^\s*```([a-zA-Z0-9_-]+)?\s*$/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || "";
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length) {
        if (/^\s*```\s*$/.test(lines[i])) {
          i += 1;
          break;
        }
        codeLines.push(lines[i]);
        i += 1;
      }
      blocks.push({ type: "code_block", lang, code: codeLines.join("\n") });
      continue;
    }

    const headingMatch = line.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({ type: "heading", level: headingMatch[1].length, text: headingMatch[2] });
      i += 1;
      continue;
    }

    // Tabella GFM: riga che inizia con `|` seguita (anche dopo righe vuote) da
    // un separatore. Consuma header, separatore e righe successive insieme.
    if (tableRowRe.test(line)) {
      const separatorIndex = nextNonEmptyIndex(lines, i + 1);
      if (separatorIndex !== -1 && tableSeparatorRe.test(lines[separatorIndex].trim())) {
        const header = splitTableRow(lines[i]);
        const align = parseTableSeparator(lines[separatorIndex]);
        const rows: string[][] = [];
        let j = separatorIndex + 1;
        while (j < lines.length && tableRowRe.test(lines[j])) {
          rows.push(splitTableRow(lines[j]));
          j += 1;
        }
        blocks.push({ type: "table", header, rows, align });
        i = j;
        continue;
      }
      // Riga con `|` ma senza un vero separatore GFM dopo (es. barra di stato
      // di una TUI, "cmd | grep foo"): niente tabella. Va comunque consumata
      // qui come paragrafo semplice, altrimenti il while esterno resterebbe
      // bloccato per sempre su questa riga — il loop dei paragrafi qui sotto
      // si ferma subito perché la riga corrente soddisfa ancora `tableRowRe`.
      blocks.push({ type: "paragraph", text: line });
      i += 1;
      continue;
    }

    if (horizontalRuleRe.test(line)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    // Elenco puntato (-, *, •)
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        let itemText = lines[i].replace(/^\s*[-*•]\s+/, "");
        i += 1;
        while (
          i < lines.length &&
          lines[i].trim() &&
          !/^\s*[-*•]\s+/.test(lines[i]) &&
          !/^\s*\d+\.\s+/.test(lines[i]) &&
          !/^(#{1,4})\s+/.test(lines[i]) &&
          !/^\s*```([a-zA-Z0-9_-]+)?\s*$/.test(lines[i]) &&
          !tableRowRe.test(lines[i]) &&
          !horizontalRuleRe.test(lines[i])
        ) {
          itemText += ` ${lines[i].trim()}`;
          i += 1;
        }
        items.push(itemText);
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Elenco numerato (1., 2., ecc.)
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        let itemText = lines[i].replace(/^\s*\d+\.\s+/, "");
        i += 1;
        while (
          i < lines.length &&
          lines[i].trim() &&
          !/^\s*[-*•]\s+/.test(lines[i]) &&
          !/^\s*\d+\.\s+/.test(lines[i]) &&
          !/^(#{1,4})\s+/.test(lines[i]) &&
          !/^\s*```([a-zA-Z0-9_-]+)?\s*$/.test(lines[i]) &&
          !tableRowRe.test(lines[i]) &&
          !horizontalRuleRe.test(lines[i])
        ) {
          itemText += ` ${lines[i].trim()}`;
          i += 1;
        }
        items.push(itemText);
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    if (/^\s*>\s*/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^\s*>\s*/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^\s*>\s*/, ""));
        i += 1;
      }
      blocks.push({ type: "quote", text: quoteLines.join("\n") });
      continue;
    }

    if (!line.trim()) {
      i += 1;
      continue;
    }

    const pLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```([a-zA-Z0-9_-]+)?\s*$/.test(lines[i]) &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*[-*•]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*>\s*/.test(lines[i]) &&
      !tableRowRe.test(lines[i]) &&
      !horizontalRuleRe.test(lines[i])
    ) {
      pLines.push(lines[i]);
      i += 1;
    }
    blocks.push({ type: "paragraph", text: pLines.join("\n") });
  }

  return blocks;
}

function MarkdownContent({ content, onPreviewPath }: { content: string; onPreviewPath?: PreviewPathHandler }) {
  const blocks = parseMarkdownBlocks(content);
  // Namespace di slug locale a questo render: azzerato ad ogni chiamata così
  // istanze diverse di MarkdownContent (blocchi chat diversi) non si influenzano
  // a vicenda. Duplicati nello stesso rendering ricevono suffissi -1, -2, ...
  // come fa GitHub.
  const slugCounts = new Map<string, number>();
  const slugFor = (text: string): string => {
    const base = githubSlug(text);
    const count = slugCounts.get(base) ?? 0;
    slugCounts.set(base, count + 1);
    return count === 0 ? base : `${base}-${count}`;
  };
  return (
    <>
      {blocks.map((block, idx) => {
        if (block.type === "code_block") {
          return <MarkdownCodeBlock key={idx} code={block.code} lang={block.lang} />;
        }
        if (block.type === "heading") {
          const id = slugFor(block.text);
          if (block.level === 1 || block.level === 2) {
            return <h4 id={id} key={idx}><MarkdownInline text={block.text} onPreviewPath={onPreviewPath} /></h4>;
          }
          return <h5 id={id} key={idx}><MarkdownInline text={block.text} onPreviewPath={onPreviewPath} /></h5>;
        }
        if (block.type === "ul") {
          return (
            <ul key={idx}>
              {block.items.map((item, itemIdx) => (
                <li key={itemIdx}><MarkdownInline text={item} onPreviewPath={onPreviewPath} /></li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol key={idx}>
              {block.items.map((item, itemIdx) => (
                <li key={itemIdx}><MarkdownInline text={item} onPreviewPath={onPreviewPath} /></li>
              ))}
            </ol>
          );
        }
        if (block.type === "quote") {
          return (
            <blockquote key={idx}>
              <MarkdownInline text={block.text} onPreviewPath={onPreviewPath} />
            </blockquote>
          );
        }
        if (block.type === "hr") {
          return <hr key={idx} />;
        }
        if (block.type === "table") {
          const cellStyle = (cellIdx: number): React.CSSProperties | undefined => {
            const align = block.align[cellIdx];
            if (align === "center") return { textAlign: "center" };
            if (align === "right") return { textAlign: "right" };
            return undefined;
          };
          return (
            <div className="markdown-table-wrap" key={idx}>
              <table>
                <thead>
                  <tr>
                    {block.header.map((cell, cellIdx) => (
                      <th key={cellIdx} style={cellStyle(cellIdx)}>
                        <MarkdownInline text={cell} onPreviewPath={onPreviewPath} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIdx) => (
                    <tr key={rowIdx}>
                      {row.map((cell, cellIdx) => (
                        <td key={cellIdx} style={cellStyle(cellIdx)}>
                          <MarkdownInline text={cell} onPreviewPath={onPreviewPath} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return (
          <p key={idx}>
            <MarkdownInline text={block.text} onPreviewPath={onPreviewPath} />
          </p>
        );
      })}
    </>
  );
}

// Componente per un singolo blocco chat con stato espanso/collassato
function ChatBlockItem({
  block,
  index,
  provider,
  onCopy,
  copiedKey,
  onPreviewPath,
}: {
  block: ChatBlock;
  index: number;
  provider: string;
  onCopy: (key: string, text: string) => void;
  copiedKey: string;
  onPreviewPath: PreviewPathHandler;
}) {
  const blockKey = `${index}-${block.content.slice(0, 20)}`;
  const isCollapsible = Boolean(block.collapsed ?? (block.content.length > BLOCK_COLLAPSE_THRESHOLD));
  const [isExpanded, setIsExpanded] = useState(false);
  // Un blocco collassato mostra solo ~120px (CSS, vedi styles.css) prima della
  // dissolvenza: passare comunque l'intero contenuto al parser markdown è
  // lavoro sincrono sprecato che scala con la dimensione del blocco, non con
  // quella visibile. Per contenuto grosso (es. tool output non troncato) può
  // bloccare il thread principale prima ancora che l'utente scelga di
  // espandere. Si parsa per intero solo quando serve davvero.
  const displayContent = isCollapsible && !isExpanded
    ? block.content.slice(0, BLOCK_COLLAPSE_THRESHOLD)
    : block.content;

  return (
    <article className={`chat-block ${block.kind} ${isCollapsible && !isExpanded ? "collapsed" : ""}`} key={blockKey}>
      <div className="chat-block-header">
        <small>
          {block.kind === "user"
            ? "Tu"
            : block.kind === "agent"
              ? provider
              : "Attività"}
        </small>
        {block.kind === "agent" && (
          <button
            type="button"
            className="chat-copy"
            onClick={() => void onCopy(blockKey, block.content)}
          >
            {copiedKey === blockKey ? "Copiato" : "Copia pulito"}
          </button>
        )}
        {isCollapsible && (
          <button
            type="button"
            className="chat-toggle"
            onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
            aria-expanded={isExpanded}
            aria-label={isExpanded ? "Comprimi" : "Espandi"}
          >
            {isExpanded ? "▲ Mostra meno" : "▼ Mostra tutto"}
          </button>
        )}
      </div>
      {block.kind === "activity" ? (
        <pre><PreviewPathText text={displayContent} onPreviewPath={onPreviewPath} /></pre>
      ) : (
        <div className="chat-markdown">
          <MarkdownContent content={displayContent} onPreviewPath={onPreviewPath} />
        </div>
      )}
    </article>
  );
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

type EntryCategory = "all" | "folders" | "code" | "media" | "docs";

const CODE_EXTENSIONS = new Set([
  ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".json", ".css", ".html", ".sh",
  ".bash", ".zsh", ".yaml", ".yml", ".toml", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
  ".sql", ".env", ".ini", ".conf", ".xml", ".lua", ".rb", ".php", ".java", ".kt"
]);

const MEDIA_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico",
  ".mp4", ".webm", ".mov", ".m4v", ".mp3", ".m4a", ".wav", ".ogg"
]);

const DOCS_EXTENSIONS = new Set([
  ".md", ".markdown", ".txt", ".pdf", ".rst", ".doc", ".docx", ".rtf", ".csv", ".log"
]);

function getEntryCategory(entry: DirectoryEntry): "folders" | "code" | "media" | "docs" | "other" {
  if (entry.type === "dir") return "folders";
  const ext = entry.name.includes(".") ? "." + entry.name.split(".").pop()!.toLowerCase() : "";
  if (CODE_EXTENSIONS.has(ext)) return "code";
  if (MEDIA_EXTENSIONS.has(ext)) return "media";
  if (DOCS_EXTENSIONS.has(ext)) return "docs";
  return "other";
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}g`;
}

// Formato relativo compatto per l'ultimo aggiornamento di una sessione
// (es. "3 min fa" / "3 min ago"). Nessun tooltip con la data assoluta:
// scelta esplicita, solo il testo relativo.
function formatRelativeActivity(value: string, language: Language): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const diffSeconds = (Date.now() - timestamp) / 1000;
  const rtf = new Intl.RelativeTimeFormat(language, { numeric: "auto", style: "short" });
  if (diffSeconds < 60) return rtf.format(0, "second");
  if (diffSeconds < 3600) return rtf.format(-Math.round(diffSeconds / 60), "minute");
  if (diffSeconds < 86400) return rtf.format(-Math.round(diffSeconds / 3600), "hour");
  return rtf.format(-Math.round(diffSeconds / 86400), "day");
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

const DOWNLOADABLE_FILE = /\.(?:bmp|docx?|gif|jpe?g|m4a|mp3|pdf|png|tiff?|webp)$/i;

function isDownloadable(name: string): boolean {
  return DOWNLOADABLE_FILE.test(name);
}

// L'estensione qui decide solo *quale elemento montare*: il tipo vero lo stabilisce
// il backend leggendo i byte, e rifiuta con 400 tutto cio' che non e' un media ammesso.
const PREVIEWABLE_VIDEO = /\.mp4$/i;
const PREVIEWABLE_IMAGE = /\.(?:jpe?g|png|webp)$/i;
const PREVIEWABLE_AUDIO = /\.(?:m4a|mp3)$/i;
const PREVIEWABLE_MARKDOWN = /\.(?:md|markdown)$/i;

type PreviewKind = "image" | "video" | "audio" | "text" | "markdown";

type PreviewContent = {
  content: string;
  truncated: boolean;
};

type PreviewSource = {
  kind: PreviewKind;
  name: string;
  modifiedAt: string | null;
  url: string | null;
  fetchContent: () => Promise<PreviewContent>;
  onBack: () => void;
  eyebrow?: string;
};

function previewKindFor(name: string, mediaType?: string): PreviewKind {
  if (mediaType === "text/markdown" || PREVIEWABLE_MARKDOWN.test(name)) return "markdown";
  if (mediaType === "video/mp4" || PREVIEWABLE_VIDEO.test(name)) return "video";
  if (mediaType?.startsWith("image/") || PREVIEWABLE_IMAGE.test(name)) return "image";
  if ((mediaType === "audio/mpeg" || mediaType === "audio/mp4") || PREVIEWABLE_AUDIO.test(name)) return "audio";
  return "text";
}

type BrowserSort = "name-asc" | "name-desc" | "date-desc" | "date-asc";

function compareNullableDates(a: string | null, b: string | null, ascending: boolean): number {
  const aTime = a ? new Date(a).getTime() : 0;
  const bTime = b ? new Date(b).getTime() : 0;
  return ascending ? aTime - bTime : bTime - aTime;
}

function sortDirectoryEntries(entries: DirectoryEntry[], sort: BrowserSort): DirectoryEntry[] {
  return [...entries].sort((a, b) => {
    // Le cartelle restano in testa, come in un file manager, qualunque sia
    // l'ordinamento scelto per le voci dello stesso tipo.
    if (a.type !== b.type) {
      if (a.type === "dir") return -1;
      if (b.type === "dir") return 1;
    }
    if (sort === "name-asc") return a.name.localeCompare(b.name);
    if (sort === "name-desc") return b.name.localeCompare(a.name);
    const dateOrder = compareNullableDates(a.modified_at, b.modified_at, sort === "date-asc");
    return dateOrder || a.name.localeCompare(b.name);
  });
}

function isPreviewableDirectoryEntry(entry: DirectoryEntry): boolean {
  if (entry.type !== "file") return false;
  return previewKindFor(entry.name) !== "text" || !isDownloadable(entry.name);
}

const CODE_FILE_EXTENSION = /\.(?:py|ts|tsx|js|jsx|json|sh|bash|zsh|yaml|yml|toml|css|scss|html|rs|go|c|cpp|h|hpp|sql|env|dockerfile|makefile)$/i;
const ARCHIVE_FILE_EXTENSION = /\.(?:zip|tar|gz|tgz|bz2|xz|7z|rar)$/i;

function FileTypeIcon({ type, name, mediaType }: { type: "dir" | "file" | "other"; name: string; mediaType?: string }) {
  if (type === "dir") {
    return (
      <svg className="directory-icon dir" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      </svg>
    );
  }
  if (type === "other") {
    return (
      <svg className="directory-icon other" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
    );
  }
  const kind = previewKindFor(name, mediaType);
  if (kind === "image") {
    return (
      <svg className="directory-icon media" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <polyline points="21 15 16 10 5 21" />
      </svg>
    );
  }
  if (kind === "video") {
    return (
      <svg className="directory-icon media" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <polygon points="23 7 16 12 23 17 23 7" />
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
      </svg>
    );
  }
  if (kind === "audio") {
    return (
      <svg className="directory-icon audio" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
    );
  }
  if (kind === "markdown" || CODE_FILE_EXTENSION.test(name)) {
    return (
      <svg className="directory-icon code" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    );
  }
  if (ARCHIVE_FILE_EXTENSION.test(name)) {
    return (
      <svg className="directory-icon archive" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <polyline points="21 8 21 21 3 21 3 8" />
        <rect x="1" y="3" width="22" height="5" />
        <line x1="10" y1="12" x2="14" y2="12" />
      </svg>
    );
  }
  return (
    <svg className="directory-icon file" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  );
}

function PathBreadcrumbs({
  path,
  root,
  onNavigate,
}: {
  path?: string;
  root?: string;
  onNavigate: (targetPath: string) => void;
}) {
  const effectiveRoot = root || "/";
  const effectivePath = path || effectiveRoot;

  const crumbs: Array<{ label: string; path: string }> = [
    { label: "root", path: effectiveRoot }
  ];

  if (effectivePath.startsWith(effectiveRoot) && effectivePath.length > effectiveRoot.length) {
    const relative = effectivePath.slice(effectiveRoot.length).replace(/^\/+/, "");
    const parts = relative.split("/").filter(Boolean);
    let acc = effectiveRoot.replace(/\/+$/, "");
    for (const part of parts) {
      acc += "/" + part;
      crumbs.push({ label: part, path: acc });
    }
  } else if (!effectivePath.startsWith(effectiveRoot) && effectivePath !== effectiveRoot) {
    const parts = effectivePath.split("/").filter(Boolean);
    let acc = "";
    for (const part of parts) {
      acc += "/" + part;
      crumbs.push({ label: part, path: acc });
    }
  }

  return (
    <nav className="directory-breadcrumbs" aria-label="Percorso cartelle">
      {crumbs.map((crumb, idx) => {
        const isCurrent = crumb.path === effectivePath;
        const isRoot = crumb.path === effectiveRoot;
        return (
          <span key={crumb.path + "-" + idx} className="breadcrumb-segment">
            {idx > 0 && <span className="breadcrumb-sep" aria-hidden="true">/</span>}
            {isCurrent ? (
              <span className={`breadcrumb-item active${isRoot ? " root" : ""}`} aria-current="location">
                {isRoot ? "⌂ root" : crumb.label}
              </span>
            ) : (
              <button
                type="button"
                className={`breadcrumb-item link${isRoot ? " root" : ""}`}
                onClick={() => onNavigate(crumb.path)}
                title={crumb.path}
              >
                {isRoot ? "⌂ root" : crumb.label}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function parseArtifactBreadcrumbs(currentPath: string): Array<{ name: string; path: string }> {
  const crumbs: Array<{ name: string; path: string }> = [
    { name: "Artefatti", path: "" }
  ];
  if (!currentPath) return crumbs;
  const parts = currentPath.split("/").filter(Boolean);
  let acc = "";
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part;
    crumbs.push({ name: part, path: acc });
  }
  return crumbs;
}

// Adapter di directory: il tipo si decide dall'estensione perche' la directory
// non espone un media type; i tag media caricano da soli e il flag `truncated`
// arriva dalla risposta di `/file`.
type PreviewSourceInput = Omit<PreviewSource, "onBack">;

function filePreviewSource(
  sessionId: string,
  path: string,
  modifiedAt: string | null,
  mediaType?: string,
): PreviewSourceInput {
  const kind = previewKindFor(path, mediaType);
  const isMedia = kind === "video" || kind === "image" || kind === "audio";
  return {
    kind,
    name: path,
    modifiedAt,
    url: isMedia ? filePreviewUrl(sessionId, path) : null,
    fetchContent: () => fetchFile(sessionId, path).then((file) => ({ content: file.content, truncated: file.truncated })),
    eyebrow: translations[readLanguage()].readOnlyFile,
  };
}

function artifactPreviewSource(sessionId: string, item: Artifact): PreviewSourceInput {
  const kind = previewKindFor(item.name, item.media_type);
  const isMedia = kind === "video" || kind === "image" || kind === "audio";
  return {
    kind,
    name: item.name,
    modifiedAt: item.modified_at,
    url: isMedia ? artifactDownloadUrl(sessionId, item.name) : null,
    fetchContent: () => fetchArtifactContent(sessionId, item.name).then((text) => ({ content: text, truncated: false })),
  };
}

type PreviewNavigation = {
  index: number;
  total: number;
  onPrevious: (() => void) | null;
  onNext: (() => void) | null;
};

// Window manager delle anteprime: solleva lo stato "quale file è aperto" da
// tre useState locali (DirectoryModal.openFile, ArtifactsModal.previewItem,
// Console.blockPreview) a un unico Context montato in App(). Così una
// finestra di anteprima sopravvive allo smontaggio del componente che l'ha
// aperta (chiudere il browser directory, tornare alla dashboard, cambiare
// sessione con Console rimontata via key={session.id}). Vedi
// docs/adr/015-preview-window-manager.md.
type PreviewWindowState = {
  id: string;
  resolveSource: (path: string) => PreviewSourceInput;
  siblings: string[];
  currentPath: string;
  fullscreen: boolean;
};

type PreviewWindowsContextValue = {
  hasActivePreviewWindow: boolean;
  openPreviewWindow: (init: {
    resolveSource: (path: string) => PreviewSourceInput;
    siblings: string[];
    initialPath: string;
  }) => void;
  closePreviewWindow: (id: string) => void;
  toggleWindowFullscreen: (id: string) => void;
  navigateWindow: (id: string, direction: -1 | 1) => void;
};

const PreviewWindowsContext = createContext<PreviewWindowsContextValue | null>(null);

function usePreviewWindows(): PreviewWindowsContextValue {
  const ctx = useContext(PreviewWindowsContext);
  if (!ctx) throw new Error("usePreviewWindows usato fuori da PreviewWindowsProvider");
  return ctx;
}

let previewWindowSeq = 0;

function PreviewWindowsProvider({ children, active }: { children: ReactNode; active: boolean }) {
  const [windows, setWindows] = useState<PreviewWindowState[]>([]);

  useEffect(() => {
    if (!active) setWindows([]);
  }, [active]);

  const openPreviewWindow = useCallback((init: {
    resolveSource: (path: string) => PreviewSourceInput;
    siblings: string[];
    initialPath: string;
  }) => {
    previewWindowSeq += 1;
    const id = `preview-${previewWindowSeq}`;
    setWindows((current) => [...current, {
      id,
      resolveSource: init.resolveSource,
      siblings: init.siblings,
      currentPath: init.initialPath,
      fullscreen: false,
    }]);
  }, []);

  const closePreviewWindow = useCallback((id: string) => {
    setWindows((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const toggleWindowFullscreen = useCallback((id: string) => {
    setWindows((current) => current.map((entry) => (
      entry.id === id ? { ...entry, fullscreen: !entry.fullscreen } : entry
    )));
  }, []);

  const navigateWindow = useCallback((id: string, direction: -1 | 1) => {
    setWindows((current) => current.map((entry) => {
      if (entry.id !== id) return entry;
      const index = entry.siblings.indexOf(entry.currentPath);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= entry.siblings.length) return entry;
      return { ...entry, currentPath: entry.siblings[nextIndex] };
    }));
  }, []);

  const activeWindow = windows.length > 0 ? windows[windows.length - 1] : null;

  const value = useMemo<PreviewWindowsContextValue>(() => ({
    hasActivePreviewWindow: activeWindow !== null,
    openPreviewWindow,
    closePreviewWindow,
    toggleWindowFullscreen,
    navigateWindow,
  }), [activeWindow, openPreviewWindow, closePreviewWindow, toggleWindowFullscreen, navigateWindow]);

  return (
    <PreviewWindowsContext.Provider value={value}>
      {children}
      {activeWindow && <PreviewWindowHost key={activeWindow.id} entry={activeWindow} />}
    </PreviewWindowsContext.Provider>
  );
}

function PreviewWindowHost({ entry }: { entry: PreviewWindowState }) {
  const { closePreviewWindow, toggleWindowFullscreen, navigateWindow } = usePreviewWindows();
  const index = entry.siblings.indexOf(entry.currentPath);
  const close = useCallback(() => closePreviewWindow(entry.id), [closePreviewWindow, entry.id]);
  const source: PreviewSource = { ...entry.resolveSource(entry.currentPath), onBack: close };
  const navigation: PreviewNavigation = {
    index,
    total: entry.siblings.length,
    onPrevious: index > 0 ? () => navigateWindow(entry.id, -1) : null,
    onNext: index >= 0 && index < entry.siblings.length - 1 ? () => navigateWindow(entry.id, 1) : null,
  };

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [close]);

  return (
    <div
      className={`modal-backdrop${entry.fullscreen ? " modal-backdrop-fullscreen" : ""}`}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <section
        className={`help-modal directory-modal${entry.fullscreen ? " help-modal-fullscreen" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={translations[readLanguage()].filePreview}
      >
        <PreviewModal
          source={source}
          navigation={navigation}
          fullscreen={entry.fullscreen}
          onToggleFullscreen={() => toggleWindowFullscreen(entry.id)}
        />
      </section>
    </div>
  );
}

function PreviewModal({
  source,
  navigation,
  fullscreen,
  onToggleFullscreen,
}: {
  source: PreviewSource;
  navigation: PreviewNavigation;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pathCopied, setPathCopied] = useState(false);
  const [viewMode, setViewMode] = useState<"rendered" | "source">("rendered");
  const [showLineNumbers, setShowLineNumbers] = useState(false);
  const t = translations[readLanguage()];
  const isText = source.kind === "text" || source.kind === "markdown";
  const lastSlash = source.name.lastIndexOf("/");
  const fileName = lastSlash >= 0 ? source.name.slice(lastSlash + 1) : source.name;
  const filePath = lastSlash >= 0 ? source.name.slice(0, lastSlash) : "";

  // Il source e' ricreato a ogni render del padre (adapter costruiti inline),
  // quindi l'effetto non deve dipenderne per identita', altrimenti ogni
  // ri-render (poll agent-status, snapshot WebSocket) ritriggerebbe il fetch
  // e il contenuto verrebbe smontato/rimontato, perdendo lo scroll. Ci si
  // ancora al file aperto e si legge la callback corrente tramite ref.
  const sourceRef = useRef(source);
  sourceRef.current = source;

  useEffect(() => {
    setViewMode("rendered");
    setShowLineNumbers(false);
  }, [source.name]);

  useEffect(() => {
    if (!isText) {
      setContent(null);
      setError("");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    sourceRef.current.fetchContent()
      .then((value) => {
        if (cancelled) return;
        setContent(value.content);
        setTruncated(value.truncated);
      })
      .catch((value) => {
        if (!cancelled) {
          setContent(null);
          setError(errorMessage(value));
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isText, source.kind, source.name]);

  async function copy() {
    if (!content) return;
    const ok = await copyToClipboard(content);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  }

  async function copyPath() {
    if (!await copyToClipboard(source.name)) return;
    setPathCopied(true);
    window.setTimeout(() => setPathCopied(false), 1500);
  }

  return (
    <>
      <header>
        <div>
          <span className="eyebrow">{source.eyebrow ?? t.preview}</span>
          <div className="preview-path-row">
            <h2 className="preview-file-name" title={source.name}>{fileName}</h2>
            <button
              type="button"
              className="preview-path-copy"
              onClick={() => void copyPath()}
              aria-label={`${t.copyPath}: ${source.name}`}
            >
              {pathCopied ? t.copied : t.copyPath}
            </button>
          </div>
          {filePath && <p className="preview-file-dir" title={filePath}>{filePath}</p>}
          {source.modifiedAt && (
            <p className="preview-modified">
              {t.lastModified}: <time dateTime={source.modifiedAt}>{formatDate(source.modifiedAt)}</time>
            </p>
          )}
        </div>
        <div className="modal-header-actions">
          <button
            type="button"
            className="modal-fullscreen"
            onClick={onToggleFullscreen}
            aria-pressed={fullscreen}
            aria-label={fullscreen ? t.exitFullscreen : t.enterFullscreen}
          >
            {fullscreen ? "⤡" : "⤢"}
          </button>
          <button className="modal-close" onClick={source.onBack} aria-label={t.backToList}>‹</button>
        </div>
      </header>
      <div className="preview-toolbar">
        <nav className="preview-navigation" aria-label={t.previewNavigation}>
          <button
            type="button"
            disabled={navigation.onPrevious === null}
            onClick={() => navigation.onPrevious?.()}
            title={t.previousPreview}
            aria-label={t.previousPreview}
          >
            ‹
          </button>
          <span aria-live="polite">{navigation.index + 1} / {navigation.total}</span>
          <button
            type="button"
            disabled={navigation.onNext === null}
            onClick={() => navigation.onNext?.()}
            title={t.nextPreview}
            aria-label={t.nextPreview}
          >
            ›
          </button>
        </nav>
        {source.kind === "markdown" && (
          <div className="preview-toggle-group">
            <button
              type="button"
              className={`preview-toggle-btn${viewMode === "rendered" ? " active" : ""}`}
              onClick={() => setViewMode("rendered")}
            >
              👁️ {t.renderedView}
            </button>
            <button
              type="button"
              className={`preview-toggle-btn${viewMode === "source" ? " active" : ""}`}
              onClick={() => setViewMode("source")}
            >
              💻 {t.sourceView}
            </button>
          </div>
        )}
        {(source.kind === "text" || (source.kind === "markdown" && viewMode === "source")) && (
          <button
            type="button"
            className={`preview-option-btn${showLineNumbers ? " active" : ""}`}
            onClick={() => setShowLineNumbers((v) => !v)}
            title={t.lineNumbersToggle}
            aria-pressed={showLineNumbers}
          >
            # {t.lineNumbersToggle}
          </button>
        )}
        {isText && !loading && !error && content && (
          <button type="button" className="preview-copy-btn" onClick={() => void copy()}>
            {copied ? (
              <>
                <svg className="action-icon-sm copy-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span>{t.copied}</span>
              </>
            ) : (
              <>
                <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                <span>{t.copyContent}</span>
              </>
            )}
          </button>
        )}
      </div>
      {source.kind === "video" && (
        <video className={`file-media${fullscreen ? " is-fullscreen" : ""}`} src={source.url ?? undefined} controls playsInline preload="metadata" />
      )}
      {source.kind === "image" && (
        <div className={`file-media-wrapper${fullscreen ? " is-fullscreen" : ""}`}>
          <img
            key={source.url}
            className={`file-media preview-fade-in${fullscreen ? " is-fullscreen" : ""}`}
            src={source.url ?? undefined}
            alt={source.name}
          />
        </div>
      )}
      {source.kind === "audio" && (
        <audio className="file-media" src={source.url ?? undefined} controls preload="metadata" />
      )}
      {isText && (
        <div className={`preview-viewport${fullscreen ? " is-fullscreen" : ""}${loading ? " is-loading" : ""}`}>
          {loading && content === null && (
            <div className="preview-skeleton-loader" aria-busy="true">
              <div className="skeleton-line" style={{ width: "85%" }} />
              <div className="skeleton-line" style={{ width: "65%" }} />
              <div className="skeleton-line" style={{ width: "92%" }} />
              <div className="skeleton-line" style={{ width: "45%" }} />
              <div className="skeleton-line" style={{ width: "78%" }} />
              <div className="skeleton-line" style={{ width: "60%" }} />
              <div className="skeleton-line" style={{ width: "80%" }} />
            </div>
          )}
          {loading && content !== null && (
            <div className="preview-loading-bar" aria-busy="true" />
          )}
          {error && <p className="error">{error}</p>}
          {!error && content !== null && (
            <>
              {source.kind === "markdown" && viewMode === "rendered" ? (
                content ? (
                  <div className={`chat-markdown markdown-preview preview-fade-in${fullscreen ? " is-fullscreen" : ""}`}>
                    <MarkdownContent content={content} />
                  </div>
                ) : (
                  <p className="empty">{t.emptyFile}</p>
                )
              ) : (
                <pre className={`file-preview preview-fade-in${fullscreen ? " is-fullscreen" : ""}${showLineNumbers ? " with-lines" : ""}`}>
                  {showLineNumbers && content ? (
                    content.split("\n").map((line, idx) => (
                      <div key={idx} className="code-line-row">
                        <span className="code-line-num" aria-hidden="true">{idx + 1}</span>
                        <span className="code-line-text">{line || "\n"}</span>
                      </div>
                    ))
                  ) : (
                    content || t.emptyFile
                  )}
                </pre>
              )}
              {truncated && <small>{t.truncatedPreview}</small>}
            </>
          )}
        </div>
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
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState("");
  const [directoryQuery, setDirectoryQuery] = useState("");
  const [directorySort, setDirectorySort] = useState<BrowserSort>("name-asc");
  const [categoryFilter, setCategoryFilter] = useState<EntryCategory>("all");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLElement>(null);
  const { openPreviewWindow, hasActivePreviewWindow } = usePreviewWindows();

  const dirStats = useMemo(() => {
    if (!listing) return null;
    let folders = 0;
    let files = 0;
    let totalBytes = 0;
    for (const e of listing.entries) {
      if (e.type === "dir") {
        folders++;
      } else {
        files++;
        totalBytes += e.size ?? 0;
      }
    }
    return { folders, files, totalBytes };
  }, [listing]);

  useEffect(() => {
    fetchConfig().then(setAppConfig).catch(() => {});
  }, []);

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
      if (event.key !== "Escape" || hasActivePreviewWindow) return;
      onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, hasActivePreviewWindow]);

  const [copiedKey, setCopiedKey] = useState("");

  async function copy(entry: DirectoryEntry) {
    return copyName(entry);
  }

  async function copyName(entry: DirectoryEntry) {
    const ok = await copyToClipboard(shellQuote(entry.name));
    if (ok) {
      setError("");
      setCopiedKey(entry.name + "-name");
      setCopiedName(entry.name);
      window.setTimeout(() => {
        setCopiedKey("");
        setCopiedName("");
      }, 1500);
    } else {
      setError("Copia negli appunti non riuscita.");
    }
  }

  async function copyFullPath(entry: DirectoryEntry) {
    if (!listing) return;
    const fullPath = joinPath(listing.path, entry.name);
    const ok = await copyToClipboard(fullPath);
    if (ok) {
      setError("");
      setCopiedKey(entry.name + "-path");
      window.setTimeout(() => setCopiedKey(""), 1500);
    } else {
      setError("Copia negli appunti non riuscita.");
    }
  }

  async function copyHeaderPath() {
    const path = listing?.path ?? currentPath;
    if (!path) return;
    const ok = await copyToClipboard(path);
    if (ok) {
      setCopiedKey("header-path");
      window.setTimeout(() => setCopiedKey(""), 1500);
    }
  }

  async function copyHeaderName() {
    const path = listing?.path ?? currentPath;
    if (!path) return;
    const parts = path.split("/").filter(Boolean);
    const folderName = parts.length > 0 ? parts[parts.length - 1] : "/";
    const ok = await copyToClipboard(folderName);
    if (ok) {
      setCopiedKey("header-name");
      window.setTimeout(() => setCopiedKey(""), 1500);
    }
  }

  function openEntry(entry: DirectoryEntry) {
    if (!listing) return;
    const fullPath = joinPath(listing.path, entry.name);
    if (entry.type === "dir") {
      setCurrentPath(fullPath);
      return;
    }
    // I file scaricabili non anteprima (gif, pdf, docx, …) si scaricano col
    // browser; testo, markdown e media si aprono in anteprima.
    if (isPreviewableDirectoryEntry(entry)) {
      openPreviewWindow({
        resolveSource: (path) => {
          const match = sortedDirectoryEntries.find((candidate) => joinPath(listing!.path, candidate.name) === path);
          return filePreviewSource(sessionId, path, match?.modified_at ?? null);
        },
        siblings: previewPaths,
        initialPath: fullPath,
      });
    } else if (entry.type === "file") {
      downloadEntry(entry);
    }
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

  const defaultAllowedExtensions = [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".ico",
    ".tiff",
    ".avif",
    ".heic",
    ".pdf",
    ".md",
    ".mp3",
  ];
  const allowedExtensions = appConfig?.upload_allowed_extensions || defaultAllowedExtensions;
  const maxUploadBytes = appConfig?.max_upload_bytes || 10 * 1024 * 1024;
  const acceptAttr = allowedExtensions.join(",");
  const normalizedDirectoryQuery = directoryQuery.trim().toLocaleLowerCase();
  const sortedDirectoryEntries = listing ? sortDirectoryEntries(listing.entries, directorySort) : [];
  const displayedEntries = sortedDirectoryEntries.filter((entry) => {
    if (categoryFilter !== "all") {
      const cat = getEntryCategory(entry);
      if (categoryFilter === "folders" && cat !== "folders") return false;
      if (categoryFilter === "code" && cat !== "code") return false;
      if (categoryFilter === "media" && cat !== "media") return false;
      if (categoryFilter === "docs" && cat !== "docs") return false;
    }
    if (!normalizedDirectoryQuery) return true;
    return entry.name.toLocaleLowerCase().includes(normalizedDirectoryQuery);
  });
  const previewPaths = listing
    ? sortedDirectoryEntries
      .filter(isPreviewableDirectoryEntry)
      .map((entry) => joinPath(listing.path, entry.name))
    : [];

  async function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";

    const ext = file.name.includes(".") ? "." + file.name.split(".").pop()!.toLowerCase() : "";
    const stem = ext ? file.name.slice(0, -ext.length) : file.name;
    const isAllowed = allowedExtensions.some(
      (allowed) => allowed.toLowerCase() === ext
    );

    if (!isAllowed) {
      setError(translations[readLanguage()].invalidFileExtension);
      return;
    }

    if (!stem || !/^[\p{L}\p{N}_]+$/u.test(stem)) {
      setError(translations[readLanguage()].invalidFilenamePattern);
      return;
    }

    if (file.size > maxUploadBytes) {
      setError(translations[readLanguage()].fileExceedsMaxSize);
      return;
    }

    setUploading(true);
    setError("");
    setUploadNotice("");

    try {
      await uploadDirectoryFile(sessionId, listing?.path, file);
      setUploadNotice(translations[readLanguage()].fileUploaded);
      window.setTimeout(() => setUploadNotice(""), 3000);
      const updated = await fetchDirectory(sessionId, listing?.path);
      setListing(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget) return;
        onClose();
      }}
    >
      <section
        ref={modalRef}
        className="help-modal directory-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="directory-title"
      >
        <>
            <header>
              <div className="directory-header-main">
                <span className="eyebrow">{translations[readLanguage()].directoryContent}</span>
                <div className="directory-header-path-row">
                  <h2 id="directory-title" className="directory-path" title={listing?.path ?? currentPath}>
                    {listing?.path ?? currentPath ?? "…"}
                  </h2>
                  <div className="directory-header-actions">
                    <button
                      type="button"
                      className="directory-icon-btn directory-header-btn"
                      title={copiedKey === "header-path" ? translations[readLanguage()].copied : translations[readLanguage()].copyPath}
                      aria-label={`${translations[readLanguage()].copyPath}: ${listing?.path ?? currentPath}`}
                      onClick={() => void copyHeaderPath()}
                    >
                      {copiedKey === "header-path" ? (
                        <svg className="action-icon-sm copy-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                        </svg>
                      )}
                    </button>
                    <button
                      type="button"
                      className="directory-icon-btn directory-header-btn"
                      title={copiedKey === "header-name" ? translations[readLanguage()].copied : translations[readLanguage()].copyName}
                      aria-label={`${translations[readLanguage()].copyName}: ${listing?.path ?? currentPath}`}
                      onClick={() => void copyHeaderName()}
                    >
                      {copiedKey === "header-name" ? (
                        <svg className="action-icon-sm copy-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                        </svg>
                      )}
                    </button>
                  </div>
                </div>
              </div>
              <button className="modal-close" onClick={onClose} aria-label={translations[readLanguage()].close}>×</button>
            </header>
            {(listing || error) && (
              <div className="directory-nav-bar">
                <div className="directory-nav-actions">
                  <button
                    type="button"
                    className="directory-nav-btn"
                    disabled={!listing?.parent || uploading}
                    onClick={() => {
                      if (listing?.parent) {
                        setError("");
                        setCurrentPath(listing.parent);
                      }
                    }}
                    title={translations[readLanguage()].upDirectory}
                    aria-label={translations[readLanguage()].upDirectory}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <line x1="12" y1="19" x2="12" y2="5" />
                      <polyline points="5 12 12 5 19 12" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="directory-nav-btn"
                    disabled={uploading || (currentPath === undefined && !error && listing?.path === listing?.root)}
                    onClick={() => {
                      setError("");
                      setCurrentPath(undefined);
                    }}
                    title={translations[readLanguage()].rootFolder}
                    aria-label={translations[readLanguage()].rootFolder}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                      <polyline points="9 22 9 12 15 12 15 22" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="directory-nav-btn upload-btn"
                    disabled={loading || uploading || Boolean(error)}
                    onClick={() => fileInputRef.current?.click()}
                    title={translations[readLanguage()].uploadFile}
                    aria-label={translations[readLanguage()].uploadFile}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span>{uploading ? translations[readLanguage()].uploadingFile : translations[readLanguage()].uploadFile}</span>
                  </button>
                  <input
                    type="file"
                    ref={fileInputRef}
                    style={{ display: "none" }}
                    accept={acceptAttr}
                    onChange={(e) => void handleFileSelected(e)}
                  />
                </div>
                <PathBreadcrumbs
                  path={listing?.path ?? currentPath}
                  root={listing?.root}
                  onNavigate={(target) => {
                    if (!uploading) {
                      setError("");
                      setCurrentPath(target === listing?.root ? undefined : target);
                    }
                  }}
                />
              </div>
            )}
            {uploadNotice && <p className="directory-upload-notice">{uploadNotice}</p>}
            {dirStats && (
              <div className="directory-summary-bar">
                <span>📁 {dirStats.folders} {dirStats.folders === 1 ? "cartella" : "cartelle"}</span>
                <span className="summary-dot">·</span>
                <span>📄 {dirStats.files} {dirStats.files === 1 ? "file" : "file"}</span>
                {dirStats.totalBytes > 0 && (
                  <>
                    <span className="summary-dot">·</span>
                    <span>{formatSize(dirStats.totalBytes)}</span>
                  </>
                )}
              </div>
            )}
            {listing && listing.entries.length > 0 && (
              <>
                <div className="artifact-toolbar">
                  <input
                    type="search"
                    className="artifact-search"
                    placeholder={translations[readLanguage()].directorySearchPlaceholder}
                    aria-label={translations[readLanguage()].directorySearchPlaceholder}
                    value={directoryQuery}
                    onChange={(event) => setDirectoryQuery(event.target.value)}
                  />
                  <select
                    className="artifact-sort"
                    aria-label={translations[readLanguage()].artifactSortLabel}
                    value={directorySort}
                    onChange={(event) => setDirectorySort(event.target.value as BrowserSort)}
                  >
                    <option value="name-asc">{translations[readLanguage()].artifactSortNameAsc}</option>
                    <option value="name-desc">{translations[readLanguage()].artifactSortNameDesc}</option>
                    <option value="date-desc">{translations[readLanguage()].artifactSortDateDesc}</option>
                    <option value="date-asc">{translations[readLanguage()].artifactSortDateAsc}</option>
                  </select>
                </div>
                <div className="category-chips" role="group" aria-label="Filtri categoria">
                  <button
                    type="button"
                    className={`category-chip${categoryFilter === "all" ? " active" : ""}`}
                    onClick={() => setCategoryFilter("all")}
                  >
                    {translations[readLanguage()].allCategories}
                  </button>
                  <button
                    type="button"
                    className={`category-chip${categoryFilter === "folders" ? " active" : ""}`}
                    onClick={() => setCategoryFilter("folders")}
                  >
                    📁 {translations[readLanguage()].filterFolders}
                  </button>
                  <button
                    type="button"
                    className={`category-chip${categoryFilter === "code" ? " active" : ""}`}
                    onClick={() => setCategoryFilter("code")}
                  >
                    💻 {translations[readLanguage()].filterCode}
                  </button>
                  <button
                    type="button"
                    className={`category-chip${categoryFilter === "media" ? " active" : ""}`}
                    onClick={() => setCategoryFilter("media")}
                  >
                    🖼️ {translations[readLanguage()].filterMedia}
                  </button>
                  <button
                    type="button"
                    className={`category-chip${categoryFilter === "docs" ? " active" : ""}`}
                    onClick={() => setCategoryFilter("docs")}
                  >
                    📄 {translations[readLanguage()].filterDocs}
                  </button>
                </div>
              </>
            )}
            {loading && <p className="empty">{translations[readLanguage()].loading}</p>}
            {error && <p className="error">{error}</p>}
            {!loading && !error && listing && (
              <>
                <ul className="directory-list">
                  {displayedEntries.map((entry) => (
                    <li key={entry.name} className="directory-entry">
                      <button
                        type="button"
                        className="directory-open"
                        disabled={entry.type === "other"}
                        onClick={() => openEntry(entry)}
                      >
                        <FileTypeIcon type={entry.type} name={entry.name} />
                        <span className="directory-name" title={entry.name}>{entry.name}</span>
                        <span className="directory-meta">{formatSize(entry.size)} · {formatDate(entry.modified_at)}</span>
                      </button>
                      <button
                        type="button"
                        className="directory-icon-btn"
                        title={copiedKey === entry.name + "-path" ? translations[readLanguage()].copied : translations[readLanguage()].copyPath}
                        aria-label={`${translations[readLanguage()].copyPath}: ${entry.name}`}
                        onClick={() => void copyFullPath(entry)}
                      >
                        {copiedKey === entry.name + "-path" ? (
                          <svg className="action-icon-sm copy-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        ) : (
                          <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                          </svg>
                        )}
                      </button>
                      <button
                        type="button"
                        className="directory-copy directory-icon-btn"
                        title={copiedKey === entry.name + "-name" ? translations[readLanguage()].copied : translations[readLanguage()].copyName}
                        aria-label={`${translations[readLanguage()].copyName}: ${entry.name}`}
                        onClick={() => void copyName(entry)}
                      >
                        {copiedKey === entry.name + "-name" ? (
                          <svg className="action-icon-sm copy-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        ) : (
                          <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                          </svg>
                        )}
                      </button>
                      {entry.type === "file" && isDownloadable(entry.name) && (
                        <button
                          type="button"
                          className="directory-download directory-icon-btn"
                          title={translations[readLanguage()].download}
                          aria-label={`${translations[readLanguage()].download}: ${entry.name}`}
                          onClick={() => downloadEntry(entry)}
                        >
                          <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="7 10 12 15 17 10" />
                            <line x1="12" y1="15" x2="12" y2="3" />
                          </svg>
                        </button>
                      )}
                    </li>
                  ))}
                  {displayedEntries.length === 0 && (
                    <li className="empty">
                      {listing.entries.length === 0
                        ? translations[readLanguage()].emptyDirectory
                        : translations[readLanguage()].noDirectoryMatch}
                    </li>
                  )}
                </ul>
                {listing.truncated && <small>Elenco troncato alle prime 2000 voci.</small>}
              </>
            )}
        </>
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

function isPreviewableArtifact(name: string, mediaType: string): boolean {
  return previewKindFor(name, mediaType) !== "text" || PREVIEWABLE_TEXT_TYPES.has(mediaType);
}

type ArtifactSort = BrowserSort;

function sortArtifacts(list: Artifact[], sort: ArtifactSort): Artifact[] {
  const sorted = [...list];
  sorted.sort((a, b) => {
    switch (sort) {
      case "name-asc":
        return a.name.localeCompare(b.name);
      case "name-desc":
        return b.name.localeCompare(a.name);
      case "date-asc":
        return new Date(a.modified_at).getTime() - new Date(b.modified_at).getTime();
      case "date-desc":
      default:
        return new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime();
    }
  });
  return sorted;
}

function artifactParentPath(name: string): string {
  const separator = name.lastIndexOf("/");
  return separator < 0 ? "" : name.slice(0, separator);
}

function ArtifactsModal({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  // State for current path within artifacts (empty string = root)
  const [currentPath, setCurrentPath] = useState<string>('');
  const [items, setItems] = useState<Artifact[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [artifactQuery, setArtifactQuery] = useState("");
  const [artifactSort, setArtifactSort] = useState<ArtifactSort>("name-asc");
  const [artifactDirectory, setArtifactDirectory] = useState("");
  const [artifactDirectoryError, setArtifactDirectoryError] = useState(false);
  const [directoryCopied, setDirectoryCopied] = useState(false);
  const { openPreviewWindow, hasActivePreviewWindow } = usePreviewWindows();
  const t = translations[readLanguage()];

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
    let cancelled = false;
    setArtifactDirectory("");
    setArtifactDirectoryError(false);
    fetchArtifactDirectory(sessionId)
      .then((result) => { if (!cancelled) setArtifactDirectory(result.path); })
      .catch(() => { if (!cancelled) setArtifactDirectoryError(true); });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || hasActivePreviewWindow) return;
      onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, hasActivePreviewWindow]);

  function downloadArtifact(item: Artifact) {
    const anchor = document.createElement("a");
    anchor.href = artifactDownloadUrl(sessionId, item.name);
    anchor.download = item.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  async function copyArtifactDirectory() {
    if (!artifactDirectory) return;
    if (await copyToClipboard(artifactDirectory)) {
      setDirectoryCopied(true);
      window.setTimeout(() => setDirectoryCopied(false), 1500);
    }
  }

  const normalizedQuery = artifactQuery.trim().toLowerCase();
  const isSearching = normalizedQuery.length > 0;

  // When searching, look across every artifact in the session (not just the
  // current folder) so results aren't hidden behind navigation.
  const searchResults = isSearching
    ? items.filter((item) => item.name.toLowerCase().includes(normalizedQuery))
    : [];

  // Compute visible items based on currentPath
  const visibleItems = items.filter((item) => {
    if (!currentPath) return !item.name.includes("/");
    return item.name.startsWith(currentPath + "/") && !item.name.slice(currentPath.length + 1).includes("/");
  });

  const displayedItems = sortArtifacts(isSearching ? searchResults : visibleItems, artifactSort);

  // Compute subfolders in the current directory (always sorted by name;
  // folders have no date of their own to sort by).
  const subfolders = isSearching ? [] : Array.from(new Set(items
    .filter((item) => {
      const prefix = currentPath ? currentPath + "/" : "";
      if (!item.name.startsWith(prefix)) return false;
      const remainder = item.name.slice(prefix.length);
      return remainder.includes("/");
    })
    .map((item) => {
      const prefix = currentPath ? currentPath + "/" : "";
      const remainder = item.name.slice(prefix.length);
      return remainder.split("/")[0];
    })
  )).sort((a, b) => a.localeCompare(b));

  const goUp = () => {
    if (!currentPath) return;
    const parts = currentPath.split("/");
    parts.pop();
    setCurrentPath(parts.join("/"));
  };

  const openFolder = (folder: string) => {
    setCurrentPath(currentPath ? `${currentPath}/${folder}` : folder);
  };

  function openArtifactPreview(item: Artifact) {
    const parentPath = artifactParentPath(item.name);
    const siblingItems = sortArtifacts(
      items.filter((candidate) => (
        artifactParentPath(candidate.name) === parentPath
        && isPreviewableArtifact(candidate.name, candidate.media_type)
      )),
      artifactSort,
    );
    openPreviewWindow({
      resolveSource: (path) => {
        const match = items.find((candidate) => candidate.name === path);
        return artifactPreviewSource(sessionId, match ?? item);
      },
      siblings: siblingItems.map((candidate) => candidate.name),
      initialPath: item.name,
    });
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="help-modal directory-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="artifacts-title"
      >
        <>
            <header>
              <div>
                <span className="eyebrow">{translations[readLanguage()].artifactsTitle}</span>
                <h2 id="artifacts-title" className="directory-path">
                  {translations[readLanguage()].sessions} {sessionId}
                  {currentPath && ` / ${currentPath}`}
                </h2>
              </div>
              <button className="modal-close" onClick={onClose} aria-label={translations[readLanguage()].close}>×</button>
            </header>
            <div className="artifact-directory">
              <span>{t.artifactFolderLabel}</span>
              <code title={artifactDirectory}>
                {artifactDirectory || (artifactDirectoryError ? t.artifactFolderUnavailable : "…")}
              </code>
              <button
                type="button"
                className="directory-copy directory-icon-btn"
                disabled={!artifactDirectory}
                onClick={() => void copyArtifactDirectory()}
                title={directoryCopied ? t.copied : t.copyPath}
                aria-label={directoryCopied ? t.copied : t.copyPath}
              >
                {directoryCopied ? (
                  <svg className="action-icon-sm copy-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                )}
              </button>
            </div>
            <div className="directory-nav-bar">
              <div className="directory-nav-actions">
                <button
                  type="button"
                  className="directory-nav-btn"
                  disabled={!currentPath || isSearching}
                  onClick={goUp}
                  title={translations[readLanguage()].upDirectory}
                  aria-label={translations[readLanguage()].upDirectory}
                >
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="directory-nav-btn"
                  disabled={!currentPath || isSearching}
                  onClick={() => setCurrentPath("")}
                  title={translations[readLanguage()].rootArtifacts}
                  aria-label={translations[readLanguage()].rootArtifacts}
                >
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                    <polyline points="9 22 9 12 15 12 15 22" />
                  </svg>
                </button>
              </div>
              {!isSearching && (
                <nav className="directory-breadcrumbs" aria-label="Percorso artefatti">
                  {parseArtifactBreadcrumbs(currentPath).map((crumb, idx) => {
                    const isCurrent = crumb.path === currentPath;
                    return (
                      <span key={crumb.path || "root"} className="breadcrumb-segment">
                        {idx > 0 && <span className="breadcrumb-sep" aria-hidden="true">/</span>}
                        {isCurrent ? (
                          <span className="breadcrumb-item active" aria-current="location">{crumb.name}</span>
                        ) : (
                          <button
                            type="button"
                            className="breadcrumb-item link"
                            onClick={() => setCurrentPath(crumb.path)}
                            title={crumb.name}
                          >
                            {crumb.name}
                          </button>
                        )}
                      </span>
                    );
                  })}
                </nav>
              )}
            </div>
            {items.length > 0 && (
              <div className="artifact-toolbar">
                <input
                  type="search"
                  className="artifact-search"
                  placeholder={translations[readLanguage()].artifactSearchPlaceholder}
                  aria-label={translations[readLanguage()].artifactSearchPlaceholder}
                  value={artifactQuery}
                  onChange={(event) => setArtifactQuery(event.target.value)}
                />
                <select
                  className="artifact-sort"
                  aria-label={translations[readLanguage()].artifactSortLabel}
                  value={artifactSort}
                  onChange={(event) => setArtifactSort(event.target.value as ArtifactSort)}
                >
                  <option value="name-asc">{translations[readLanguage()].artifactSortNameAsc}</option>
                  <option value="name-desc">{translations[readLanguage()].artifactSortNameDesc}</option>
                  <option value="date-desc">{translations[readLanguage()].artifactSortDateDesc}</option>
                  <option value="date-asc">{translations[readLanguage()].artifactSortDateAsc}</option>
                </select>
              </div>
            )}
            {loading && <p className="empty">{translations[readLanguage()].loading}</p>}
            {error && <p className="error">{error}</p>}
            {!loading && !error && (
              <ul className="directory-list">
                {subfolders.map((folder) => (
                  <li key={`folder-${folder}`} className="directory-entry">
                    <button
                      type="button"
                      className="directory-open"
                      onClick={() => openFolder(folder)}
                    >
                      <FileTypeIcon type="dir" name={folder} />
                      <span className="directory-name" title={folder}>{folder}</span>
                    </button>
                  </li>
                ))}
                {displayedItems.map((item) => (
                  <li key={item.name} className="directory-entry">
                    <button
                      type="button"
                      className="directory-open"
                      disabled={!isPreviewableArtifact(item.name, item.media_type)}
                      onClick={() => openArtifactPreview(item)}
                    >
                      <FileTypeIcon type="file" name={item.name} mediaType={item.media_type} />
                      <span className="directory-name" title={item.name}>{isSearching ? item.name : item.name.split("/").pop()}</span>
                      <span className="directory-meta">{formatSize(item.size)} · {formatDate(item.modified_at)}</span>
                    </button>
                    <button
                      type="button"
                      className="directory-download directory-icon-btn"
                      title={t.download}
                      aria-label={`${t.download}: ${item.name}`}
                      onClick={() => downloadArtifact(item)}
                    >
                      <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                    </button>
                  </li>
                ))}
                {displayedItems.length === 0 && subfolders.length === 0 && (
                  <li className="empty">
                    {isSearching ? translations[readLanguage()].noArtifactsMatch : translations[readLanguage()].noArtifacts}
                  </li>
                )}
              </ul>
            )}
        </>
      </section>
    </div>
  );
}

function isYoloSession(session: Session): boolean {
  return (session.profile ?? "").endsWith("_yolo");
}

function yoloLabel(): string {
  return translations[readLanguage()].yoloLabel;
}

function suggestedSnapshotMode(session: Session): SnapshotMode {
  if (isYoloSession(session)) {
    return session.profile === "antigravity_yolo" ? "antigravity_yolo" : "opencode_yolo";
  }
  const command = session.current_command.toLowerCase();
  if (command.includes("codex")) return "codex";
  if (command.includes("claude")) return "claude";
  if (command.includes("agy") || command.includes("antigravity")) return "antigravity";
  if (command.includes("opencode")) return "opencode";
  return "shell";
}

/**
 * Modificatore di colore per il riquadro icona, per dare un minimo di
 * riconoscibilità visiva ai servizi principali senza rompere la palette
 * scura dell'app. Stessa logica di riconoscimento di `SessionIcon`.
 */
function sessionIconAccent(cmd: string): "" | "claude" | "agy" | "opencode" | "codex" {
  const c = cmd.toLowerCase();
  if (c.includes("claude") || c.includes("anthropic")) return "claude";
  if (c.includes("agy") || c.includes("antigravity")) return "agy";
  if (c.includes("opencode")) return "opencode";
  if (c.includes("codex") || c.includes("openai")) return "codex";
  return "";
}

/** Icona SVG ufficiale (Simple Icons) o testuale per il riquadro di ogni sessione in lista. */
function SessionIcon({ cmd }: { cmd: string }): ReactNode {
  const c = cmd.toLowerCase();

  // Claude / Anthropic — logo Anthropic (claude.svg non presente in Simple Icons)
  if (c.includes("claude") || c.includes("anthropic"))
    return (
      <svg viewBox="0 0 24 24" aria-label="Claude" role="img">
        <path d="M17.3041 3.541h-3.6718l6.696 16.918H24Zm-10.6082 0L0 20.459h3.7442l1.3693-3.5527h7.0052l1.3693 3.5528h3.7442L10.5363 3.5409Zm-.3712 10.2232 2.2914-5.9456 2.2914 5.9456Z" />
      </svg>
    );

  // Antigravity / AGY — logo Google Gemini (Antigravity è basato su Gemini)
  if (c.includes("agy") || c.includes("antigravity"))
    return (
      <svg viewBox="0 0 24 24" aria-label="Antigravity (Gemini)" role="img">
        <path d="M11.04 19.32Q12 21.51 12 24q0-2.49.93-4.68.96-2.19 2.58-3.81t3.81-2.55Q21.51 12 24 12q-2.49 0-4.68-.93a12.3 12.3 0 0 1-3.81-2.58 12.3 12.3 0 0 1-2.58-3.81Q12 2.49 12 0q0 2.49-.96 4.68-.93 2.19-2.55 3.81a12.3 12.3 0 0 1-3.81 2.58Q2.49 12 0 12q2.49 0 4.68.96 2.19.93 3.81 2.55t2.55 3.81" />
      </svg>
    );

  // OpenCode
  if (c.includes("opencode"))
    return (
      <svg viewBox="0 0 24 24" aria-label="OpenCode" role="img">
        <path d="M0 0v24h24V0H0zm3.84 3.84h16.32v16.32H3.84V3.84zm3.84 3.84v8.64h8.64V7.68H7.68z" />
      </svg>
    );

  // Codex / OpenAI
  if (c.includes("codex") || c.includes("openai"))
    return (
      <svg viewBox="0 0 24 24" aria-label="OpenAI" role="img">
        <path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.5045 4.5045 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1239 7.2a.076.076 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z" />
      </svg>
    );

  // Python / IPython / Jupyter
  if (c.includes("python") || c.includes("ipython") || c.includes("jupyter"))
    return (
      <svg viewBox="0 0 24 24" aria-label="Python" role="img">
        <path d="M14.254.011c-.459.002-.899.04-1.284.11-1.12.202-1.682.63-1.682 1.32v1.54h3.033v.44H8.652c-1.42 0-2.664.845-3.045 2.378-.44 1.765-.452 2.87-.01 4.675.344 1.392 1.125 2.376 2.545 2.376h1.64v-1.6c0-1.57 1.338-2.88 2.97-2.88h4.59v-3.04c0-1.392-1.156-2.5-2.547-2.5H14.25zm-2.03 1.54a.88.88 0 1 1 .002 1.76.88.88 0 0 1-.002-1.76zM9.746 23.989c.459-.002.899-.04 1.284-.11 1.12-.202 1.682-.63 1.682-1.32v-1.54H9.68v-.44h5.669c1.42 0 2.664-.845 3.045-2.378.44-1.765.452-2.87.01-4.675-.344-1.392-1.125-2.376-2.545-2.376h-1.64v1.6c0 1.57-1.338 2.88-2.97 2.88h-4.59v3.04c0 1.392 1.156 2.5 2.547 2.5h.547zm2.03-1.54a.88.88 0 1 1-.002-1.76.88.88 0 0 1 .002 1.76z" />
      </svg>
    );

  // Node.js / Bun / Deno
  if (c.includes("node") || c.includes("bun") || c.includes("deno"))
    return (
      <svg viewBox="0 0 24 24" aria-label="Node.js" role="img">
        <path d="M11.998 0c-.394 0-.788.106-1.135.318L1.648 5.7c-.707.416-1.148 1.185-1.148 2.012v10.576c0 .827.441 1.596 1.148 2.012l9.215 5.382c.347.212.741.318 1.135.318s.788-.106 1.135-.318l9.215-5.382c.707-.416 1.148-1.185 1.148-2.012V7.712c0-.827-.441-1.596-1.148-2.012L13.133.318C12.786.106 12.392 0 11.998 0zm.014 2.215a.998.998 0 0 1 .5.137l7.744 4.523a1 1 0 0 1 .494.863v8.524a1 1 0 0 1-.494.863l-7.744 4.523a.998.998 0 0 1-1 0l-7.744-4.523a1 1 0 0 1-.494-.863V7.738a1 1 0 0 1 .494-.863l7.744-4.523a.998.998 0 0 1 .5-.137z" />
      </svg>
    );

  // Vim / Neovim — Simple Icons ha solo neovim.svg
  if (c.includes("vim") || c.includes("nvim"))
    return (
      <svg viewBox="0 0 24 24" aria-label="Neovim" role="img">
        <path d="M1.644 0v19.34L18.356 0v20h-1.644V.66L0 20V0h1.644Z" />
      </svg>
    );

  // Git
  if (c.includes("git"))
    return (
      <svg viewBox="0 0 24 24" aria-label="Git" role="img">
        <path d="M23.546 10.93L13.067.452a2.023 2.023 0 0 0-2.862 0l-2.86 2.86 3.616 3.616c.358-.12.774-.08 1.107.126.544.336.804.972.673 1.583l4.316 4.316c.611-.13 1.247.13 1.583.673.473.766.242 1.776-.524 2.249-.766.473-1.776.242-2.249-.524a1.698 1.698 0 0 1-.127-1.108l-4.048-4.047v5.52a1.724 1.724 0 0 1 .494.673c.473.766.242 1.776-.524 2.249-.766.473-1.776.242-2.249-.524-.473-.766-.242-1.776.524-2.249.263-.162.564-.236.864-.23V9.824a1.7 1.7 0 0 1-.864-.23c-.766-.473-.997-1.483-.524-2.249.473-.766 1.483-.997 2.249-.524.333.206.55.51.64.864l3.65-3.65L7.345 0 .454 6.892a2.023 2.023 0 0 0 0 2.862l10.479 10.479a2.023 2.023 0 0 0 2.862 0l9.751-9.751a2.023 2.023 0 0 0 0-2.862z" />
      </svg>
    );

  // SSH
  if (c.includes("ssh"))
    return <span aria-label="SSH">⇄</span>;

  // Shell generica / default
  return <span aria-label="shell">{">_"}</span>;
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
            <span className="eyebrow">{translations[readLanguage()].vpsRestart}</span>
            <h2 id="snapshot-title">{translations[readLanguage()].snapshots}</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label={translations[readLanguage()].close}>×</button>
        </header>

        <form className="snapshot-create" onSubmit={(event) => void saveSnapshot(event)}>
          <label>
            Name
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
                    <option value="shell">Shell</option>
                    <option value="codex">Codex</option>
                    <option value="claude">Claude</option>
                    <option value="antigravity">Antigravity</option>
                    <option value="antigravity_yolo">Antigravity (yolo)</option>
                    <option value="opencode">OpenCode</option>
                    <option value="opencode_yolo">OpenCode (yolo)</option>
                    <option value="manual">Manual</option>
                  </select>
                </div>
              );
            })}
            {sessions.length === 0 && <p className="empty">{translations[readLanguage()].noSessionsToSave}</p>}
          </div>
          <button type="submit" disabled={saving || sessions.length === 0}>
            {saving ? translations[readLanguage()].loading : translations[readLanguage()].snapshots}
          </button>
        </form>

        <div className="snapshot-existing">
          <h3>{translations[readLanguage()].snapshots}</h3>
          {loading && <p className="empty">{translations[readLanguage()].loading}</p>}
          {!loading && snapshots.map((item) => (
            <article className="snapshot-card" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <small>{new Date(item.created_at).toLocaleString()} · {item.sessions.length} {translations[readLanguage()].sessions}</small>
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
                  {translations[readLanguage()].restore}
                </button>
                <button className="danger" disabled={busyId === item.id} onClick={() => void remove(item)}>
                  {translations[readLanguage()].delete}
                </button>
              </div>
            </article>
          ))}
          {!loading && snapshots.length === 0 && <p className="empty">{translations[readLanguage()].noSnapshots}</p>}
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

function ArchiveSessionModal({
  session,
  onClose,
  onArchived,
}: {
  session: Session;
  onClose: () => void;
  onArchived: (session: Session) => void;
}) {
  const [agentSessionName, setAgentSessionName] = useState("");
  const [summary, setSummary] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchArchiveDraft(session.id)
      .then((draft) => {
        if (active) setSummary(draft.summary ?? "");
      })
      .catch((value) => {
        if (active) setError(`Riepilogo precompilato non disponibile: ${errorMessage(value)}`);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [session.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await archiveSession(session.id, agentSessionName, summary);
      onArchived(session);
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section className="help-modal archive-create-modal" role="dialog" aria-modal="true" aria-labelledby="archive-create-title">
        <header>
          <div><span className="eyebrow">METADATI SESSIONE</span><h2 id="archive-create-title">Archivia {session.name}</h2></div>
          <button className="modal-close" onClick={onClose} disabled={saving} aria-label="Chiudi">×</button>
        </header>
        <form className="archive-create" onSubmit={(event) => void submit(event)}>
          <label>
            Nome conversazione <small>Opzionale, utile per ritrovarla nel picker dell’agente.</small>
            <input
              value={agentSessionName}
              onChange={(event) => setAgentSessionName(event.target.value)}
              maxLength={128}
              placeholder="Es. Correzione login mobile"
              autoFocus
            />
          </label>
          <label>
            Riepilogo <small>{loading ? "Cerco archive-summary.md…" : "Opzionale e modificabile."}</small>
            <textarea
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              maxLength={2000}
              rows={8}
              disabled={loading}
              placeholder="A cosa serviva questa conversazione e cosa resta da fare?"
            />
            <small className="archive-counter">{summary.length}/2000</small>
          </label>
          <p className="archive-privacy-note">Questi metadati saranno salvati nel database e inclusi nei backup amministrativi. Non inserire segreti.</p>
          {error && <p className="error">{error}</p>}
          <div className="snapshot-actions">
            <button type="button" onClick={onClose} disabled={saving}>Annulla</button>
            <button type="submit" disabled={saving || loading}>{saving ? "Archiviazione…" : "Archivia e termina tmux"}</button>
          </div>
        </form>
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
  const [query, setQuery] = useState("");

  const filteredArchives = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return archives;
    return archives.filter((item) => [
      item.name,
      item.agent_session_name,
      item.summary,
      item.directory,
      item.profile,
    ].filter(Boolean).join(" ").toLocaleLowerCase().includes(normalized));
  }, [archives, query]);

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
          <div><span className="eyebrow">{translations[readLanguage()].sessionMetadata}</span><h2 id="archive-title">{translations[readLanguage()].archivedSessions}</h2></div>
          <button className="modal-close" onClick={onClose} aria-label={translations[readLanguage()].close}>×</button>
        </header>
        <div className="snapshot-existing">
          {!loading && archives.length > 0 && (
            <input
              className="archive-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Cerca per nome, riepilogo o percorso…"
              aria-label="Cerca sessioni archiviate"
            />
          )}
          {loading && <p className="empty">{translations[readLanguage()].loading}</p>}
          {!loading && filteredArchives.map((item) => (
            <article className="snapshot-card" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                {item.agent_session_name && <h3 className="archive-agent-name">{item.agent_session_name}</h3>}
                <small>{item.profile} · {new Date(item.archived_at).toLocaleString()}</small>
                <small>{item.directory}</small>
                {item.summary && <p className="archive-summary">{item.summary}</p>}
                <small>Archived by {item.archived_by}</small>
              </div>
              <div className="snapshot-actions">
                <button disabled={busyId === item.id} onClick={() => void restore(item)}>{translations[readLanguage()].restore}</button>
                <button className="danger" disabled={busyId === item.id} onClick={() => void remove(item)}>{translations[readLanguage()].delete}</button>
              </div>
            </article>
          ))}
          {!loading && archives.length > 0 && filteredArchives.length === 0 && <p className="empty">Nessun archivio corrisponde alla ricerca.</p>}
          {!loading && archives.length === 0 && <p className="empty">{translations[readLanguage()].noArchivedSessions}</p>}
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
          <div><span className="eyebrow">DASHBOARD</span><h2 id="hidden-sessions-title">{translations[readLanguage()].hiddenSessions}</h2></div>
          <button className="modal-close" onClick={onClose} aria-label={translations[readLanguage()].close}>×</button>
        </header>
        <div className="snapshot-existing">
          {sessions.map((session) => (
            <article className="snapshot-card" key={session.id}>
              <div>
                <strong>{session.name}</strong>
                <small>{session.current_command}</small>
              </div>
              <div className="snapshot-actions">
                <button onClick={() => { onOpen(session); onClose(); }}>Open</button>
                {canManage && <button disabled={busyId === session.id} onClick={() => void restore(session)}>Show</button>}
              </div>
            </article>
          ))}
          {sessions.length === 0 && <p className="empty">{translations[readLanguage()].noHiddenSessions}</p>}
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
  language,
  onLanguageChange,
}: {
  onClose: () => void;
  dashboardDensity: DashboardDensity;
  onDashboardDensityChange: (density: DashboardDensity) => void;
  language: Language;
  onLanguageChange: (lang: Language) => void;
}) {
  const [defaultView, setDefaultView] = useState<"blocks" | "terminal">(readDefaultAgentView());
  const t = translations[language];

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
          <div><span className="eyebrow">CONSOLE</span><h2 id="preferences-title">{t.settings}</h2></div>
          <button className="modal-close" onClick={onClose} aria-label={t.close}>×</button>
        </header>
        <fieldset className="preference-field">
          <legend>{t.language}</legend>
          <label>
            <input
              type="radio"
              name="app-language"
              checked={language === "it"}
              onChange={() => onLanguageChange("it")}
            />
            {t.italian}
          </label>
          <label>
            <input
              type="radio"
              name="app-language"
              checked={language === "en"}
              onChange={() => onLanguageChange("en")}
            />
            {t.english}
          </label>
        </fieldset>
        <fieldset className="preference-field">
          <legend>{t.defaultView}</legend>
          <label>
            <input
              type="radio"
              name="default-agent-view"
              checked={defaultView === "blocks"}
              onChange={() => choose("blocks")}
            />
            {t.blocksView}
          </label>
          <label>
            <input
              type="radio"
              name="default-agent-view"
              checked={defaultView === "terminal"}
              onChange={() => choose("terminal")}
            />
            {t.terminalView}
          </label>
        </fieldset>
        <fieldset className="preference-field">
          <legend>{t.dashboardDensity}</legend>
          <label>
            <input
              type="radio"
              name="dashboard-density"
              checked={dashboardDensity === "extended"}
              onChange={() => onDashboardDensityChange("extended")}
            />
            {t.extended}
          </label>
          <label>
            <input
              type="radio"
              name="dashboard-density"
              checked={dashboardDensity === "compact"}
              onChange={() => onDashboardDensityChange("compact")}
            />
            {t.compact}
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
  docker_state_stale: "Stato Docker non aggiornato",
  essential_container_down: "Servizio strategico non attivo",
  docker_output_excessive: "Risposta Docker troppo grande",
  docker_output_invalid: "Risposta Docker non valida",
  containers_problematic: "Container con problemi",
  services_unavailable: "Stato dei servizi non disponibile",
  services_state_stale: "Stato dei servizi non aggiornato",
  services_output_excessive: "Stato dei servizi troppo grande",
  services_output_invalid: "Stato dei servizi non valido",
  essential_service_down: "Servizio strategico non attivo",
  supervisor_unavailable: "Supervisore non raggiunto",
  tmux_orphans_unavailable: "Monitor scope tmux non disponibile",
  tmux_orphans_state_stale: "Monitor scope tmux non aggiornato",
  tmux_orphan_detected: "Processo orfano di una sessione tmux",
  tmux_orphan_memory_critical: "Processo tmux orfano con memoria critica",
  tmux_orphan_swap_critical: "Processo tmux orfano con swap critica",
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

// Cosa fare, non come si chiama il codice di reason: il titolo resta
// HOST_REASON_LABEL, questa è la riga che dice perché importa.
const HOST_REASON_HINT: Record<string, string> = {
  memory_available_low: "Resta poca memoria libera: la prossima sessione pesante rischia di finire in swap.",
  memory_available_critical: "Memoria libera quasi esaurita: chiudi qualche sessione prima di avviarne altre.",
  memory_unavailable: "Il collector non ha potuto leggere i valori di memoria: nessuna misura, non un esito positivo.",
  swap_used_high: "Spazio di swap occupato oltre la soglia. Guarda l'attività: se è ferma sono pagine parcheggiate.",
  swap_used_critical: "Spazio di swap quasi esaurito: senza margine il kernel non può più scaricare pagine.",
  swap_activity_high: "Il sistema sta leggendo e scrivendo swap adesso: è questo che rallenta la macchina.",
  swap_pressure_critical: "Memoria esaurita e swap in movimento insieme: la macchina sta trascinando.",
  swap_sample_unavailable: "Senza campione non si può dire se la swap sia in uso o solo occupata.",
  load_high: "Più lavoro in coda che CPU per eseguirlo: i comandi rispondono lenti.",
  load_critical: "Coda di esecuzione molto oltre il numero di CPU: la macchina non sta dietro.",
  load_unavailable: "Carico non leggibile in questa fotografia.",
  filesystem_used_high: "Spazio in esaurimento: controlla log e immagini prima che si riempia.",
  filesystem_used_critical: "Spazio quasi finito: le scritture stanno per fallire.",
  filesystem_unavailable: "Volume non interrogabile: spazio non accertato.",
  filesystems_not_configured: "Nessun volume da sorvegliare è configurato nel collector.",
  processes_partial: "Parte dei processi non è leggibile: le classifiche qui sotto possono essere incomplete.",
  processes_unavailable: "Elenco processi non disponibile: nessuna attribuzione possibile.",
  process_group_count_high: "Molti processi con lo stesso nome: di solito è qualcosa che non è stato chiuso.",
  process_group_count_critical: "Numero di processi omonimi fuori scala: quasi certamente processi orfani.",
  process_policy_count_high: "Il gruppo supera il numero di processi ammesso dalla policy locale.",
  process_policy_count_critical: "Il gruppo supera di molto il numero di processi ammesso dalla policy locale.",
  process_policy_rss_high: "Il gruppo supera la memoria aggregata ammessa dalla policy locale.",
  process_policy_rss_critical: "Il gruppo supera di molto la memoria aggregata ammessa dalla policy locale.",
  wildcard_listener_unexpected: "Una porta ascolta su tutte le interfacce dove la policy si aspetta un bind ristretto.",
  tcp_listener_unexpected: "Una porta in ascolto non compare tra quelle previste dalla policy locale.",
  listeners_partial: "Alcuni socket non hanno un processo associato: il proprietario resta ignoto.",
  listeners_unavailable: "Porte in ascolto non leggibili in questa fotografia.",
  docker_unavailable: "Senza Docker non si vede la memoria per container: metà delle diagnosi manca.",
  docker_state_stale: "Il timer che raccoglie lo stato dei container si è fermato: quello mostrato sarebbe vecchio, quindi non viene mostrato affatto.",
  essential_container_down: "Un servizio dichiarato strategico non è in esecuzione: va rimesso in piedi, non rimandato.",
  docker_disabled: "Raccolta Docker disattivata nella configurazione del collector.",
  docker_output_excessive: "Risposta di Docker troppo grande: scartata senza interpretarla.",
  docker_output_invalid: "Risposta di Docker non interpretabile: stato dei container non accertato.",
  containers_problematic: "Uno o più container non sono in stato sano.",
  services_unavailable: "Stato dei servizi supervisionati non raccolto: systemd e pm2 non sono osservati in questa fotografia.",
  services_state_stale: "Il timer che raccoglie lo stato dei servizi si è fermato: quello mostrato sarebbe vecchio, quindi non viene mostrato affatto.",
  services_output_excessive: "Stato dei servizi troppo grande: scartato senza interpretarlo.",
  services_output_invalid: "Stato dei servizi non interpretabile: nessun servizio è accertato.",
  essential_service_down: "Un servizio dichiarato strategico non è in esecuzione: va rimesso in piedi, non rimandato.",
  supervisor_unavailable: "Un supervisore non ha risposto: i suoi servizi non sono accertati, il che non vuol dire che siano caduti.",
  tmux_orphans_unavailable: "Il confronto tra pane tmux e scope systemd non è disponibile: gli orfani non sono accertati.",
  tmux_orphans_state_stale: "Il timer del monitor tmux si è fermato: il dato vecchio viene scartato.",
  tmux_orphan_detected: "Uno scope avviato da tmux è ancora attivo, ma il pane che lo possedeva non esiste più.",
  tmux_orphan_memory_critical: "Uno scope tmux orfano ha superato la soglia di memoria corrente configurata.",
  tmux_orphan_swap_critical: "Uno scope tmux orfano ha superato la soglia di swap configurata.",
};

// `info` non è uno stato del collector: è una riga che esiste perché l'utente
// deve vederla e decidere, non perché qualcosa stia andando male.
type HostIssueSeverity = HostComponent["status"] | "info";
type HostIssue = { key: string; severity: HostIssueSeverity; title: string; hint: string };

const HOST_SEVERITY_RANK: Record<HostIssueSeverity, number> = {
  critical: 0,
  warning: 1,
  unknown: 2,
  info: 3,
  ok: 4,
};

const HOST_CONTAINER_STATE_LABEL: Record<string, string> = {
  running: "attivo",
  stopped: "fermo",
  restarting: "in riavvio",
  unhealthy: "non sano",
  starting: "in avvio",
  paused: "in pausa",
  unknown: "stato ignoto",
};

const HOST_SERVICE_STATE_LABEL: Record<string, string> = {
  running: "attivo",
  starting: "in avvio",
  stopped: "fermo",
  failed: "in errore",
  restarting: "in riavvio",
  // Il supervisore risponde e non lo conosce più: è sparito, non è fermo.
  absent: "non esiste più",
  unknown: "non accertato",
};

const HOST_SUPERVISOR_LABEL: Record<string, string> = {
  systemd_system: "systemd",
  systemd_user: "systemd utente",
  pm2: "pm2",
};

// Il suffisso del reason porta già la gravità; `fallback` è lo stato del
// componente da cui il reason proviene, usato quando il nome non la dichiara.
function hostReasonSeverity(reason: string, fallback: HostComponent["status"]): HostComponent["status"] {
  if (reason.endsWith("_critical")) return "critical";
  if (reason.endsWith("_unavailable") || reason.endsWith("_partial")) return "unknown";
  if (
    reason.endsWith("_high")
    || reason.endsWith("_low")
    || reason.endsWith("_unexpected")
    || reason === "containers_problematic"
  ) return "warning";
  return fallback;
}

function hostSwapIdle(snapshot: HostObservabilitySnapshot): boolean {
  if (snapshot.schema_version === 1) return false;
  const sample = snapshot.memory.swap_io_sample;
  return sample.available && sample.pages_in_delta === 0 && sample.pages_out_delta === 0;
}

function buildHostIssues(snapshot: HostObservabilitySnapshot): HostIssue[] {
  const components: Array<[string, HostComponent]> = [
    ["memoria", snapshot.memory],
    ["carico", snapshot.load],
    ["dischi", snapshot.filesystems],
    ["processi", snapshot.processes],
    ["porte", snapshot.listeners],
    ["docker", snapshot.docker],
    ...(snapshot.schema_version !== 1 && snapshot.services
      ? ([["servizi", snapshot.services]] as Array<[string, HostComponent]>)
      : []),
    ...(snapshot.schema_version === 3
      ? ([["orfani tmux", snapshot.tmux_orphans]] as Array<[string, HostComponent]>)
      : []),
  ];
  const issues: HostIssue[] = [];
  const seen = new Set<string>();
  for (const [scope, component] of components) {
    for (const reason of component.reasons) {
      if (seen.has(reason)) continue;
      seen.add(reason);
      issues.push({
        key: `${scope}-${reason}`,
        severity: hostReasonSeverity(reason, component.status),
        title: HOST_REASON_LABEL[reason] ?? reason.replaceAll("_", " "),
        hint: hostIssueHint(reason, snapshot),
      });
    }
  }
  // I servizi non critici fermi non producono un reason: il collector non li
  // giudica. Restano però una decisione da prendere, quindi vanno visti.
  if (snapshot.schema_version !== 1) {
    for (const container of snapshot.docker.containers ?? []) {
      if (container.priority !== "optional" || container.state === "running") continue;
      issues.push({
        key: `container-${container.label}`,
        severity: "info",
        title: `${container.label}: ${HOST_CONTAINER_STATE_LABEL[container.state] ?? container.state}`,
        hint: "Servizio non critico: puoi riavviarlo quando non ci sono sessioni pesanti in corso.",
      });
    }
    for (const service of snapshot.services?.items ?? []) {
      // `unknown` non è "fermo": è già dichiarato da `supervisor_unavailable`,
      // e contarlo fra i non critici fermi direbbe una cosa falsa.
      if (
        service.priority !== "optional"
        || service.state === "running"
        || service.state === "starting"
        || service.state === "unknown"
      ) continue;
      issues.push({
        key: `service-${service.supervisor}-${service.label}`,
        severity: "info",
        title: `${service.label}: ${HOST_SERVICE_STATE_LABEL[service.state] ?? service.state}`,
        hint: "Servizio non critico: puoi riavviarlo quando non ci sono sessioni pesanti in corso.",
      });
    }
  }
  return issues.sort((a, b) => HOST_SEVERITY_RANK[a.severity] - HOST_SEVERITY_RANK[b.severity]);
}

// Il reason dice la categoria; qui si aggiunge il soggetto concreto già
// presente nello snapshot, così la riga nomina la porta o il volume.
function hostIssueHint(reason: string, snapshot: HostObservabilitySnapshot): string {
  const base = HOST_REASON_HINT[reason] ?? "";
  if (reason === "swap_used_high" && hostSwapIdle(snapshot)) {
    // L'attività è già stata misurata: inutile rimandare l'utente a guardarla.
    return "Spazio di swap occupato oltre la soglia, ma fermo: nessuna pagina letta o scritta nel campione. Sono pagine parcheggiate.";
  }
  if (reason === "wildcard_listener_unexpected" || reason === "tcp_listener_unexpected") {
    const wildcardOnly = reason === "wildcard_listener_unexpected";
    const ports = snapshot.listeners.items
      .filter((item) => {
        if (item.status === "ok") return false;
        const scope = "bind_scope" in item ? item.bind_scope : item.address_scope;
        return wildcardOnly ? scope === "wildcard" : scope !== "wildcard";
      })
      .map((item) => `TCP ${item.port}${item.process_label ?? item.process_name ? ` (${item.process_label ?? item.process_name})` : ""}`);
    return ports.length > 0 ? `${base} Interessate: ${ports.join(", ")}.` : base;
  }
  if (reason.startsWith("filesystem_used")) {
    const volumes = snapshot.filesystems.items
      .filter((item) => item.status !== "ok")
      .map((item) => `${item.label} ${formatPercent(item.used_percent)}`);
    return volumes.length > 0 ? `${base} Interessati: ${volumes.join(", ")}.` : base;
  }
  if (reason === "essential_service_down" || reason === "supervisor_unavailable") {
    const wanted = reason === "supervisor_unavailable" ? "unknown" : null;
    const services = (snapshot.schema_version !== 1 ? snapshot.services?.items ?? [] : [])
      .filter((service) => (
        wanted === null
          ? service.priority === "essential" && service.state !== "running" && service.state !== "starting" && service.state !== "unknown"
          : service.state === "unknown"
      ))
      .map((service) => `${service.label} (${HOST_SERVICE_STATE_LABEL[service.state] ?? service.state})`);
    return services.length > 0 ? `${base} Interessati: ${services.join(", ")}.` : base;
  }
  if (reason.startsWith("process_policy") || reason.startsWith("process_group_count")) {
    const groups = snapshot.processes.groups
      .filter((group) => group.policy_status === "violated")
      .map((group) => `${group.label ?? group.name} (${group.count}×)`);
    return groups.length > 0 ? `${base} Interessati: ${groups.join(", ")}.` : base;
  }
  return base;
}

function hostVerdictHeadline(snapshot: HostObservabilitySnapshot, issues: HostIssue[]): string {
  const criticals = issues.filter((issue) => issue.severity === "critical").length;
  const warnings = issues.filter((issue) => issue.severity === "warning").length;
  if (snapshot.status === "critical") {
    return criticals === 1 ? "1 problema critico" : `${criticals} problemi critici`;
  }
  if (snapshot.status === "warning") {
    return warnings === 1 ? "1 segnalazione, nessuna critica" : `${warnings} segnalazioni, nessuna critica`;
  }
  if (snapshot.status === "unknown") return "Fotografia incompleta";
  return "Tutto regolare";
}

function hostVerdictDetail(snapshot: HostObservabilitySnapshot, issues: HostIssue[]): string {
  const swapHigh = snapshot.memory.reasons.some((reason) => reason.startsWith("swap_used"));
  if (swapHigh && hostSwapIdle(snapshot) && snapshot.schema_version !== 1) {
    const sample = snapshot.memory.swap_io_sample;
    return (
      `La swap è occupata (${formatSize(snapshot.memory.swap_used_bytes)} di `
      + `${formatSize(snapshot.memory.swap_total_bytes)}) ma non viene toccata: 0 pagine lette e 0 scritte `
      + `nel campione da ${sample.duration_ms} ms. È memoria parcheggiata, non un collo di bottiglia.`
    );
  }
  const first = issues.find((issue) => issue.hint);
  if (first) return first.hint;
  return "Nessuna anomalia rilevata dai controlli disponibili.";
}

function HostVerdict({ snapshot, issues }: { snapshot: HostObservabilitySnapshot; issues: HostIssue[] }) {
  const counts = {
    warning: issues.filter((issue) => issue.severity === "warning").length,
    unknown: issues.filter((issue) => issue.severity === "unknown").length,
    critical: issues.filter((issue) => issue.severity === "critical").length,
    info: issues.filter((issue) => issue.severity === "info").length,
  };
  return (
    <section className={`host-verdict status-${snapshot.status}`} aria-labelledby="host-verdict-title">
      <span className="eyebrow">VERDETTO</span>
      <h2 id="host-verdict-title">
        <i className={snapshot.status} aria-hidden="true" />
        {hostVerdictHeadline(snapshot, issues)}
      </h2>
      <p>{hostVerdictDetail(snapshot, issues)}</p>
      <div className="host-verdict-chips">
        <span className="host-chip">{HOST_STATUS_LABEL[snapshot.status]}</span>
        {counts.critical > 0 && <span className="host-chip critical">{counts.critical} critiche</span>}
        {counts.warning > 0 && <span className="host-chip warning">{counts.warning} da controllare</span>}
        {counts.unknown > 0 && <span className="host-chip unknown">{counts.unknown} non accertate</span>}
        {counts.info > 0 && <span className="host-chip info">{counts.info} non critici fermi</span>}
      </div>
    </section>
  );
}

function HostKpi({
  label,
  value,
  unit,
  fill,
  status,
  note,
  tag,
  idle,
  children,
}: {
  label: string;
  value: string;
  unit?: string;
  fill: number | null;
  status: HostComponent["status"];
  note: string;
  tag?: string;
  idle?: boolean;
  children?: ReactNode;
}) {
  return (
    <article className={`host-kpi status-${status}`}>
      <header>
        <span className="eyebrow">{label}</span>
        {tag && <span className="host-kpi-tag">{tag}</span>}
      </header>
      <strong className="host-kpi-value">{value}{unit && <span>{unit}</span>}</strong>
      <div className="host-meter" aria-hidden="true">
        <i
          className={`${status}${idle ? " idle" : ""}`}
          style={{ width: `${Math.max(0, Math.min(100, fill ?? 0))}%` }}
        />
      </div>
      {children}
      <small>{note}</small>
    </article>
  );
}

// Storia locale alla visita: nessuna raccolta in background, solo gli snapshot
// che l'utente ha già chiesto (ADR 009).
function HostSparkline({ points, label }: { points: number[]; label: string }) {
  if (points.length < 2) return null;
  const step = 100 / (points.length - 1);
  const path = points
    .map((point, index) => `${(index * step).toFixed(1)},${(18 - (Math.max(0, Math.min(100, point)) / 100) * 16).toFixed(1)}`)
    .join(" ");
  const last = points[points.length - 1];
  return (
    <svg className="host-spark" viewBox="0 0 100 20" preserveAspectRatio="none" role="img" aria-label={label}>
      <polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="100" cy={18 - (Math.max(0, Math.min(100, last)) / 100) * 16} r="1.8" fill="currentColor" />
    </svg>
  );
}

function HostIssueList({ issues }: { issues: HostIssue[] }) {
  if (issues.length === 0) {
    return <p className="host-empty">Nessuna segnalazione: i controlli disponibili non hanno rilevato anomalie.</p>;
  }
  return (
    <ul className="host-issue-list">
      {issues.map((issue) => (
        <li key={issue.key} className={`status-${issue.severity}`}>
          <i className={issue.severity} aria-hidden="true" />
          <div>
            <strong>{issue.title}</strong>
            {issue.hint && <small>{issue.hint}</small>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function HostKpiRow({ snapshot, swapHistory }: { snapshot: HostObservabilitySnapshot; swapHistory: number[] }) {
  const memory = snapshot.memory;
  const usedPercent = memory.available_percent === null ? null : Math.round((100 - memory.available_percent) * 10) / 10;
  const memoryStatus: HostComponent["status"] = memory.total_bytes === null
    ? "unknown"
    : memory.reasons.includes("memory_available_critical")
      ? "critical"
      : memory.reasons.includes("memory_available_low")
        ? "warning"
        : "ok";
  const swapStatus: HostComponent["status"] = memory.swap_total_bytes === null
    ? "unknown"
    : memory.reasons.includes("swap_pressure_critical") || memory.reasons.includes("swap_used_critical")
      ? "critical"
      : memory.reasons.some((reason) => reason.startsWith("swap_"))
        ? "warning"
        : "ok";
  const idle = hostSwapIdle(snapshot);
  const swapNote = snapshot.schema_version === 1
    ? "Attività non campionata su snapshot v1"
    : snapshot.memory.swap_io_sample.available
      ? idle
        ? `Nessuna pagina letta o scritta in ${snapshot.memory.swap_io_sample.duration_ms} ms`
        : `${snapshot.memory.swap_io_sample.pages_in_delta} lette · ${snapshot.memory.swap_io_sample.pages_out_delta} scritte`
      : "Attività non accertata: campione non disponibile";
  const load = snapshot.load;
  const volumes = [...snapshot.filesystems.items].sort(
    (a, b) => (b.used_percent ?? -1) - (a.used_percent ?? -1),
  );
  const worstVolume = volumes[0];

  return (
    <div className="host-kpis">
      <HostKpi
        label="Memoria"
        value={usedPercent === null ? "n/d" : usedPercent.toFixed(0)}
        unit={usedPercent === null ? undefined : "%"}
        fill={usedPercent}
        status={memoryStatus}
        note={
          memory.total_bytes === null
            ? "Valori di memoria non leggibili"
            : `${formatSize((memory.total_bytes ?? 0) - (memory.available_bytes ?? 0))} usati di ${formatSize(memory.total_bytes)} · ${formatSize(memory.available_bytes)} liberi`
        }
      />
      <HostKpi
        label="Swap"
        value={memory.swap_used_percent === null ? "n/d" : memory.swap_used_percent.toFixed(0)}
        unit={memory.swap_used_percent === null ? undefined : "%"}
        fill={memory.swap_used_percent}
        status={swapStatus}
        idle={idle}
        tag={idle ? "Inattiva" : undefined}
        note={`${formatSize(memory.swap_used_bytes)} di ${formatSize(memory.swap_total_bytes)} · ${swapNote}`}
      >
        <HostSparkline points={swapHistory} label="Swap occupata negli aggiornamenti di questa visita" />
      </HostKpi>
      <HostKpi
        label="Carico per CPU"
        value={load.normalized_one === null ? "n/d" : load.normalized_one.toFixed(2)}
        unit={load.normalized_one === null ? undefined : "×"}
        fill={load.normalized_one === null ? null : load.normalized_one * 100}
        status={load.status}
        note={
          load.one === null
            ? "Carico non leggibile"
            : `${load.one.toFixed(2)} in coda su ${load.cpu_count} CPU · 5m ${load.five?.toFixed(2) ?? "—"} · 15m ${load.fifteen?.toFixed(2) ?? "—"}`
        }
      />
      <HostKpi
        label="Disco"
        value={worstVolume?.used_percent === null || worstVolume === undefined ? "n/d" : worstVolume.used_percent.toFixed(0)}
        unit={worstVolume?.used_percent == null ? undefined : "%"}
        fill={worstVolume?.used_percent ?? null}
        status={worstVolume?.status ?? snapshot.filesystems.status}
        note={
          worstVolume
            ? `${worstVolume.label} · ${formatSize(worstVolume.available_bytes)} liberi di ${formatSize(worstVolume.total_bytes)}${volumes.length > 1 ? ` · ${volumes.length} volumi sorvegliati` : ""}`
            : "Nessun volume configurato nel collector"
        }
      />
    </div>
  );
}

// L'unico dato della fotografia che non è istantaneo: l'età va detta, non
// lasciata intendere.
function HostContainersNote({ snapshot }: { snapshot: HostObservabilitySnapshot }) {
  if (snapshot.schema_version === 1) {
    return <>Snapshot legacy v1: la memoria per container non è raccolta.</>;
  }
  const age = snapshot.docker.state_age_seconds;
  const unmapped = snapshot.docker.unmapped_count ?? 0;
  return (
    <>
      {age === null || age === undefined
        ? "Età dello stato Docker non accertata."
        : `Stato Docker raccolto ${formatAge(age)} fa, non all'apertura di questa pagina.`}
      {unmapped > 0 && ` ${unmapped} container senza label configurata non sono elencati.`}
    </>
  );
}

// Riflette la regola del collector: la severità dipende dalla priorità, non
// dal solo stato osservato. `unknown` non è un allarme, è assenza di evidenza.
function hostServiceStatus(service: HostServiceItem): HostComponent["status"] {
  if (service.state === "unknown") return "unknown";
  if (service.state === "running" || service.state === "starting") return "ok";
  return service.priority === "essential" ? "critical" : "warning";
}

function HostServicesNote({ snapshot }: { snapshot: HostObservabilitySnapshot }) {
  const services = snapshot.schema_version !== 1 ? snapshot.services : null;
  if (!services) return <>Raccolta dei servizi supervisionati non configurata.</>;
  const unmapped = services.unmapped_count;
  return (
    <>
      {services.state_age_seconds === null || services.state_age_seconds === undefined
        ? "Età dello stato dei servizi non accertata."
        : `Stato dei servizi raccolto ${formatAge(services.state_age_seconds)} fa, non all'apertura di questa pagina.`}
      {unmapped > 0 && ` ${unmapped} app pm2 senza policy configurata non sono elencate.`}
      {" I riavvii sono mostrati ma non giudicati: il contatore è cumulativo e non ha una soglia sensata."}
    </>
  );
}

type HostConsumerTab = "rss" | "swap" | "groups" | "containers" | "services";

function HostConsumers({ snapshot }: { snapshot: HostObservabilitySnapshot }) {
  const [tab, setTab] = useState<HostConsumerTab>("rss");
  const swapRanking = snapshot.schema_version !== 1 ? snapshot.processes.top_swap ?? [] : [];
  const swapAvailable = snapshot.schema_version !== 1 && snapshot.processes.top_swap !== undefined;
  const attributed = snapshot.schema_version !== 1 ? snapshot.processes.swap_attributed_bytes ?? null : null;
  const containers = snapshot.schema_version !== 1 ? snapshot.docker.containers ?? [] : [];
  const containersAvailable = snapshot.schema_version !== 1 && snapshot.docker.containers !== undefined;
  const services = snapshot.schema_version !== 1 ? snapshot.services : null;
  const tabs: Array<[HostConsumerTab, string]> = [
    ["rss", "Memoria"],
    ...(swapAvailable ? ([["swap", "Swap"]] as Array<[HostConsumerTab, string]>) : []),
    ["groups", "Gruppi"],
    ...(containersAvailable ? ([["containers", "Container"]] as Array<[HostConsumerTab, string]>) : []),
    ...(services ? ([["services", "Servizi"]] as Array<[HostConsumerTab, string]>) : []),
  ];
  const rows = tab === "rss" ? snapshot.processes.top : tab === "swap" ? swapRanking : [];

  return (
    <section className="host-consumers" aria-labelledby="host-consumers-title">
      <header>
        <h2 id="host-consumers-title">Chi consuma</h2>
        <small>{snapshot.processes.scanned} processi analizzati{snapshot.processes.truncated ? " · elenco troncato" : ""}</small>
      </header>
      <div className="host-tabs" role="tablist" aria-label="Ordina i consumatori">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : undefined}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "services" ? (
        !services || !services.available ? (
          <p className="host-empty">
            Stato dei servizi non accertato: {HOST_REASON_LABEL[services?.reasons[0] ?? ""] ?? "raccolta non configurata"}.
          </p>
        ) : services.items.length === 0 ? (
          <p className="host-empty">Nessun servizio con una policy configurata nel collector.</p>
        ) : (
          <table className="host-table">
            <thead>
              <tr><th scope="col">Servizio</th><th scope="col">Stato</th><th scope="col">Memoria</th></tr>
            </thead>
            <tbody>
              {/* Come per i container: prima ciò su cui c'è una decisione da
                  prendere, con i servizi strategici in testa. */}
              {[...services.items].sort((a, b) => (
                Number(a.state === "running") - Number(b.state === "running")
                || Number(a.priority === "optional") - Number(b.priority === "optional")
                || (b.memory_bytes ?? 0) - (a.memory_bytes ?? 0)
              )).map((service) => (
                <tr key={`${service.supervisor}-${service.label}`}>
                  <th scope="row">
                    <span className="host-table-name">{service.label}</span>
                    <span className="host-table-sub">
                      {HOST_SUPERVISOR_LABEL[service.supervisor] ?? service.supervisor}
                      {" · "}
                      {service.priority === "essential" ? "strategico" : "non critico"}
                      {service.restarts ? ` · ${service.restarts} riavvii` : ""}
                    </span>
                  </th>
                  <td>
                    <span className={`host-container-state state-${service.state} priority-${service.priority}`}>
                      {HOST_SERVICE_STATE_LABEL[service.state] ?? service.state}
                    </span>
                  </td>
                  <td>{service.memory_bytes === null ? "—" : formatSize(service.memory_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : tab === "containers" ? (
        !snapshot.docker.available ? (
          <p className="host-empty">
            Stato dei container non accertato: {HOST_REASON_LABEL[snapshot.docker.reasons[0]] ?? "Docker non disponibile"}.
          </p>
        ) : containers.length === 0 ? (
          <p className="host-empty">Nessun container con una policy configurata nel collector.</p>
        ) : (
          <table className="host-table">
            <thead>
              <tr><th scope="col">Container</th><th scope="col">Stato</th><th scope="col">Memoria</th></tr>
            </thead>
            <tbody>
              {/* Prima ciò su cui c'è una decisione da prendere: quello che non
                  gira, con i servizi strategici in testa. */}
              {[...containers].sort((a, b) => (
                Number(a.state === "running") - Number(b.state === "running")
                || Number(a.priority === "optional") - Number(b.priority === "optional")
                || (b.memory_bytes ?? 0) - (a.memory_bytes ?? 0)
              )).map((container) => (
                <tr key={container.label}>
                  <th scope="row">
                    <span className="host-table-name">{container.label}</span>
                    <span className="host-table-sub">
                      {container.priority === "essential" ? "strategico" : "non critico"}
                    </span>
                  </th>
                  <td>
                    <span className={`host-container-state state-${container.state} priority-${container.priority}`}>
                      {HOST_CONTAINER_STATE_LABEL[container.state] ?? container.state}
                    </span>
                  </td>
                  <td>{container.memory_bytes === null ? "—" : formatSize(container.memory_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : tab === "groups" ? (
        snapshot.processes.groups.length === 0 ? (
          <p className="host-empty">Nessun gruppo disponibile.</p>
        ) : (
          <table className="host-table">
            <thead>
              <tr><th scope="col">Gruppo</th><th scope="col">Memoria</th><th scope="col">Swap</th><th scope="col">Attivi</th></tr>
            </thead>
            <tbody>
              {snapshot.processes.groups.map((group) => (
                <tr key={group.name}>
                  <th scope="row">
                    <span className="host-table-name">{group.label ?? group.name}</span>
                    <span className="host-table-sub">{group.count}× · più vecchio {formatAge(group.oldest_age_seconds)}</span>
                  </th>
                  <td>{formatSize(group.rss_bytes)}</td>
                  <td className={group.swap_bytes ? "host-table-swap" : undefined}>
                    {group.swap_bytes === undefined || group.swap_bytes === null ? "n/a" : formatSize(group.swap_bytes)}
                  </td>
                  <td>{group.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : rows.length === 0 ? (
        <p className="host-empty">
          {tab === "swap"
            ? "Nessun processo osservato ha pagine in swap: la swap occupata appartiene a processi non più esistenti o non leggibili."
            : "Nessun processo disponibile."}
        </p>
      ) : (
        <table className="host-table">
          <thead>
            <tr><th scope="col">Processo</th><th scope="col">Memoria</th><th scope="col">Swap</th><th scope="col">Età</th></tr>
          </thead>
          <tbody>
            {rows.map((process) => (
              <tr key={process.pid}>
                <th scope="row">
                  <span className="host-table-name">{process.label ?? process.name}</span>
                  <span className="host-table-sub">{process.label ? process.name : `PID ${process.pid}`}</span>
                </th>
                <td>{formatSize(process.rss_bytes)}</td>
                <td className={process.swap_bytes ? "host-table-swap" : undefined}>
                  {process.swap_bytes === undefined || process.swap_bytes === null ? "n/a" : formatSize(process.swap_bytes)}
                </td>
                <td>{formatAge(process.age_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="host-note">
        {tab === "services" ? (
          <HostServicesNote snapshot={snapshot} />
        ) : tab === "containers" ? (
          <HostContainersNote snapshot={snapshot} />
        ) : snapshot.schema_version === 1 ? (
          "Snapshot legacy v1: la swap per processo non è raccolta, la colonna resta non accertata."
        ) : attributed === null ? (
          "Swap per processo non accertata in questa fotografia."
        ) : (
          <>
            Swap attribuita ai processi osservati: {formatSize(attributed)} su{" "}
            {formatSize(snapshot.memory.swap_used_bytes)} occupati. La differenza appartiene a processi
            terminati o non leggibili e non è attribuibile.
          </>
        )}
      </p>
    </section>
  );
}

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
  // Serie locale alla visita: si allunga solo quando l'utente chiede un
  // aggiornamento, quindi non introduce raccolta periodica (ADR 009).
  const [swapHistory, setSwapHistory] = useState<number[]>([]);
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
        if (next.memory.swap_used_percent !== null) {
          const percentValue = next.memory.swap_used_percent;
          setSwapHistory((history) => [...history, percentValue].slice(-12));
        }
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
    snapshot.schema_version !== 1
      ? snapshot.listeners.items
      : snapshot.listeners.items.filter((item) => !item.expected)
  ) : [];
  const collectedAt = snapshot ? new Date(snapshot.collected_at).getTime() : 0;
  const stale = snapshot !== null && (
    Boolean(error) || !Number.isFinite(collectedAt) || Date.now() - collectedAt > 2 * 60_000
  );
  const snapshotJson = snapshot ? JSON.stringify(snapshot, null, 2) : "";
  const issues = snapshot ? buildHostIssues(snapshot) : [];

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
          <HostVerdict snapshot={snapshot} issues={issues} />

          <HostKpiRow snapshot={snapshot} swapHistory={swapHistory} />

          <section className="host-issues" aria-labelledby="host-issues-title">
            <header>
              <h2 id="host-issues-title">Da controllare</h2>
              <span className="host-chip">{issues.length}</span>
            </header>
            <HostIssueList issues={issues} />
          </section>

          <HostConsumers snapshot={snapshot} />

          <div className="host-detail-heading">
            <span className="eyebrow">DETTAGLIO</span>
            <small>
              Contratto {snapshot.schema_version === 1 ? "v1 legacy" : `v${snapshot.schema_version}`} · Raccolta in {snapshot.duration_ms} ms
            </small>
          </div>

          <div className="host-grid">
            <HostCard title="Memoria e swap" component={snapshot.memory}>
              <dl className="host-metrics">
                <HostMetric label="Disponibile" value={`${formatSize(snapshot.memory.available_bytes)} · ${formatPercent(snapshot.memory.available_percent)}`} />
                <HostMetric label="Totale" value={formatSize(snapshot.memory.total_bytes)} />
                <HostMetric label="Swap usata" value={`${formatSize(snapshot.memory.swap_used_bytes)} · ${formatPercent(snapshot.memory.swap_used_percent)}`} />
                <HostMetric label="Swap totale" value={formatSize(snapshot.memory.swap_total_bytes)} />
              </dl>
              {snapshot.schema_version !== 1 && (
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

          <HostCard title="Policy sui processi" component={snapshot.processes}>
            <p className="host-note">
              {snapshot.processes.scanned} processi analizzati · {snapshot.processes.skipped} saltati ·{" "}
              {snapshot.processes.inaccessible} non accessibili{snapshot.processes.truncated ? " · elenco troncato" : ""}
            </p>
            {snapshot.processes.groups.length === 0 ? <p className="host-empty">Nessun gruppo disponibile.</p> : (
              <div className="host-process-list">
                {snapshot.processes.groups.map((group) => (
                  <article key={group.name}>
                    <span><strong>{group.label ?? group.name}</strong><small>{group.label ? group.name : null}</small></span>
                    <span><strong>{group.count}×</strong><small>{formatSize(group.rss_bytes)} · più vecchio {formatAge(group.oldest_age_seconds)}</small></span>
                    {snapshot.schema_version !== 1 && group.policy_status && (
                      <p className={`host-policy policy-${group.policy_status}`}>
                        Valutazione policy: {HOST_PROCESS_POLICY_LABEL[group.policy_status]}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </HostCard>

          <HostCard
            title={snapshot.schema_version !== 1 ? "Listener TCP" : "Porte inattese"}
            component={snapshot.listeners}
          >
            {displayedListeners.length === 0 ? (
              <p className="host-empty">
                {snapshot.schema_version !== 1 ? "Nessun listener TCP rilevato." : "Nessuna porta inattesa rilevata."}
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
              {snapshot.schema_version !== 1
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
            {snapshot.schema_version !== 1 && (
              <p className="host-note"><HostContainersNote snapshot={snapshot} /></p>
            )}
          </HostCard>

          {snapshot.schema_version !== 1 && snapshot.services && (
            <HostCard title="Servizi supervisionati" component={snapshot.services}>
              {!snapshot.services.available && <p className="host-empty">Stato dei servizi non disponibile.</p>}
              {snapshot.services.available && snapshot.services.items.length === 0 && (
                <p className="host-empty">Nessun servizio con una policy configurata.</p>
              )}
              {snapshot.services.items.length > 0 && (
                <div className="host-item-grid">
                  {snapshot.services.items.map((service) => (
                    <article
                      key={`${service.supervisor}-${service.label}`}
                      className={`host-item status-${hostServiceStatus(service)}`}
                    >
                      <header>
                        <strong>{service.label}</strong>
                        <HostStatusBadge status={hostServiceStatus(service)} />
                      </header>
                      <span>{HOST_SERVICE_STATE_LABEL[service.state] ?? service.state}</span>
                      <small>
                        {HOST_SUPERVISOR_LABEL[service.supervisor] ?? service.supervisor}
                        {" · "}
                        {service.priority === "essential" ? "strategico" : "non critico"}
                      </small>
                      <small>
                        {service.restarts === null ? "Riavvii non accertati" : `${service.restarts} riavvii`}
                        {" · "}
                        {service.memory_bytes === null ? "memoria non accertata" : formatSize(service.memory_bytes)}
                      </small>
                    </article>
                  ))}
                </div>
              )}
              <p className="host-note"><HostServicesNote snapshot={snapshot} /></p>
            </HostCard>
          )}

          {snapshot.schema_version === 3 && (
            <HostCard title="Scope tmux orfani" component={snapshot.tmux_orphans}>
              {!snapshot.tmux_orphans.available && (
                <p className="host-empty">Rilevamento degli orfani non disponibile.</p>
              )}
              {snapshot.tmux_orphans.available && snapshot.tmux_orphans.items.length === 0 && (
                <p className="host-empty">Nessuno scope sopravvissuto al proprio pane oltre il periodo di tolleranza.</p>
              )}
              {snapshot.tmux_orphans.items.length > 0 && (
                <div className="host-item-grid">
                  {snapshot.tmux_orphans.items.map((orphan) => (
                    <article key={orphan.pane_pid} className="host-item status-warning">
                      <header><strong>Pane PID {orphan.pane_pid}</strong><HostStatusBadge status="warning" /></header>
                      <span>{formatSize(orphan.memory_bytes)} RAM · {formatSize(orphan.swap_bytes)} swap</span>
                      <small>
                        Attivo da {formatAge(orphan.age_seconds)} · {orphan.tasks ?? "—"} processi
                        {orphan.memory_peak_bytes === null ? "" : ` · picco ${formatSize(orphan.memory_peak_bytes)}`}
                      </small>
                    </article>
                  ))}
                </div>
              )}
              <p className="host-note">
                {snapshot.tmux_orphans.scanned_scopes} scope tmux confrontati con i pane attivi; il monitor segnala soltanto e non termina processi.
              </p>
            </HostCard>
          )}

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
        </div>
      )}
    </main>
  );
}

function SessionList({
  onOpen,
  identity,
  onLogout,
}: {
  onOpen: (session: Session) => void;
  identity: Identity;
  onLogout: () => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [profile, setProfile] = useState<"shell" | "codex" | "claude" | "antigravity" | "opencode">("shell");
  const [fullPermissions, setFullPermissions] = useState(false);
  const [presets, setPresets] = useState<[string, string][]>([]);
  const [customDirectory, setCustomDirectory] = useState(false);
  const [projectQuery, setProjectQuery] = useState("");
  const [projectSort, setProjectSort] = useState<ProjectSort>("name-asc");
  const [showHelp, setShowHelp] = useState(false);
  const [showSnapshots, setShowSnapshots] = useState(false);
  const [showArchives, setShowArchives] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<Session | null>(null);
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
  const [language, setLanguage] = useState<Language>(readLanguage);
  const [openActionsId, setOpenActionsId] = useState<string | null>(null);

  function chooseLanguage(lang: Language) {
    writeLanguage(lang);
    setLanguage(lang);
  }
  const t = translations[language];
  const [providerLimits, setProviderLimits] = useState<ProviderRateLimits | null>(null);
  const [orchestratorState, setOrchestratorState] = useState<OrchestratorState | null>(null);
  const [orchestratorExpanded, setOrchestratorExpanded] = useState<boolean>(readOrchestratorExpanded());

  function toggleOrchestratorExpanded() {
    setOrchestratorExpanded((prev) => {
      const next = !prev;
      try {
        window.sessionStorage.setItem(ORCHESTRATOR_EXPANDED_KEY, String(next));
      } catch {
        // ignore storage errors
      }
      return next;
    });
  }
  const [agentStatusBySession, setAgentStatusBySession] = useState<Record<string, AgentStatus>>({});
  const [notifyEnabled, setNotifyEnabled] = useState(false);
  const [notifyError, setNotifyError] = useState("");
  const notifySupported = typeof Notification !== "undefined" && "serviceWorker" in navigator;
  const [searchQuery, setSearchQuery] = useState("");

  const compactDashboard = dashboardDensity === "compact";
  const normalizedProjectQuery = projectQuery.trim().toLocaleLowerCase();
  const masterPreset = presets.find(([label]) => label.localeCompare("master", undefined, { sensitivity: "base" }) === 0);
  const filteredAndSorted = [...presets]
    .filter(([label, path]) => `${label} ${path}`.toLocaleLowerCase().includes(normalizedProjectQuery))
    .sort(([aLabel, aPath], [bLabel, bPath]) => {
      const order = aLabel.localeCompare(bLabel) || aPath.localeCompare(bPath);
      return projectSort === "name-asc" ? order : -order;
    });
  const displayedPresets =
    masterPreset && filteredAndSorted.includes(masterPreset)
      ? [masterPreset, ...filteredAndSorted.filter((preset) => preset !== masterPreset)]
      : filteredAndSorted;

  const dashboardSessions = useMemo(() => sessions.filter((session) => !session.hidden), [sessions]);
  const hiddenSessions = useMemo(() => sessions.filter((session) => session.hidden), [sessions]);

  const filteredSessions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return dashboardSessions;
    return dashboardSessions.filter((session) => {
      const status = agentStatusBySession[session.id];
      const stateLabel = status
        ? getAgentStateLegend().find(([state]) => state === status.state)?.[1]
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
        const entries = Object.entries(config.workspace_presets).sort(([aLabel], [bLabel]) => aLabel.localeCompare(bLabel));
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

  function archiveListedSession(session: Session) {
    setError("");
    setOpenActionsId(null);
    setArchiveTarget(session);
  }

  function archivedListedSession(session: Session) {
    setSessions((items) => items.filter((item) => item.id !== session.id));
    setArchiveTarget(null);
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
        <div><span className="eyebrow">TMUX / PRIVATE NETWORK</span><h1>{t.sessions}</h1></div>
        <div className="topbar-actions">
          <button className="help-button" onClick={() => setShowHelp(true)} aria-label="Help">
            ?
          </button>
          <span className="count">
            {searchQuery.trim() ? `${filteredSessions.length}/${sessions.length}` : sessions.length}
          </span>
        </div>
      </header>
      <div className="dashboard-actions-wrap">
        <div className="dashboard-actions">
          {identity.role !== "viewer" && (
            <button
              className="new-session"
              onClick={() => setCreating((value) => !value)}
              aria-label={compactDashboard ? t.newSession : undefined}
              title={compactDashboard ? t.newSession : undefined}
            >
              {compactDashboard ? "＋" : `+ ${t.newSession}`}
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
              {compactDashboard ? (notifyEnabled ? "🔔" : "🔕") : (notifyEnabled ? t.notificationsOn : t.notificationsOff)}
            </button>
          )}
          <button
            className="snapshot-button dashboard-more-actions"
            aria-expanded={showDashboardActions}
            aria-controls="dashboard-secondary-actions"
            aria-label={compactDashboard ? (showDashboardActions ? t.lessActions : t.moreActions) : undefined}
            title={compactDashboard ? (showDashboardActions ? t.lessActions : t.moreActions) : undefined}
            onClick={() => setShowDashboardActions((value) => !value)}
          >
            {compactDashboard ? "⋯" : (showDashboardActions ? t.lessActions : t.moreActions)}
          </button>
        </div>
        {showDashboardActions && (
          <div className="dashboard-secondary-actions" id="dashboard-secondary-actions" role="group" aria-label={t.moreActions}>
            <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowPreferences(true); }} aria-label={t.settings} title={t.settings}>{compactDashboard ? "⚙" : t.settings}</button>
            <button className="snapshot-button" onClick={async () => {
              setShowDashboardActions(false);
              try {
                await logout();
              } catch { /* session clearance on failure */ }
              onLogout();
            }} aria-label={t.logout} title={t.logout}>{compactDashboard ? "⎋" : t.logout}</button>
            {identity.role !== "viewer" && (
              <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowSnapshots(true); }} aria-label={t.snapshots} title={t.snapshots}>{compactDashboard ? "◫" : t.snapshots}</button>
            )}
            {identity.role !== "viewer" && (
              <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowArchives(true); }} aria-label={t.archivedSessions} title={t.archivedSessions}>{compactDashboard ? "▣" : t.archivedSessions}</button>
            )}
            <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowHiddenSessions(true); }} aria-label={t.hiddenSessions} title={t.hiddenSessions}>{compactDashboard ? "◌" : t.hiddenSessions}</button>
            <button ref={budgetTriggerRef} className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowBudget(true); }} aria-label={t.budget} title={t.budget}>{compactDashboard ? "◔" : t.budget}</button>
            {identity.role === "admin" && (
              <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowUsers(true); }} aria-label={t.users} title={t.users}>{compactDashboard ? "♟" : t.users}</button>
            )}
            {identity.role === "admin" && (
              <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowAudit(true); }} aria-label={t.auditLogs} title={t.auditLogs}>{compactDashboard ? "≡" : t.auditLogs}</button>
            )}
            {identity.role === "admin" && (
              <button className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowBackups(true); }} aria-label={t.backups} title={t.backups}>{compactDashboard ? "⇩" : t.backups}</button>
            )}
            {identity.role === "admin" && hostObservabilityEnabled && (
              <button ref={hostTriggerRef} className="snapshot-button" onClick={() => { setShowDashboardActions(false); setShowHost(true); }} aria-label={t.host} title={t.host}>{compactDashboard ? "▥" : t.host}</button>
            )}
          </div>
        )}
      </div>
      {creating && <form className="create-form" onSubmit={async (event) => {
        event.preventDefault();
        const normalizedName = name.trim().normalize("NFC");
        if (!SESSION_NAME_PATTERN.test(normalizedName)) {
          setError(SESSION_NAME_HINT);
          return;
        }
        try {
          const effectiveProfile: SessionProfile =
            (profile === "antigravity" && fullPermissions)
              ? "antigravity_yolo"
              : (profile === "opencode" && fullPermissions)
                ? "opencode_yolo"
                : profile;
          await createSession(normalizedName, directory, effectiveProfile);
          const updatedSessions = await listSessions();
          setCreating(false); setName(""); setProfile("shell"); setFullPermissions(false); setError("");
          setSessions(updatedSessions);
          const createdSession = updatedSessions.find((session) => session.name === normalizedName);
          if (createdSession) onOpen(createdSession);
        } catch (value) {
          setError(errorMessage(value));
        }
      }}>
        <input
          required
          pattern="[\p{L}\p{N}_-]+( [\p{L}\p{N}_-]+)*"
          maxLength={64}
          title={SESSION_NAME_HINT}
          placeholder={t.sessionNamePlaceholder}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {presets.length > 0 && !customDirectory ? (
          <fieldset className="project-picker">
            <legend>{t.projectLabel}</legend>
            <div className="project-picker-toolbar">
              <input
                type="search"
                placeholder={t.projectSearchPlaceholder}
                aria-label={t.projectSearchPlaceholder}
                value={projectQuery}
                onChange={(event) => setProjectQuery(event.target.value)}
              />
              <select
                aria-label={t.projectSortLabel}
                value={projectSort}
                onChange={(event) => setProjectSort(event.target.value as ProjectSort)}
              >
                <option value="name-asc">{t.projectSortNameAsc}</option>
                <option value="name-desc">{t.projectSortNameDesc}</option>
              </select>
            </div>
            <div className="project-picker-list" role="listbox" aria-label={t.availableProjects}>
              {displayedPresets.map(([label, path]) => (
                <button
                  key={`${label}-${path}`}
                  type="button"
                  className="project-option"
                  role="option"
                  aria-selected={directory === path}
                  onClick={() => setDirectory(path)}
                >
                  <strong>{label}</strong>
                  <small>{path}</small>
                </button>
              ))}
              {displayedPresets.length === 0 && <p className="empty">{t.noProjectMatch}</p>}
            </div>
            <button type="button" className="project-custom" onClick={() => setCustomDirectory(true)}>
              {t.chooseCustomDirectory}
            </button>
          </fieldset>
        ) : (
          <div className="custom-directory-field">
            <input required placeholder={t.allowedDirPlaceholder} value={directory} onChange={(event) => setDirectory(event.target.value)} />
            {presets.length > 0 && (
              <button type="button" onClick={() => {
                if (!presets.some(([, path]) => path === directory)) setDirectory(presets[0][1]);
                setCustomDirectory(false);
              }}>{t.backToProjects}</button>
            )}
          </div>
        )}
        <select
          aria-label="Profilo sessione"
          value={profile}
          onChange={(event) => {
            setProfile(event.target.value as "shell" | "codex" | "claude" | "antigravity" | "opencode");
            setFullPermissions(false);
          }}
        >
          <option value="shell">Shell</option>
          <option value="codex">Codex</option>
          <option value="claude">Claude</option>
          <option value="antigravity">Antigravity (agy)</option>
          <option value="opencode">OpenCode</option>
        </select>
        {(profile === "antigravity" || profile === "opencode") && (
          <label className="full-permissions">
            <input
              type="checkbox"
              checked={fullPermissions}
              onChange={(event) => setFullPermissions(event.target.checked)}
            />
            {t.fullPermissionsLabel}
            <small>{t.fullPermissionsHint}</small>
          </label>
        )}
        <button type="submit">{t.createSessionBtn}</button>
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
                <p className="empty">Nessun dato provider</p>
              )}
            </article>
          ))}
        </section>
      )}
      {orchestratorState && (
        <section
          className={`orchestrator-state ${compactDashboard ? "compact" : ""} ${orchestratorExpanded ? "expanded" : "collapsed"}`}
          aria-label="Task orchestratore"
        >
          <header
            onClick={toggleOrchestratorExpanded}
            className="orchestrator-header-toggle"
            role="button"
            tabIndex={0}
            aria-expanded={orchestratorExpanded}
            aria-label="Espandi o comprimi elenco task schedulati"
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                toggleOrchestratorExpanded();
              }
            }}
          >
            <div className="orchestrator-header-title">
              <strong>{compactDashboard ? "Task" : "Task schedulati"}</strong>
              <small>
                {compactDashboard
                  ? orchestratorState.tasks.length
                  : `${orchestratorState.tasks.length} attivi · aggiornato ${formatDate(orchestratorState.collected_at)}`}
              </small>
            </div>
            <span className="orchestrator-toggle-icon" aria-hidden="true">
              {orchestratorExpanded ? "▲" : "▼"}
            </span>
          </header>
          {orchestratorExpanded && !compactDashboard && (
            orchestratorState.tasks.length === 0 ? (
              <small className="orchestrator-empty">Nessun task schedulato attivo.</small>
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
            )
          )}
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
        {visibleSessions.map((session) => {
          const isYolo = isYoloSession(session);
          const iconAccent = sessionIconAccent(session.current_command);
          return (
          <article className={`session-item${isYolo ? " yolo" : ""}`} key={session.id}>
            <div className="session-row">
              <button className="session-card" onClick={() => onOpen(session)}>
                <span className={`session-icon${iconAccent ? ` session-icon--${iconAccent}` : ""}`}>
                  <SessionIcon cmd={session.current_command} />
                </span>
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
                        {agentStatusBySession[session.id].subagent_count > 0 && (
                          <span
                            className="subagent-badge"
                            aria-label={`${agentStatusBySession[session.id].subagent_count} subagent attivi`}
                            title={`${agentStatusBySession[session.id].subagent_count} subagent attivi`}
                          >
                            ◯{agentStatusBySession[session.id].subagent_count}
                          </span>
                        )}
                      </>
                    )}
                    {isYolo && (
                      <span
                        className="yolo-pill"
                        title={t.yoloTitle}
                        aria-label={t.yoloTitle}
                      >
                        {yoloLabel()}
                      </span>
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
                    {agentStatusBySession[session.id]?.model && (
                      <span className="agent-model">
                        {agentStatusBySession[session.id].model}
                      </span>
                    )}
                    {" · "}{formatRelativeActivity(
                      agentStatusBySession[session.id]?.content_changed_at ?? session.activity_at,
                      language,
                    )}
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
          );
        })}
        {!error && dashboardSessions.length === 0 && <p className="empty">Nessuna sessione visibile sulla dashboard.</p>}
        {!error && !compactDashboard && dashboardSessions.length > 0 && filteredSessions.length === 0 && (
          <p className="empty">Nessuna sessione corrisponde alla ricerca.</p>
        )}
      </section>
      <footer className="agent-legend" aria-label="Legenda stati agentici">
        <section>
          <strong>Stato agente</strong>
          <div>
            {getAgentStateLegend().map(([state, label]) => (
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
            {getPermissionStateLegend().map(([state, label]) => (
              <span key={state}>
                <i className={`permission-state ${state}`} aria-hidden="true">
                  {PERMISSION_STATE_ICON[state]}
                </i>
                {label}
              </span>
            ))}
            <span>
              <i className="yolo-pill" aria-hidden="true">{yoloLabel()}</i>
              {t.yoloTitle}
            </span>
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
          language={language}
          onLanguageChange={chooseLanguage}
        />
      )}
      {showArchives && (
        <ArchiveModal
          onClose={() => setShowArchives(false)}
          onRestored={refreshSessions}
        />
      )}
      {archiveTarget && (
        <ArchiveSessionModal
          session={archiveTarget}
          onClose={() => setArchiveTarget(null)}
          onArchived={archivedListedSession}
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
  const [showToolsActions, setShowToolsActions] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [changingModel, setChangingModel] = useState(false);
  const [sendingArtifactPrompt, setSendingArtifactPrompt] = useState(false);
  const [sendingArchiveSummaryPrompt, setSendingArchiveSummaryPrompt] = useState(false);
  const [showDirectory, setShowDirectory] = useState(false);
  const [showArtifacts, setShowArtifacts] = useState(false);
  const [fullscreenOutput, setFullscreenOutput] = useState(false);
  const [controlError, setControlError] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachmentError, setAttachmentError] = useState("");
  const [panes, setPanes] = useState<Pane[]>([]);
  const [paneId, setPaneId] = useState("");
  const [closingPane, setClosingPane] = useState(false);
  const agentic = /codex|claude|agy|antigravity/i.test(session.current_command);
  const claude = /claude/i.test(session.current_command);
  // La vista Blocchi di OpenCode è una trasformazione client-side dello
  // snapshot tmux (vedi opencodeChatBlocks). Con il classificatore backend
  // di OC-03 disponibile, anche lo stato agentico e i pulsanti Compact/Clear
  // (comandi TUI validi per OpenCode) si attivano; restano invece escluse le
  // quote provider, perché OpenCode non ha una finestra di rate limit
  // attribuita (nessun modello provider).
  const opencode = /opencode/i.test(session.current_command);
  const agenticStatus = agentic || opencode;
  const agenticView = agenticStatus;
  const [historyEnabled, setHistoryEnabled] = useState(false);
  const [history, setHistory] = useState<ClaudeHistory | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [copiedAgentBlock, setCopiedAgentBlock] = useState("");
  const [outputMode, setOutputMode] = useState<"terminal" | "blocks" | "history">(
    agenticView ? readDefaultAgentView() : "terminal",
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

  const { openPreviewWindow } = usePreviewWindows();

  async function openBlockPreview(path: string) {
    setControlError("");
    try {
      const metadata = await fetchFileMetadata(session.id, path);
      openPreviewWindow({
        resolveSource: () => filePreviewSource(session.id, metadata.path, metadata.modified_at, metadata.media_type),
        siblings: [metadata.path],
        initialPath: metadata.path,
      });
    } catch (value) {
      setControlError(errorMessage(value));
    }
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
    if (!agenticStatus && !showSwitcher) return;
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
  }, [agenticStatus, showSwitcher]);

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
    // ADR 007 addendum "Blocchi usa la cronologia nativa quando disponibile":
    // la stessa cronologia serve sia il tab Cronologia sia, quando c'è testo
    // reale, il tab Blocchi al posto dello stream tmux (schermo alternativo,
    // poche righe). Terminale resta sempre e solo sullo stream tmux.
    if ((outputMode !== "history" && outputMode !== "blocks") || !historyEnabled) return;
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

  const [opencodeHistory, setOpencodeHistory] = useState<OpencodeHistory | null>(null);
  const [opencodeHistoryEnabled, setOpencodeHistoryEnabled] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!opencode) return;
    fetchConfig()
      .then((config) => {
        if (!cancelled && config.opencode_history_enabled !== undefined) {
          setOpencodeHistoryEnabled(config.opencode_history_enabled);
        }
      })
      .catch(() => {
        if (!cancelled) setOpencodeHistoryEnabled(false);
      });
    return () => { cancelled = true; };
  }, [opencode]);

  useEffect(() => {
    if (!opencode || outputMode !== "blocks" || !opencodeHistoryEnabled) return;
    let cancelled = false;
    let timer: number | undefined;
    const refresh = () => {
      fetchOpencodeHistory(session.id)
        .then((result) => {
          if (cancelled) return;
          setOpencodeHistory(result);
        })
        .catch((value) => {
          if (cancelled) return;
          if (value instanceof ApiError && value.status === 404) {
            setOpencodeHistoryEnabled(false);
            return;
          }
        })
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(refresh, 3000);
        });
    };
    refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [opencode, opencodeHistoryEnabled, outputMode, session.id]);

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

  // Swipe naturale in vista Terminale -> scroll-wheel remoto sul pane
  // (POST .../scroll). Non tocca il buffer locale di xterm.js né la
  // scrollback di tmux: manda eventi di rotellina al processo nel pane
  // (es. il pager interno di Claude Code), che li interpreta e ridisegna la
  // propria schermata; il nuovo contenuto arriva al prossimo snapshot via
  // WebSocket, esattamente come per il resto di questa vista.
  //
  // È un meccanismo AGGIUNTIVO rispetto al load-more esistente sopra
  // (terminal.onScroll/historyExhaustedRef, righe ~5943-5960), non un suo
  // sostituto: quello resta il modo per rivedere storico locale già
  // scaricato ma non ancora visibile. Per evitare che i due si pestino i
  // piedi durante un drag touch, usiamo lo spazio di scroll nativo residuo
  // di `.xterm-viewport` come discriminante: se c'è ancora storico locale
  // da rivelare in quella direzione lasciamo fare lo scroll nativo (che
  // alimenta il meccanismo esistente) e non chiamiamo l'endpoint; solo
  // quando il buffer locale non ha più margine (tipicamente un pane in
  // alt-screen come Claude Code, dove non esiste scrollback tmux e
  // historyExhaustedRef è già true) il drag pilota il pane remoto, con
  // preventDefault per bloccare anche il bounce/pull-to-refresh nativo
  // della pagina durante il gesto.
  useEffect(() => {
    if (outputMode !== "terminal") return;
    const container = terminalContainerRef.current;
    if (!container) return;

    let dragging = false;
    let lastY = 0;
    // Pixel di drag accumulati da inizio gesto (o dall'ultimo invio):
    // positivo = dito trascinato verso il basso. Si svuota a soglie di
    // SWIPE_PX_PER_TICK, non tutto insieme al rilascio del dito.
    let accumPx = 0;

    // deltaSign>0 = drag verso il basso (rivelerebbe contenuto sopra, come
    // uno scroll-up nativo): c'è ancora spazio locale se .xterm-viewport
    // non è già in cima e lo storico caricato non è esaurito. deltaSign<0 =
    // drag verso l'alto: c'è spazio se il viewport non è già in fondo.
    const hasLocalScrollRoom = (deltaSign: number): boolean => {
      const viewport = container.querySelector<HTMLElement>(".xterm-viewport");
      if (!viewport) return false;
      if (deltaSign > 0) return !historyExhaustedRef.current && viewport.scrollTop > 0;
      return viewport.scrollTop + viewport.clientHeight < viewport.scrollHeight - 1;
    };

    const flushTicks = () => {
      const ticks = Math.trunc(Math.abs(accumPx) / SWIPE_PX_PER_TICK);
      if (ticks <= 0) return;
      const direction: "up" | "down" = accumPx > 0 ? "up" : "down";
      const sentTicks = Math.min(SWIPE_MAX_TICKS_PER_REQUEST, ticks);
      accumPx -= Math.sign(accumPx) * sentTicks * SWIPE_PX_PER_TICK;
      scrollPane(session.id, direction, sentTicks, paneId || undefined).catch((value) => {
        setControlError(errorMessage(value));
      });
    };

    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      dragging = true;
      lastY = event.touches[0].clientY;
      accumPx = 0;
    };

    const onTouchMove = (event: TouchEvent) => {
      if (!dragging || event.touches.length !== 1) return;
      const y = event.touches[0].clientY;
      const delta = y - lastY;
      lastY = y;
      if (delta === 0) return;
      if (hasLocalScrollRoom(delta)) {
        // Storico locale ancora disponibile in quella direzione: lascia
        // fare lo scroll nativo (alimenta terminal.onScroll più sopra),
        // niente preventDefault e nessuna chiamata remota per questo evento.
        accumPx = 0;
        return;
      }
      // Niente altro da scrollare localmente: il drag pilota il pane
      // remoto. preventDefault richiede il listener { passive: false }.
      event.preventDefault();
      accumPx += delta;
      flushTicks();
    };

    const endDrag = () => {
      dragging = false;
      accumPx = 0;
    };

    const onWheel = (event: WheelEvent) => {
      // Trackpad/mouse (l'app gira anche da browser desktop): nessun
      // preventDefault, lo scroll nativo di .xterm-viewport resta
      // invariato; il pane remoto riceve comunque i tick in aggiunta, con
      // lo stesso accumulo a soglia del touch. deltaY>0 (wheel verso il
      // basso) = direzione "down", convenzione opposta allo swipe touch
      // perché segue la rotellina fisica, non lo scroll "naturale".
      accumPx -= event.deltaY;
      flushTicks();
    };

    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: false });
    container.addEventListener("touchend", endDrag, { passive: true });
    container.addEventListener("touchcancel", endDrag, { passive: true });
    container.addEventListener("wheel", onWheel, { passive: true });

    return () => {
      container.removeEventListener("touchstart", onTouchStart);
      container.removeEventListener("touchmove", onTouchMove);
      container.removeEventListener("touchend", endDrag);
      container.removeEventListener("touchcancel", endDrag);
      container.removeEventListener("wheel", onWheel);
    };
  }, [outputMode, session.id, paneId]);

  useEffect(() => {
    if (outputMode === "terminal") return;
    if (followingOutput && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [content, history, opencodeHistory, followingOutput, outputMode]);

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

  async function pressSpecialKey(key: "Up" | "Down" | "Left" | "Right" | "Escape" | "C-c" | "Tab" | "Shift-Tab" | "C-End") {
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

  async function runModel() {
    setChangingModel(true);
    setControlError("");
    try {
      await sendText(session.id, "/model", [], paneId || undefined);
      await sendEnter(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setChangingModel(false);
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

  async function sendArchiveSummaryInstructions() {
    setSendingArchiveSummaryPrompt(true);
    setControlError("");
    try {
      await sendArchiveSummaryPrompt(session.id, paneId || undefined);
    } catch (value) {
      setControlError(errorMessage(value));
    } finally {
      setSendingArchiveSummaryPrompt(false);
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
    <main className={`console ${fullscreenOutput ? "fullscreen-console" : ""}${isYoloSession(session) ? " yolo" : ""}`}>
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
        <span className={`status ${connection}`}>{CONNECTION_LABEL[connection]}</span>
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
      </header>
      {isYoloSession(session) && (
        <div className="yolo-strip" role="status">
          {translations[readLanguage()].yoloStrip}
        </div>
      )}
      {agenticStatus && (ownStatus || ownProviderLimit) && (
        <section className="agent-info-bar" aria-label="Stato agente">
          <div className="agent-info-primary">
            {ownStatus && (
              <span className="agent-info-state" title={`${ownStatus.provider}: ${ownStatus.detail}`}>
                <i className={`agent-state ${ownStatus.state}`}>{AGENT_STATE_ICON[ownStatus.state]}</i>
                {getAgentStateLegend().find(([st]) => st === ownStatus.state)?.[1] ?? ownStatus.detail}
              </span>
            )}
            {isYoloSession(session) && (
              <span className="yolo-badge" title={translations[readLanguage()].yoloTitle}>
                {yoloLabel()}
              </span>
            )}
            {ownStatus?.context_used_percent != null && (
              <span
                className="context-badge"
                style={{
                  borderColor: rateLimitColor(ownStatus.context_used_percent),
                  color: rateLimitColor(ownStatus.context_used_percent),
                }}
                title="Finestra di contesto utilizzata"
              >
                <small className="context-label">CTX</small>
                <strong>{Math.round(ownStatus.context_used_percent)}%</strong>
              </span>
            )}
          </div>
          {ownProviderLimit?.available && ownProviderLimit.windows.length > 0 && (
            <div className="agent-info-limits">
              {ownProviderLimit.windows.map((window) => (
                <div
                  key={window.label}
                  className="agent-limit-card"
                  title={rateLimitWindowDescription(window) ?? undefined}
                >
                  <div className="agent-limit-header">
                    <span className="agent-limit-label">{window.label}</span>
                    <strong
                      className="agent-limit-value"
                      style={{ color: rateLimitColor(window.used_percent) }}
                    >
                      {window.used_percent === null ? "n/d" : `${Math.round(window.used_percent)}%`}
                    </strong>
                  </div>
                  {formatRateLimitReset(window.resets_at) && (
                    <small className="agent-info-reset">reset {formatRateLimitReset(window.resets_at)}</small>
                  )}
                </div>
              ))}
            </div>
          )}
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
          <section className="session-switcher" role="dialog" aria-modal="true" aria-label={translations[readLanguage()].switchSession}>
            <header>
              <strong>{translations[readLanguage()].sessions}</strong>
              <button className="modal-close" onClick={() => setShowSwitcher(false)} aria-label={translations[readLanguage()].close}>×</button>
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
                      {isYoloSession(item) && (
                        <span className="yolo-pill compact" title={translations[readLanguage()].yoloTitle}>
                          {yoloLabel()}
                        </span>
                      )}
                    </strong>
                    <small>{item.current_command}</small>
                  </span>
                </button>
              ))}
              {switcherSessions.length === 0 && <p className="empty">{translations[readLanguage()].noSessions}</p>}
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
            {agenticView && (
              <span className="output-mode" role="group" aria-label="Vista output">
                <button
                  type="button"
                  aria-pressed={outputMode === "blocks"}
                  onClick={() => setOutputMode("blocks")}
                >
                  {translations[readLanguage()].blocks}
                </button>
                <button
                  type="button"
                  aria-pressed={outputMode === "terminal"}
                  onClick={() => setOutputMode("terminal")}
                >
                  {translations[readLanguage()].terminal}
                </button>
                {claude && historyEnabled && (
                  <button
                    type="button"
                    aria-pressed={outputMode === "history"}
                    onClick={() => setOutputMode("history")}
                  >
                    {translations[readLanguage()].history}
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
        ) : outputMode === "blocks" && agenticView ? (
          <div
            ref={(element) => { outputRef.current = element; }}
            className="output chat-blocks"
            onScroll={updateScrollMode}
          >
            {opencode && opencodeHistory && opencodeHistory.blocks.length > 0 ? (
              opencodeHistory.blocks.map((block, index) => (
                <ChatBlockItem
                  key={block.id || `${index}-${block.content.slice(0, 20)}`}
                  block={{
                    kind: block.kind,
                    content: block.content,
                    collapsed: block.content.length > BLOCK_COLLAPSE_THRESHOLD,
                  }}
                  index={index}
                  provider={session.current_command}
                  onCopy={copyAgentBlock}
                  copiedKey={copiedAgentBlock}
                  onPreviewPath={(path) => void openBlockPreview(path)}
                />
              ))
            ) : claude && historyEnabled && history && history.messages.length > 0 ? (
              // ADR 007 addendum: storico reale (JSONL nativo) al posto dello
              // stream tmux, che a schermo alternativo mostra solo le poche
              // righe visibili. Compromesso accettato: niente tool
              // input/output (esclusi dal collector, ADR 007 punto 3), solo
              // il nome del tool per le voci "activity" — meno dettaglio
              // dello stream live, molto più storico.
              history.messages.map((message, index) => (
                <ChatBlockItem
                  key={message.id}
                  block={{
                    kind: message.kind === "activity" ? "activity" : message.role === "user" ? "user" : "agent",
                    content: message.kind === "activity"
                      ? `${message.pending ? "⏳ " : "🔧 "}${message.content}${message.pending ? " (in corso o in attesa di conferma)" : ""}`
                      : message.content,
                    collapsed: message.content.length > BLOCK_COLLAPSE_THRESHOLD,
                  }}
                  index={index}
                  provider={session.current_command}
                  onCopy={copyAgentBlock}
                  copiedKey={copiedAgentBlock}
                  onPreviewPath={(path) => void openBlockPreview(path)}
                />
              ))
            ) : content ? (
              chatBlocks(content, session.current_command).map((block, index) => (
                <ChatBlockItem
                  key={`${index}-${block.content.slice(0, 20)}`}
                  block={block}
                  index={index}
                  provider={session.current_command}
                  onCopy={copyAgentBlock}
                  copiedKey={copiedAgentBlock}
                  onPreviewPath={(path) => void openBlockPreview(path)}
                />
              ))
            ) : (
              <p className="output-waiting">In attesa dell'output…</p>
            )}
          </div>
        ) : (
          <div className="output terminal-xterm" ref={terminalContainerRef} />
        )}
        {outputMode === "terminal" && terminalLoading && (
          <p className="output-waiting terminal-loading">{translations[readLanguage()].loadingTerminal}</p>
        )}
        {outputMode === "terminal" && loadingMoreHistory && (
          <div className="history-loading" role="status">{translations[readLanguage()].loadingHistory}</div>
        )}
        {!followingOutput && (
          <button className="follow-output" type="button" onClick={resumeFollowingOutput}>
            ↓ {translations[readLanguage()].followOutput}
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
          placeholder={translations[readLanguage()].promptPlaceholder}
          rows={3}
          maxLength={65536}
          disabled={connection === "closed"}
        />
        <input
          ref={fileInputRef}
          className="file-input"
          type="file"
          multiple
          accept=".csv,.json,.md,.markdown,.mp3,.pdf,.txt,.xml,audio/mpeg,image/jpeg,image/png,image/webp"
          onChange={(event) => void selectFiles(event.target.files)}
        />
        {showSpecialKeys && (
          <div className="special-actions" aria-label={translations[readLanguage()].specialFunctions}>
            <div className="special-section">
              <button
                type="button"
                className="special-section-toggle"
                aria-expanded={showToolsActions}
                onClick={() => setShowToolsActions((value) => !value)}
              >
                <span className="special-section-title">{translations[readLanguage()].toolsAndActions}</span>
                <svg
                  className={`special-chevron ${showToolsActions ? "expanded" : ""}`}
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  focusable="false"
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              {showToolsActions && (
                <div className="special-grid">
                  <button
                    disabled={connection === "closed"}
                    type="button"
                    onClick={() => setShowDirectory(true)}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    </svg>
                    <span>{translations[readLanguage()].directoryContentBtn}</span>
                  </button>
                  <button
                    disabled={connection === "closed"}
                    type="button"
                    onClick={() => setShowArtifacts(true)}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                      <line x1="12" y1="22.08" x2="12" y2="12" />
                    </svg>
                    <span>{translations[readLanguage()].artifactsBtn}</span>
                  </button>
                  <button
                    disabled={connection === "closed" || sendingArtifactPrompt}
                    type="button"
                    onClick={() => void sendArtifactInstructions()}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span>{sendingArtifactPrompt ? translations[readLanguage()].sendingInstructions : translations[readLanguage()].deliverArtifactBtn}</span>
                  </button>
                  {agenticStatus && (
                    <>
                      <button
                        disabled={connection === "closed" || sendingArchiveSummaryPrompt}
                        type="button"
                        onClick={() => void sendArchiveSummaryInstructions()}
                      >
                        <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                          <line x1="16" y1="13" x2="8" y2="13" />
                          <line x1="16" y1="17" x2="8" y2="17" />
                          <polyline points="10 9 9 9 8 9" />
                        </svg>
                        <span>{sendingArchiveSummaryPrompt ? "Invio richiesta…" : "Prepara riepilogo archivio"}</span>
                      </button>
                      <button
                        disabled={connection === "closed" || compacting || clearing || changingModel}
                        type="button"
                        className="command"
                        onClick={() => void runCompact()}
                      >
                        <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <polyline points="4 14 10 14 10 20" />
                          <polyline points="20 10 14 10 14 4" />
                          <line x1="14" y1="10" x2="21" y2="3" />
                          <line x1="3" y1="21" x2="10" y2="14" />
                        </svg>
                        <span>{compacting ? "Compact…" : "Compact"}</span>
                      </button>
                      <button
                        disabled={connection === "closed" || compacting || clearing || changingModel}
                        type="button"
                        className="command"
                        onClick={() => void runClear()}
                      >
                        <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                        <span>{clearing ? "Clear…" : "Clear"}</span>
                      </button>
                      <button
                        disabled={connection === "closed" || compacting || clearing || changingModel}
                        type="button"
                        className="command"
                        onClick={() => void runModel()}
                      >
                        <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                          <rect x="4" y="4" width="16" height="16" rx="2" />
                          <rect x="9" y="9" width="6" height="6" />
                          <line x1="9" y1="1" x2="9" y2="4" />
                          <line x1="15" y1="1" x2="15" y2="4" />
                          <line x1="9" y1="20" x2="9" y2="23" />
                          <line x1="15" y1="20" x2="15" y2="23" />
                          <line x1="20" y1="9" x2="23" y2="9" />
                          <line x1="20" y1="14" x2="23" y2="14" />
                          <line x1="1" y1="9" x2="4" y2="9" />
                          <line x1="1" y1="14" x2="4" y2="14" />
                        </svg>
                        <span>{changingModel ? "Model…" : "Model"}</span>
                      </button>
                    </>
                  )}
                  {(session.current_command.toLowerCase().includes("claude")
                    || /agy|antigravity/i.test(session.current_command)) && (
                    <button
                      disabled={connection === "closed"}
                      type="button"
                      className="command"
                      onClick={() => void pressSpecialKey("Shift-Tab")}
                    >
                      <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                      </svg>
                      <span>{/agy|antigravity/i.test(session.current_command) ? "AGY" : "Claude"} · {translations[readLanguage()].changePermissions}</span>
                    </button>
                  )}
                  {session.current_command.toLowerCase().includes("codex") && (
                    <button
                      disabled={connection === "closed"}
                      type="button"
                      className="command"
                      onClick={() => void openCodexPermissions()}
                    >
                      <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                      </svg>
                      <span>Codex · {translations[readLanguage()].permissions}</span>
                    </button>
                  )}
                  {panes.length > 1 && (
                    <button
                      disabled={connection === "closed" || closingPane || !paneId}
                      type="button"
                      className="danger"
                      onClick={() => void closePane()}
                    >
                      <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                      <span>{closingPane ? translations[readLanguage()].closingPane : translations[readLanguage()].closePane}</span>
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="special-section">
              <span className="special-section-title">{translations[readLanguage()].terminalKeys}</span>
              <div className="special-keys-grid">
                <button
                  disabled={connection === "closed"}
                  type="button"
                  aria-label="Up"
                  title="Up (↑)"
                  onClick={() => void pressSpecialKey("Up")}
                >
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
                <button
                  disabled={connection === "closed"}
                  type="button"
                  aria-label="Down"
                  title="Down (↓)"
                  onClick={() => void pressSpecialKey("Down")}
                >
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <polyline points="19 12 12 19 5 12" />
                  </svg>
                </button>
                <button
                  disabled={connection === "closed"}
                  type="button"
                  aria-label="Left"
                  title="Left (←)"
                  onClick={() => void pressSpecialKey("Left")}
                >
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <line x1="19" y1="12" x2="5" y2="12" />
                    <polyline points="12 19 5 12 12 5" />
                  </svg>
                </button>
                <button
                  disabled={connection === "closed"}
                  type="button"
                  aria-label="Right"
                  title="Right (→)"
                  onClick={() => void pressSpecialKey("Right")}
                >
                  <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <line x1="5" y1="12" x2="19" y2="12" />
                    <polyline points="12 5 19 12 12 19" />
                  </svg>
                </button>
                {outputMode === "terminal" && (
                  <button
                    disabled={connection === "closed"}
                    type="button"
                    aria-label="Vai in fondo (Ctrl+End)"
                    title="Torna in fondo alla cronologia del pane (Ctrl+End)"
                    onClick={() => void pressSpecialKey("C-End")}
                  >
                    <svg className="action-icon-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <line x1="12" y1="3" x2="12" y2="17" />
                      <polyline points="6 11 12 17 18 11" />
                      <line x1="5" y1="21" x2="19" y2="21" />
                    </svg>
                  </button>
                )}
                <button
                  disabled={connection === "closed"}
                  type="button"
                  aria-label="Tab"
                  title="Tab"
                  onClick={() => void pressSpecialKey("Tab")}
                >
                  Tab
                </button>
                <button
                  disabled={connection === "closed"}
                  type="button"
                  aria-label="Escape"
                  title="Escape"
                  onClick={() => void pressSpecialKey("Escape")}
                >
                  Esc
                </button>
                <button
                  disabled={connection === "closed"}
                  type="button"
                  className="danger"
                  aria-label="Ctrl-C"
                  title="Ctrl-C (Interrompi)"
                  onClick={() => void pressSpecialKey("C-c")}
                >
                  Ctrl-C
                </button>
              </div>
            </div>
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
            className={`secondary special-toggle${showSpecialKeys ? " active" : ""}`}
            disabled={connection === "closed"}
            aria-expanded={showSpecialKeys}
            aria-label={translations[readLanguage()].specialFunctions}
            onClick={() => {
              setShowSpecialKeys((value) => {
                if (!value) setShowToolsActions(false);
                return !value;
              });
            }}
          >
            <svg className="action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          <button
            type="button"
            className="secondary attach-button"
            disabled={connection === "closed" || uploading || attachments.length >= 5}
            aria-label={translations[readLanguage()].attach}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? translations[readLanguage()].loading : (
              <svg className="action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            )}
          </button>
          <button
            type="button"
            className="secondary enter-button"
            disabled={connection === "closed"}
            aria-label="Enter"
            onClick={() => void pressEnter()}
          >
            <svg className="action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
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
            {translations[readLanguage()].sendText}
          </button>
        </div>
        {controlError && <small className="attachment-error">{controlError}</small>}
        {attachmentError && <small className="attachment-error">{attachmentError}</small>}
        <small>{translations[readLanguage()].textNoEnterHint}</small>
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
      : <SessionList identity={identity} onOpen={openSession} onLogout={() => setIdentity(null)} />;
  }
  return (
    <PreviewWindowsProvider active={identity != null}>
      <>
        {!online && (
          <p className="offline-banner" role="status">
            Connessione assente: in attesa di rete, alcune funzioni sono sospese.
          </p>
        )}
        {content}
      </>
    </PreviewWindowsProvider>
  );
}
