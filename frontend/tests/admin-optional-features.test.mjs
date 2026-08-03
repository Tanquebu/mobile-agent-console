import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Copre BH-03: l'elenco delle funzioni opzionali attive, esposto nella vista
// Audit (già admin-only) come enunciazione di fatto, mai un giudizio su cosa
// "dovrebbe" essere acceso. Stessa convenzione di budget-view.test.mjs: si
// ritagliano le porzioni di sorgente rilevanti invece di rendere il
// componente (niente jsdom in questa suite).
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

const labelTable = app.slice(
  app.indexOf("const OPTIONAL_FEATURE_LABEL"),
  app.indexOf("function AuditModal("),
);
const auditModal = app.slice(
  app.indexOf("function AuditModal("),
  app.indexOf("function BackupModal("),
);

test("il config espone optional_features nel tipo frontend, nullable per i ruoli non-admin", () => {
  assert.match(api, /optional_features: Record<string, boolean> \| null;/);
});

test("la vista Audit carica optional_features dal config e la mostra soltanto se presente", () => {
  assert.match(auditModal, /const \[optionalFeatures, setOptionalFeatures\] = useState<Record<string, boolean> \| null>\(null\)/);
  assert.match(auditModal, /fetchConfig\(\)\s*\n\s*\.then\(\(config\) => setOptionalFeatures\(config\.optional_features\)\)/);
  assert.match(auditModal, /\{optionalFeatures && \(/);
});

test("ogni funzione opzionale è enunciata come acceso/spento, mai come ok/errore", () => {
  assert.match(auditModal, /\{enabled \? "attiva" : "disattiva"\}/);
  assert.doesNotMatch(auditModal, /optionalFeatures[\s\S]{0,400}(errore|manca|attenzione|warning|dovrebbe)/i);
});

test("le cinque funzioni opzionali del backend hanno tutte un'etichetta leggibile lato frontend", () => {
  for (const key of [
    "host_observability_enabled",
    "session_usage_enabled",
    "rate_limit_fresh_enabled",
    "claude_history_enabled",
    "database_auth_enabled",
  ]) {
    assert.match(labelTable, new RegExp(`${key}: "`), `manca l'etichetta per ${key}`);
  }
});

test("la sezione riusa classi esistenti (eyebrow) e aggiunge solo lo stile minimo per la lista, senza nuove dipendenze", () => {
  assert.match(auditModal, /<span className="eyebrow">FUNZIONI OPZIONALI<\/span>/);
  assert.match(styles, /\.audit-optional-features/);
  assert.doesNotMatch(styles, /\.audit-optional-features[\s\S]{0,300}(chart\.js|recharts|d3-)/i);
});
