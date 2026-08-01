import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const hostView = app.slice(
  app.indexOf("function HostView("),
  app.indexOf("function SessionList("),
);
const sessionList = app.slice(
  app.indexOf("function SessionList("),
  app.indexOf("function Console("),
);

test("la vista Host è gated da ruolo admin e feature flag", () => {
  assert.match(
    app,
    /identity\.role === "admin" && hostObservabilityEnabled && \(/,
  );
  assert.match(
    app,
    /showHost && identity\.role === "admin" && hostObservabilityEnabled/,
  );
  assert.match(api, /request\("\/api\/v1\/host-observability"\)/);
});

test("Host carica on-open e manualmente senza polling", () => {
  assert.equal(hostView.match(/fetchHostObservability\(\)/g)?.length, 1);
  assert.doesNotMatch(hostView, /setInterval|setTimeout/);
  assert.match(hostView, /useEffect\(\(\) => \{[\s\S]*void refresh\(\)/);
  assert.match(hostView, /aria-label="Aggiorna osservabilità host"/);
  assert.ok(
    (sessionList.match(/if \(showHost\) return;/g)?.length ?? 0) >= 3,
    "i poll della dashboard devono fermarsi mentre Host è aperta",
  );
});

test("le richieste stale e gli update dopo unmount sono ignorati", () => {
  assert.match(hostView, /const mounted = useRef\(false\)/);
  assert.match(hostView, /const requestVersion = useRef\(0\)/);
  assert.match(hostView, /version === requestVersion\.current/);
  assert.match(hostView, /mounted\.current = false/);
  assert.doesNotMatch(hostView, /setSnapshot\(null\)/);
});

test("il focus entra sul titolo Host e torna al trigger rimontato", () => {
  assert.match(hostView, /const headingRef = useRef<HTMLHeadingElement>\(null\)/);
  assert.match(
    hostView,
    /headingRef\.current\?\.focus\(\{ preventScroll: true \}\)/,
  );
  assert.match(
    hostView,
    /<h1 ref=\{headingRef\} className="host-focus-target" tabIndex=\{-1\}>Host<\/h1>/,
  );
  assert.match(sessionList, /const hostTriggerRef = useRef<HTMLButtonElement>\(null\)/);
  assert.match(sessionList, /setRestoreHostFocus\(true\);[\s\S]*setShowHost\(false\)/);
  assert.match(
    sessionList,
    /hostTriggerRef\.current\?\.focus\(\{ preventScroll: true \}\)/,
  );
  assert.match(sessionList, /ref=\{hostTriggerRef\} className="snapshot-button"/);
  assert.match(styles, /\.host-focus-target:focus \{ outline: none; \}/);
});

test("stati parziali, stale, empty e sezioni richieste restano visibili", () => {
  for (const text of [
    "STATO COMPLESSIVO",
    "Memoria e swap",
    "Filesystem",
    "Gruppi di processi",
    "Processi con più memoria",
    "Porte inattese",
    "Container problematici",
    "ultima fotografia valida",
    "Dati non recenti",
  ]) assert.ok(hostView.includes(text), `testo mancante: ${text}`);
  assert.match(hostView, /<HostReasons reasons=\{snapshot\.reasons\}/);
});

test("l'export serializza esclusivamente l'ultimo snapshot valido senza fetch", () => {
  assert.match(hostView, /JSON\.stringify\(snapshot, null, 2\)/);
  assert.match(hostView, /value=\{snapshotJson\}[\s\S]*readOnly/);
  assert.equal(hostView.match(/fetchHostObservability\(\)/g)?.length, 1);
  assert.match(
    hostView,
    /setSnapshot\(next\);[\s\S]*setCopyFeedback\(""\)/,
  );
  assert.doesNotMatch(hostView, /setSnapshot\(null\)|cmdline|hostname|container_id|container_name/);
});

test("Clipboard API ha feedback e fallback manuale senza execCommand", () => {
  assert.match(hostView, /navigator\.clipboard\?\.writeText/);
  assert.match(hostView, /writeText\(snapshotJson\)/);
  assert.match(hostView, /JSON copiato negli appunti/);
  assert.match(hostView, /textarea\.focus\(\{ preventScroll: true \}\)/);
  assert.match(hostView, /textarea\.select\(\)/);
  assert.match(hostView, /JSON selezionato/);
  assert.doesNotMatch(hostView, /execCommand/);
  assert.match(hostView, /aria-live="polite" aria-atomic="true">\{copyFeedback\}/);
});

test("la sezione JSON è espandibile, critica e mobile-safe", () => {
  assert.match(hostView, /<details[\s\S]*host-json-export/);
  assert.match(hostView, /<summary>/);
  assert.match(hostView, /snapshot\.status === "critical"[\s\S]*status-critical/);
  assert.match(hostView, /aria-label="JSON snapshot osservabilità host"/);
  assert.match(styles, /\.host-json-export \{[^}]*min-width: 0;[^}]*overflow: hidden/);
  assert.match(styles, /\.host-json-export textarea \{[^}]*width: 100%;[^}]*overflow: auto/);
  assert.match(styles, /\.host-json-export button \{[^}]*min-height: 44px/);
});

test("layout mobile-first e controlli accessibili sono dichiarati", () => {
  assert.match(styles, /\.host-topbar/);
  assert.match(styles, /\.host-grid, \.host-item-grid \{ grid-template-columns:/);
  assert.match(styles, /@media \(min-width: 720px\)/);
  assert.match(hostView, /aria-live="polite"/);
  assert.match(hostView, /role="alert"/);
  assert.match(hostView, /aria-label="Torna alle sessioni"/);
});
