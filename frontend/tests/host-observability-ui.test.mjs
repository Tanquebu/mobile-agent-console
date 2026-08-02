import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const liveProbe = readFileSync(new URL("host-observability-live.mjs", import.meta.url), "utf8");
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

test("il probe live consuma le response prima del teardown", () => {
  assert.match(liveProbe, /initialResponsePromise = page\.waitForResponse/);
  assert.match(liveProbe, /refreshResponsePromise = page\.waitForResponse/);
  assert.match(liveProbe, /await initialResponse\.json\(\)/);
  assert.match(liveProbe, /await refreshResponse\.json\(\)/);
  assert.match(liveProbe, /await refreshResponse\.finished\(\)/);
  assert.match(liveProbe, /MAC_LIVE_ITERATIONS/);
  assert.match(liveProbe, /iteration < iterations/);
  assert.match(liveProbe, /MAC_LIVE_ABORT_REFRESH/);
  assert.match(liveProbe, /await abortRequestPromise[\s\S]*await context\.close\(\)/);
  assert.doesNotMatch(liveProbe, /page\.on\("response", async/);
  assert.ok(
    liveProbe.indexOf("await refreshResponse.finished()") < liveProbe.indexOf("await context.close()"),
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

test("le sezioni Host partono chiuse e mostrano titolo e stato nel summary", () => {
  const hostCard = app.slice(app.indexOf("function HostCard("), app.indexOf("function HostMetric("));
  assert.match(hostCard, /<details className=\{`host-card status-\$\{component\.status\}`\}>/);
  assert.match(hostCard, /<summary>[\s\S]*<h2>\{title\}<\/h2>[\s\S]*<HostStatusBadge status=\{component\.status\}/);
  assert.match(hostCard, /<div className="host-card-body">/);
  assert.doesNotMatch(hostCard, /<details[^>]*\sopen(?:=|\s|>)/);
  assert.match(hostView, /<details className="host-reading-guide">[\s\S]*<summary id="host-reading-guide-title">/);
  assert.match(styles, /\.host-card > summary \{[^}]*min-height: 48px/);
  assert.match(styles, /\.host-card-body \{[^}]*border-top:/);
});

test("v1 e v2 distinguono fatti locali, valutazione e dati non accertati", () => {
  for (const text of [
    "Come leggere la fotografia",
    "Fatti locali",
    "Valutazione",
    "Non accertato",
    "v1 legacy",
    "Campione attività swap",
    "Policy locale non configurata",
    "Policy locale violata",
    "Raggiungibilità esterna: non accertata",
  ]) assert.ok(app.includes(text), `testo v1/v2 mancante: ${text}`);
  assert.match(hostView, /snapshot\.schema_version === 1 \? "v1 legacy" : "v2"/);
  assert.match(hostView, /snapshot\.schema_version === 2[\s\S]*swap_io_sample/);
  assert.match(hostView, /snapshot\.schema_version === 2[\s\S]*snapshot\.listeners\.items/);
  assert.doesNotMatch(hostView, /raggiungibil\w* (?:sicura|chiusa)|porta (?:sicura|chiusa)/i);
});

test("la valutazione senza reason è coerente con ciascuno status", () => {
  assert.match(app, /ok: "Nessuna anomalia rilevata dai controlli disponibili\."/);
  assert.match(app, /warning: "Attenzione rilevata; il collector non ha fornito un dettaglio della valutazione\."/);
  assert.match(app, /critical: "Stato critico rilevato; il collector non ha fornito un dettaglio della valutazione\."/);
  assert.match(app, /unknown: "Valutazione non disponibile: l’esito non è accertato\."/);
  assert.match(app, /HOST_EMPTY_ASSESSMENT_LABEL\[component\.status\]/);
  assert.doesNotMatch(
    app.slice(app.indexOf("const HOST_EMPTY_ASSESSMENT_LABEL"), app.indexOf("function HostStatusBadge")),
    /(?:warning|critical|unknown):[^\n]*(?:nessuna anomalia|sicuro|chiuso)/i,
  );
});

test("v2 conserva ogni bind locale e separa l'esito della policy", () => {
  assert.match(hostView, /Bind locale:/);
  assert.match(hostView, /external_reachability/);
  assert.match(hostView, /HOST_LISTENER_POLICY_LABEL\[listener\.policy_status\]/);
  assert.match(hostView, /HOST_PROCESS_POLICY_LABEL\[group\.policy_status\]/);
  assert.match(hostView, /non verifica la raggiungibilità dalla rete esterna/);
  assert.match(hostView, /snapshot\.schema_version === 2\s*\? snapshot\.listeners\.items/);
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
  assert.match(hostView, /aria-labelledby="host-reading-guide-title"/);
  assert.match(hostView, /aria-label="Campione attività swap"/);
  assert.match(styles, /\.host-process-list \.host-policy \{[^}]*grid-column: 1 \/ -1/);
  assert.match(styles, /\.host-policy, \.host-not-assessed \{[^}]*overflow-wrap: anywhere/);
});
