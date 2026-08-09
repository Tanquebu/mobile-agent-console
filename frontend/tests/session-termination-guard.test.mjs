import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// INC-HOST-01: il backend nasconde la sessione tmux di servizio (host
// keepalive / __runtime__) da list_sessions e rifiuta la sua terminazione
// anche per id noto (409, `TmuxError` con un messaggio fisso). Stessa
// convenzione delle altre suite in questa cartella: si legge il sorgente
// come testo invece di renderizzare il componente (niente jsdom qui).
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

test("errorMessage traduce il rifiuto di terminazione della sessione riservata in un messaggio comprensibile", () => {
  assert.match(
    api,
    /value\.status === 409 &&\s*\n\s*value\.message === "Refusing to terminate the reserved keepalive session"/,
  );
  assert.match(
    api,
    /"Questa sessione è riservata al servizio e non può essere terminata\."/,
  );
});

test("terminateListedSession non introduce una gestione speciale: si affida al messaggio generico di errorMessage", () => {
  const handler = app.slice(
    app.indexOf("async function terminateListedSession("),
    app.indexOf("async function archiveListedSession("),
  );
  assert.match(handler, /catch \(value\) \{\s*setError\(errorMessage\(value\)\);/);
  // Nessun id/nome riservato hardcoded lato client: la sessione non compare
  // mai nell'elenco (backend-only), quindi non serve un caso speciale qui.
  assert.doesNotMatch(handler, /keepalive|__runtime__/);
});
