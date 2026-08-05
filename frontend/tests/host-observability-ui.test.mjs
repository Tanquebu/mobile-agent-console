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
    "Da controllare",
    "Memoria e swap",
    "Filesystem",
    "Policy sui processi",
    "Porte inattese",
    "Container problematici",
    "ultima fotografia valida",
    "Dati non recenti",
  ]) assert.ok(hostView.includes(text), `testo mancante: ${text}`);
  assert.match(app, /<h2 id="host-consumers-title">Chi consuma<\/h2>/);
  assert.match(app, /<span className="eyebrow">VERDETTO<\/span>/);
});

test("il verdetto riporta lo stato del collector senza riscriverlo", () => {
  const verdict = app.slice(app.indexOf("function hostVerdictHeadline("), app.indexOf("function HostKpi("));
  assert.match(verdict, /if \(snapshot\.status === "critical"\)/);
  assert.match(verdict, /if \(snapshot\.status === "warning"\)/);
  assert.match(verdict, /if \(snapshot\.status === "unknown"\) return "Fotografia incompleta"/);
  // il badge continua a mostrare l'esito del collector, non una rilettura
  assert.match(verdict, /HOST_STATUS_LABEL\[snapshot\.status\]/);
  assert.match(verdict, /className=\{`host-verdict status-\$\{snapshot\.status\}`\}/);
  assert.match(hostView, /<HostVerdict snapshot=\{snapshot\} issues=\{issues\}/);
});

