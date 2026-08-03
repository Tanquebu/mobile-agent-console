import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Drill-down "fase C" (BH-04): stessa convenzione di budget-view.test.mjs e
// admin-optional-features.test.mjs — si ritagliano le porzioni di sorgente
// rilevanti per asserzioni mirate invece di rendere il componente (niente
// jsdom in questa suite).
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

const rankingItem = app.slice(
  app.indexOf("function BudgetRankingItem("),
  app.indexOf("const TOOL_CATEGORY_LABEL"),
);
const timelineModal = app.slice(
  app.indexOf("function SessionTimelineModal("),
  app.indexOf("function BudgetView("),
);
const budgetView = app.slice(
  app.indexOf("function BudgetView("),
  app.indexOf("function HostView("),
);

test("api.ts espone il tipo e la chiamata del drill-down verso l'endpoint timeline", () => {
  assert.match(api, /export type SessionTimelineWindow = \{/);
  assert.match(api, /export async function fetchSessionTimeline\(/);
  assert.match(api, /\/api\/v1\/session-usage\/timeline\?\$\{params\.toString\(\)\}/);
});

test("il config espone session_timeline_enabled come flag dedicato, non derivato da altri flag", () => {
  assert.match(api, /session_timeline_enabled: boolean;/);
});

test("SessionUsageReport include i bucket grezzi necessari a individuare il picco", () => {
  assert.match(api, /export type SessionUsageBucket = \{/);
  assert.match(api, /buckets: SessionUsageBucket\[\];/);
});

test("il bottone di drill-down compare solo quando esiste un bucket di picco (gate lato dati, non solo lato flag)", () => {
  assert.match(rankingItem, /peakBucket &&/);
  assert.match(rankingItem, /Vedi il picco dei turni/);
});

test("il picco è nascosto quando il flag è spento (calcolato lato BudgetView, mai lato modale)", () => {
  assert.match(
    budgetView,
    /peakBucket=\{\s*\n\s*sessionTimelineEnabled\s*\n\s*\? peakBucketByEntry\.get\(entry\.session_uuid\) \?\? null\s*\n\s*: null/,
  );
});

test("il bottone di drill-down rispetta il tocco minimo di 44px", () => {
  assert.match(styles, /\.budget-open-timeline \{[^}]*min-height: 44px/);
});

test("la modale del drill-down è un dialog accessibile con stato in aria-live", () => {
  assert.match(timelineModal, /role="dialog"/);
  assert.match(timelineModal, /aria-modal="true"/);
  assert.match(timelineModal, /aria-live="polite"/);
  assert.match(timelineModal, /event\.key === "Escape"/);
});

test("la modale mostra il transcript non disponibile come stato dichiarato, non come errore", () => {
  assert.match(timelineModal, /!timeline\.available/);
  assert.match(timelineModal, /non più disponibile/);
});

test("la modale non introduce mai testo di prompt/risposta/ragionamento o nomi grezzi di strumenti: solo campi del contratto BH-04", () => {
  assert.doesNotMatch(timelineModal, /\.prompt\b/);
  assert.doesNotMatch(timelineModal, /\.description\b/);
  assert.doesNotMatch(timelineModal, /\.reasoning\b/);
  assert.doesNotMatch(timelineModal, /tool_use|toolUse|rawToolName/);
  assert.doesNotMatch(timelineModal, /transcript_path|transcriptPath/);
  // I conteggi per strumento passano sempre dalla tassonomia fissa
  // (TOOL_CATEGORY_LABEL), mai un nome letto direttamente dal payload.
  assert.match(timelineModal, /TOOL_CATEGORY_LABEL\[category\]/);
});

test("le sette chiavi della tassonomia fissa hanno tutte un'etichetta leggibile", () => {
  const table = app.slice(
    app.indexOf("const TOOL_CATEGORY_LABEL"),
    app.indexOf("function SessionTimelineModal("),
  );
  for (const key of [
    "file_read",
    "file_write",
    "exec",
    "network",
    "task_management",
    "subagent_orchestration",
    "other",
  ]) {
    assert.match(table, new RegExp(`${key}: "`), `manca l'etichetta per ${key}`);
  }
});
