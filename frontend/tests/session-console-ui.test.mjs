import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const consoleView = app.slice(app.indexOf("function Console("), app.indexOf("export default function App()"));
const rootApp = app.slice(app.indexOf("export default function App()"));

test("i nomi sessione Unicode sono normalizzati e validati anche nel client", () => {
  assert.match(app, /SESSION_NAME_PATTERN = \/\^\[\\p\{L\}\\p\{N\}_-\]/);
  assert.match(app, /trim\(\)\.normalize\("NFC"\)/);
  assert.match(app, /SESSION_NAME_HINT/);
});

test("la bozza testuale resta separata per session id e non usa persistenza", () => {
  const draftState = rootApp.slice(
    rootApp.indexOf("function setSessionDraft("),
    rootApp.indexOf("useEffect(() =>", rootApp.indexOf("function setSessionDraft(")),
  );
  assert.match(rootApp, /draftsBySession/);
  assert.match(rootApp, /draft=\{draftsBySession\[active\.id\] \?\? ""\}/);
  assert.match(rootApp, /onDraftChange=\{\(draft\) => setSessionDraft\(active\.id, draft\)\}/);
  assert.match(consoleView, /value=\{draft\}[\s\S]*onChange=\{\(event\) => onDraftChange\(event\.target\.value\)\}/);
  assert.doesNotMatch(draftState, /localStorage|sessionStorage|indexedDB/);
});

test("Clear invia testo ed Enter come operazioni distinte solo nei controlli agentici", () => {
  assert.match(consoleView, /await sendText\(session\.id, "\/clear", \[\], paneId \|\| undefined\);[\s\S]*await sendEnter\(session\.id, paneId \|\| undefined\)/);
  assert.match(consoleView, /const agenticStatus = agentic \|\| opencode;/);
  assert.match(consoleView, /\{agenticStatus && \([\s\S]*onClick=\{\(\) => void runClear\(\)\}[\s\S]*\{clearing \? "Clear…" : "Clear"\}/);
  assert.match(consoleView, /disabled=\{connection === "closed" \|\| compacting \|\| clearing\}/);
  assert.doesNotMatch(consoleView, /sendText\([^\n]*"\/clear[^\n]*Enter/);
});

test("il selettore Allega abilita gli MP3", () => {
  assert.match(consoleView, /accept="[^"]*\.mp3[^"]*audio\/mpeg/);
});

test("il riepilogo archivio è richiesto all'agente con un'azione esplicita", () => {
  assert.match(consoleView, /await sendArchiveSummaryPrompt\(session\.id, paneId \|\| undefined\)/);
  assert.match(consoleView, /Prepara riepilogo archivio/);
  assert.match(consoleView, /\{agenticStatus && \([\s\S]*sendArchiveSummaryInstructions/);
});

test("la modale archivio precompila una bozza revisionabile e persiste i campi espliciti", () => {
  const archiveCreate = app.slice(
    app.indexOf("function ArchiveSessionModal("),
    app.indexOf("function ArchiveModal("),
  );
  assert.match(archiveCreate, /fetchArchiveDraft\(session\.id\)/);
  assert.match(archiveCreate, /setSummary\(draft\.summary \?\? ""\)/);
  assert.match(archiveCreate, /await archiveSession\(session\.id, agentSessionName, summary\)/);
  assert.match(archiveCreate, /maxLength=\{128\}/);
  assert.match(archiveCreate, /maxLength=\{2000\}/);
  assert.match(app, /item\.agent_session_name,[\s\S]*item\.summary,[\s\S]*item\.directory/);
});

test("le modali restano sopra la barra azioni della dashboard", () => {
  const dashboardLayer = Number(styles.match(/\.dashboard-actions-wrap \{[^}]*z-index: (\d+)/)?.[1]);
  const modalLayer = Number(styles.match(/\.modal-backdrop \{[^}]*z-index: (\d+)/)?.[1]);
  assert.ok(Number.isFinite(dashboardLayer));
  assert.ok(Number.isFinite(modalLayer));
  assert.ok(modalLayer > dashboardLayer);
});