test("swap occupata e swap attiva restano due cose distinte", () => {
  const idle = app.slice(app.indexOf("function hostSwapIdle("), app.indexOf("function buildHostIssues("));
  // senza campione non si può dedurre inattività: v1 e sample assente sono falsi
  assert.match(idle, /if \(snapshot\.schema_version !== 2\) return false/);
  assert.match(idle, /sample\.available && sample\.pages_in_delta === 0 && sample\.pages_out_delta === 0/);
  assert.match(app, /memoria parcheggiata, non un collo di bottiglia/);
  assert.match(app, /tag=\{idle \? "Inattiva" : undefined\}/);
  assert.match(styles, /\.host-meter i\.idle \{ background: repeating-linear-gradient/);
  assert.match(app, /"Attività non accertata: campione non disponibile"/);
  assert.match(app, /"Attività non campionata su snapshot v1"/);
});

test("la classifica per swap non è derivata da quella per memoria", () => {
  assert.match(api, /top_swap\?: HostProcessItem\[\]/);
  assert.match(api, /swap_attributed_bytes\?: number \| null/);
  const consumers = app.slice(app.indexOf("function HostConsumers("), app.indexOf("function HostStatusBadge("));
  assert.match(consumers, /snapshot\.schema_version === 2 \? snapshot\.processes\.top_swap \?\? \[\] : \[\]/);
  assert.match(consumers, /tab === "rss" \? snapshot\.processes\.top : tab === "swap" \? swapRanking/);
  // swap non accertata non diventa mai zero
  assert.match(consumers, /swap_bytes === undefined \|\| \w+\.swap_bytes === null \? "n\/a"/);
  assert.match(consumers, /Snapshot legacy v1: la swap per processo non è raccolta/);
  assert.match(consumers, /Swap attribuita ai processi osservati/);
  assert.match(consumers, /non è attribuibile/);
});

test("la memoria per container è mostrata con la sua età", () => {
  assert.match(api, /containers\?: Array<\{\s*label: string;\s*memory_bytes: number \| null;/);
  assert.match(api, /state_age_seconds\?: number \| null/);
  const consumers = app.slice(app.indexOf("function HostConsumers("), app.indexOf("function HostStatusBadge("));
  assert.match(consumers, /snapshot\.schema_version === 2 \? snapshot\.docker\.containers \?\? \[\] : \[\]/);
  // container fermo: nessuna memoria campionata, mai zero
  assert.match(consumers, /container\.memory_bytes === null \? "—"/);
  assert.match(consumers, /!snapshot\.docker\.available \?/);
  const note = app.slice(app.indexOf("function HostContainersNote("), app.indexOf("type HostConsumerTab"));
  assert.match(note, /Stato Docker raccolto \$\{formatAge\(age\)\} fa, non all'apertura di questa pagina/);
  assert.match(note, /Età dello stato Docker non accertata/);
  assert.match(note, /container senza label configurata non sono elencati/);
  assert.match(app, /docker_state_stale: "Stato Docker non aggiornato"/);
});

test("la priorità decide se un container fermo è un allarme o una decisione", () => {
  assert.match(api, /priority: "essential" \| "optional"/);
  const issues = app.slice(app.indexOf("function buildHostIssues("), app.indexOf("function hostIssueHint("));
  // un servizio non critico fermo non produce reason nel collector: la riga
  // esiste solo perché l'utente deve poter decidere quando riavviarlo
  assert.match(issues, /container\.priority !== "optional" \|\| container\.state === "running"\) continue/);
  assert.match(issues, /severity: "info"/);
  assert.match(app, /puoi riavviarlo quando non ci sono sessioni pesanti in corso/);
  assert.match(app, /essential_container_down: "Servizio strategico non attivo"/);
  // info non viene conteggiato fra le segnalazioni da gestire
  const verdict = app.slice(app.indexOf("function HostVerdict("), app.indexOf("function HostKpi("));
  assert.match(verdict, /info: issues\.filter\(\(issue\) => issue\.severity === "info"\)\.length/);
  assert.match(verdict, /\{counts\.info\} non critici fermi/);
  // lo stesso stato è rosso per uno strategico e informativo per uno opzionale
  assert.match(styles, /\.host-container-state\.priority-optional:not\(\.state-running\)[^{]*\{ color: #8ec7e8/);
  assert.match(styles, /\.host-container-state\.priority-essential:not\(\.state-running\)[^{]*\{ color: #ffaaa0/);
  // non accertato non è un allarme: resta neutro qualunque sia la priorità
  assert.match(styles, /\.host-container-state\.state-unknown \{ color: #a8b6ac/);
  assert.match(styles, /priority-essential:not\(\.state-running\):not\(\.state-starting\):not\(\.state-unknown\)/);
});

test("i servizi supervisionati distinguono fermo, sparito e non accertato", () => {
  assert.match(api, /supervisor: "systemd_system" \| "systemd_user" \| "pm2"/);
  assert.match(api, /state: "running" \| "starting" \| "stopped" \| "failed" \| "restarting" \| "absent" \| "unknown"/);
  // assente o null = raccolta non configurata, non "nessun servizio giù"
  assert.match(api, /services\?: \(HostComponent & \{/);
  const status = app.slice(app.indexOf("function hostServiceStatus("), app.indexOf("function HostServicesNote("));
  assert.match(status, /if \(service\.state === "unknown"\) return "unknown"/);
  assert.match(status, /service\.priority === "essential" \? "critical" : "warning"/);
  assert.match(app, /absent: "non esiste più"/);
  assert.match(app, /essential_service_down: "Servizio strategico non attivo"/);
  assert.match(app, /supervisor_unavailable: "Supervisore non raggiunto"/);
  assert.match(app, /non ha risposto: i suoi servizi non sono accertati, il che non vuol dire che siano caduti/);
  const issues = app.slice(app.indexOf("function buildHostIssues("), app.indexOf("function hostIssueHint("));
  // `unknown` non è "fermo" e non deve finire fra i non critici fermi
  assert.match(issues, /\|\| service\.state === "unknown"\s*\) continue/);
  const note = app.slice(app.indexOf("function HostServicesNote("), app.indexOf("type HostConsumerTab"));
  assert.match(note, /app pm2 senza policy configurata non sono elencate/);
  assert.match(note, /I riavvii sono mostrati ma non giudicati/);
  assert.match(note, /Raccolta dei servizi supervisionati non configurata/);
});

test("le tessere mostrano la misura leggibile, non tutti i valori grezzi", () => {
  const kpis = app.slice(app.indexOf("function HostKpiRow("), app.indexOf("type HostConsumerTab"));
  // il carico utile è quello normalizzato per CPU, non i tre load average
  assert.match(kpis, /label="Carico per CPU"/);
  assert.match(kpis, /value=\{load\.normalized_one === null \? "n\/d" : load\.normalized_one\.toFixed\(2\)\}/);
  assert.match(kpis, /in coda su \$\{load\.cpu_count\} CPU/);
  assert.match(kpis, /label="Memoria"/);
  assert.match(kpis, /label="Swap"/);
  assert.match(styles, /\.host-kpis \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(styles, /@media \(min-width: 720px\)[\s\S]*\.host-kpis \{ grid-template-columns: repeat\(4/);
});

test("le anomalie dicono cosa è successo e su quale soggetto", () => {
  assert.match(app, /const HOST_REASON_HINT: Record<string, string>/);
  const issues = app.slice(app.indexOf("function buildHostIssues("), app.indexOf("function hostVerdictHeadline("));
  assert.match(issues, /wildcard_listener_unexpected/);
  assert.match(issues, /Interessate: \$\{ports\.join\(", "\)\}/);
  assert.match(issues, /Interessati: \$\{volumes\.join\(", "\)\}/);
  assert.match(app, /Nessuna segnalazione: i controlli disponibili non hanno rilevato anomalie/);
});

test("la storia della swap non introduce raccolta periodica", () => {
  assert.doesNotMatch(hostView, /setInterval|setTimeout/);
  const spark = app.slice(app.indexOf("function HostSparkline("), app.indexOf("function HostIssueList("));
  assert.doesNotMatch(spark, /setInterval|setTimeout|fetch/);
  assert.match(spark, /if \(points\.length < 2\) return null/);
  assert.match(hostView, /setSwapHistory\(\(history\) => \[\.\.\.history, percentValue\]\.slice\(-12\)\)/);
});

test("il badge di stato non può stirarsi in un cerchio", () => {
  assert.match(styles, /\.host-status \{[^}]*align-self: center/);
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
