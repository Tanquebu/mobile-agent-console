import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const tsModule = ts.default ?? ts;

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

// Stessa convenzione di host-observability-ui.test.mjs: si ritagliano le
// porzioni di sorgente rilevanti per asserzioni mirate invece di rendere il
// componente (niente jsdom in questa suite).
const budgetModule = app.slice(
  app.indexOf("type BudgetHoursOption"),
  app.indexOf("function HostView("),
);
const budgetView = app.slice(
  app.indexOf("function BudgetView("),
  app.indexOf("function HostView("),
);
const sessionList = app.slice(
  app.indexOf("function SessionList("),
  app.indexOf("function Console("),
);
const providerChart = app.slice(
  app.indexOf("function BudgetProviderChart("),
  app.indexOf("function hasBudgetUsage("),
);

// A differenza della suite Host, qui la logica più delicata (segmentazione
// ai reset, isolamento dei tratti stantii) è in funzioni pure senza
// JSX/React: le estraiamo dal sorgente e le eseguiamo per davvero invece di
// limitarci a cercare stringhe, per verificare il comportamento e non solo
// la sua presenza testuale.
function extractFunction(source, name) {
  const marker = `function ${name}(`;
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `funzione non trovata nel sorgente: ${name}`);
  const braceStart = source.indexOf("{", start);
  let depth = 0;
  let i = braceStart;
  for (; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  assert.ok(depth === 0, `parentesi non bilanciate per ${name}`);
  return source.slice(start, i + 1);
}

function loadBudgetPureFunctions() {
  const names = [
    "budgetSeriesLabels",
    "budgetPointsForLabel",
    "buildBudgetChains",
    "growthForLabel",
    "formatSignedPercent",
    "hasBudgetUsage",
  ];
  const snippet = `${names.map((name) => extractFunction(budgetModule, name)).join("\n\n")}\nmodule.exports = { ${names.join(", ")} };\n`;
  const { outputText } = tsModule.transpileModule(snippet, {
    compilerOptions: { module: tsModule.ModuleKind.CommonJS, target: tsModule.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}

const budget = loadBudgetPureFunctions();

test("la vista Budget è raggiungibile dalla dashboard e sospende i poll come Host", () => {
  assert.match(api, /request\(`\/api\/v1\/provider-rate-limits\/history/);
  assert.match(api, /request\("\/api\/v1\/provider-rate-limits\/refresh"/);
  assert.match(api, /request\(`\/api\/v1\/session-usage/);
  assert.match(app, /setShowBudget\(true\)/);
  assert.match(sessionList, /const \[showBudget, setShowBudget\] = useState\(false\)/);
  assert.ok(
    (sessionList.match(/if \(showBudget\) return;/g)?.length ?? 0) >= 3,
    "i poll della dashboard devono fermarsi anche mentre Budget è aperta, come già avviene per showHost",
  );
});

test("lo snapshot quote espone e rende visibile il prossimo reset anche nelle viste compatte", () => {
  assert.match(api, /ProviderRateLimitWindow[\s\S]*resets_at: number \| null;/);
  assert.match(app, /function formatRateLimitReset\(value: number \| null\)/);
  assert.match(sessionList, /provider-reset[\s\S]*reset \{formatRateLimitReset\(window\.resets_at\)\}/);
  assert.match(app, /agent-info-reset[\s\S]*reset \{formatRateLimitReset\(window\.resets_at\)\}/);
  assert.match(styles, /\.provider-windows\.compact \.provider-reset/);
});

test("il focus entra sul titolo Budget e torna al trigger rimontato", () => {
  assert.match(budgetView, /const headingRef = useRef<HTMLHeadingElement>\(null\)/);
  assert.match(budgetView, /headingRef\.current\?\.focus\(\{ preventScroll: true \}\)/);
  assert.match(sessionList, /const budgetTriggerRef = useRef<HTMLButtonElement>\(null\)/);
  assert.match(sessionList, /setRestoreBudgetFocus\(true\);[\s\S]*setShowBudget\(false\)/);
  assert.match(sessionList, /budgetTriggerRef\.current\?\.focus\(\{ preventScroll: true \}\)/);
});

test("il selettore d'intervallo copre 6h/24h/7g ed è condiviso da grafico e classifica", () => {
  assert.match(
    budgetModule,
    /const BUDGET_RANGE_OPTIONS[\s\S]*\{ label: "6h", hours: 6 \}[\s\S]*\{ label: "24h", hours: 24 \}[\s\S]*\{ label: "7g", hours: 168 \}/,
  );
  assert.match(budgetView, /fetchRateLimitHistory\(rangeHours, 3000\)/);
  assert.match(budgetView, /fetchSessionUsage\(rangeHours, 50\)/);
  assert.match(budgetView, /\}, \[hours, sessionUsageEnabled\]\);/);
});

test("le richieste stale (versione) e gli update dopo unmount sono ignorati, per storico e per attribuzione", () => {
  assert.match(budgetView, /const mounted = useRef\(false\)/);
  assert.match(budgetView, /const historyVersion = useRef\(0\)/);
  assert.match(budgetView, /const usageVersion = useRef\(0\)/);
  assert.match(budgetView, /version === historyVersion\.current/);
  assert.match(budgetView, /version === usageVersion\.current/);
  assert.match(budgetView, /mounted\.current = false/);
});

test("la spezzata si interrompe quando resets_at cambia: la discesa della finestra scorrevole non è un calo di consumo", () => {
  const points = [
    { t: 1, y: 80, resetsAt: 100, stale: false },
    { t: 2, y: 90, resetsAt: 100, stale: false },
    { t: 3, y: 5, resetsAt: 200, stale: false },
    { t: 4, y: 15, resetsAt: 200, stale: false },
  ];
  const chains = budget.buildBudgetChains(points);
  assert.equal(chains.length, 2, "un cambio di resets_at deve produrre due tratti separati, non collegati");
  assert.deepEqual(chains[0].points.map((point) => point.t), [1, 2]);
  assert.deepEqual(chains[1].points.map((point) => point.t), [3, 4]);
  assert.equal(chains[0].stale, false);
  assert.equal(chains[1].stale, false);
});

test("i tratti che attraversano un campione stantio sono isolati e non interpolati come misure, ma restano a contatto nello stesso reset", () => {
  const points = [
    { t: 1, y: 10, resetsAt: 100, stale: false },
    { t: 2, y: 20, resetsAt: 100, stale: false },
    { t: 3, y: 60, resetsAt: 100, stale: true },
    { t: 4, y: 62, resetsAt: 100, stale: false },
  ];
  const chains = budget.buildBudgetChains(points);
  assert.equal(chains.length, 2);
  assert.equal(chains[0].stale, false);
  assert.deepEqual(chains[0].points.map((point) => point.t), [1, 2]);
  assert.equal(chains[1].stale, true, "il tratto che tocca il campione stantio va marcato per il tratteggio");
  assert.deepEqual(chains[1].points.map((point) => point.t), [2, 3, 4]);
  // Restano a contatto (stesso reset): l'ultimo punto del tratto osservato
  // è anche il primo del tratto stantio, nessun buco visivo.
  assert.equal(
    chains[0].points[chains[0].points.length - 1].t,
    chains[1].points[0].t,
  );
  assert.doesNotMatch(budgetView, /setSnapshot\(null\)/);
});

test("un campione con used_percent nullo non genera un punto (nessuna interpolazione a zero)", () => {
  const points = budget.budgetPointsForLabel(
    [
      { sampled_at: "2026-08-02T09:00:00Z", provider: "claude", source: "cache", observed_at: null, stale: false, windows: [{ label: "5h", used_percent: null, resets_at: 1 }], error: null },
      { sampled_at: "2026-08-02T09:05:00Z", provider: "claude", source: "cache", observed_at: null, stale: false, windows: [{ label: "5h", used_percent: 42, resets_at: 1 }], error: null },
    ],
    "5h",
  );
  assert.equal(points.length, 1);
  assert.equal(points[0].y, 42);
});

test("la crescita per il residuo è calcolata sull'ultimo reset, non sull'intero intervallo (evita di sottostimare un 5h che si è resettato più volte)", () => {
  const samples = [
    { sampled_at: "2026-08-02T00:00:00Z", provider: "claude", source: "cache", observed_at: null, stale: false, windows: [{ label: "5h", used_percent: 90, resets_at: 100 }], error: null },
    { sampled_at: "2026-08-02T01:00:00Z", provider: "claude", source: "cache", observed_at: null, stale: false, windows: [{ label: "5h", used_percent: 10, resets_at: 200 }], error: null },
    { sampled_at: "2026-08-02T02:00:00Z", provider: "claude", source: "cache", observed_at: null, stale: false, windows: [{ label: "5h", used_percent: 35, resets_at: 200 }], error: null },
  ];
  const growth = budget.growthForLabel(samples, "5h");
  assert.equal(growth, 25, "deve usare solo l'ultimo reset (200): 35 - 10, non 35 - 90 attraverso il reset");
});

test("nessuna percentuale di quota per sessione: la classifica mostra solo token, mai una stima di percentuale", () => {
  assert.match(budgetModule, /BudgetTotalsRow label="Sessione" totals=\{entry\.own\}/);
  assert.match(budgetModule, /BudgetTotalsRow label="Totale" totals=\{entry\.total\}/);
  assert.doesNotMatch(budgetModule, /used_percent.*entry\./);
  assert.match(budgetModule, /Nessuna percentuale di quota per riga/);
});

test("i subagent sono annidati sotto la sessione madre, non elencati come righe indipendenti", () => {
  const rankingItem = app.slice(app.indexOf("function BudgetRankingItem("), app.indexOf("function BudgetView("));
  assert.match(rankingItem, /<article className="budget-rank-item">/);
  // Un solo article per entry: own, subagents e total sono tutti dentro lo
  // stesso contenitore, non entry separate nella lista.
  assert.equal((rankingItem.match(/<article/g) ?? []).length, 1);
  assert.match(rankingItem, /BudgetTotalsRow label="Sessione" totals=\{entry\.own\}/);
  assert.match(
    rankingItem,
    /hasBudgetUsage\(entry\.subagents\)[\s\S]*budget-subagent-row[\s\S]*BudgetTotalsRow label="↳ Subagent" totals=\{entry\.subagents\}/,
  );
  assert.match(rankingItem, /BudgetTotalsRow label="Totale" totals=\{entry\.total\} emphasis/);
});

test("hasBudgetUsage distingue un blocco subagent vuoto da uno con attività reale", () => {
  const empty = { turns: 0, input_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 0, ranking_tokens: 0 };
  assert.equal(budget.hasBudgetUsage(empty), false);
  assert.equal(budget.hasBudgetUsage({ ...empty, output_tokens: 1 }), true);
  assert.equal(budget.hasBudgetUsage({ ...empty, turns: 1 }), true);
});

test("il collegamento alla console appare solo per origin mac con tmux_session_id mappato a una sessione viva", () => {
  const rankingItem = app.slice(app.indexOf("function BudgetRankingItem("), app.indexOf("function BudgetView("));
  assert.match(rankingItem, /entry\.tmux_session_id \? sessionsById\.get\(entry\.tmux_session_id\) : undefined/);
  assert.match(rankingItem, /entry\.origin === "mac" && linkedSession && \(/);
  assert.match(rankingItem, /onOpenSession\(linkedSession\)/);
});

test("il residuo è mostrato come voce esplicita e spiegata, mai come 'errore' né come un unico numero fabbricato fra unità incompatibili", () => {
  assert.match(budgetView, /<h3>Residuo<\/h3>/);
  assert.match(budgetView, /Crescita osservata della quota dall'ultimo reset/);
  assert.match(budgetView, /Consumo attribuito nello stesso intervallo/);
  assert.match(budgetView, /className="budget-note"/);
  assert.match(
    budgetModule,
    /non un difetto della raccolta/,
  );
  assert.doesNotMatch(budgetView, /residuo.{0,40}errore/i);
});

test("il consumo per sessione degrada in modo pulito quando l'attribuzione non è abilitata (config o 404)", () => {
  assert.match(budgetView, /if \(!sessionUsageEnabled\) \{/);
  assert.match(budgetView, /setUsageDisabled\(true\);\s*\n\s*setUsage\(null\);/);
  assert.match(budgetView, /value instanceof ApiError && value\.status === 404/);
  assert.match(budgetView, /L'attribuzione del consumo per sessione non è abilitata/);
  // Il grafico "quando" resta indipendente dallo stato di usageDisabled.
  assert.doesNotMatch(
    budgetView.slice(budgetView.indexOf('aria-label="Quando'), budgetView.indexOf('aria-label="Chi')),
    /usageDisabled/,
  );
});

test("lo storico vuoto mostra un messaggio di accumulo, non un grafico vuoto", () => {
  assert.match(
    budgetView,
    /history\.samples\.length === 0[\s\S]*i campioni si stanno accumulando/,
  );
});

test("il pulsante Aggiorna adesso è gated dal flag di config e distingue 429\\/503\\/504", () => {
  assert.match(budgetView, /\{rateLimitFreshEnabled && \(/);
  assert.match(budgetView, /Aggiorna adesso/);
  assert.match(budgetView, /value\.status === 429/);
  assert.match(budgetView, /value\.status === 503/);
  assert.match(budgetView, /value\.status === 504/);
  assert.match(budgetView, /Troppi aggiornamenti ravvicinati/);
  assert.match(budgetView, /non è raggiungibile sull'host/);
  assert.match(budgetView, /impiegato troppo tempo a rispondere/);
});

test("il colore identifica la serie e non il valore, con spessore come codifica secondaria", () => {
  // L'asse verticale codifica gia' la percentuale: colorare la linea in base
  // al valore la faceva cambiare tinta attraversando un reset, cosi' che uno
  // stesso 5h sembrasse una terza serie priva di legenda.
  assert.match(budgetModule, /stroke=\{chain\.stale \? undefined : budgetSeriesColor\(index\)\}/);
  assert.match(budgetModule, /fill=\{chain\.stale \? undefined : budgetSeriesColor\(index\)\}/);
  assert.doesNotMatch(budgetModule, /stroke=\{chain\.stale \? undefined : rateLimitColor\(/);
  // Ordine fisso, mai ciclato, e il pallino di legenda porta la stessa tinta.
  assert.match(budgetModule, /const BUDGET_SERIES_COLORS = \[/);
  assert.match(budgetModule, /style=\{\{ background: budgetSeriesColor\(index\) \}\}/);
  // Il colore non e' l'unico segnale: le serie restano distinte per spessore.
  assert.match(styles, /\.budget-line-0 \.budget-segment \{[^}]*stroke-width: 2\.6/);
  assert.match(styles, /\.budget-line-1 \.budget-segment \{[^}]*stroke-width: 1\.6/);
  assert.doesNotMatch(styles, /\.budget-line-1 \.budget-segment \{[^}]*opacity/);
});

test("i tratti stantii restano distinti nel CSS senza nuove dipendenze", () => {
  assert.match(styles, /\.budget-segment-stale \{[^}]*stroke-dasharray: 4 3/);
  assert.match(styles, /\.budget-chart svg \{[^}]*width: 100%/);
  assert.match(styles, /\.budget-range-selector/);
  assert.doesNotMatch(budgetModule, /<Line |recharts|d3-|chart\.js/i);
});

test("il config espone rate_limit_fresh_enabled e session_usage_enabled nel tipo frontend", () => {
  assert.match(api, /rate_limit_fresh_enabled: boolean;/);
  assert.match(api, /session_usage_enabled: boolean;/);
});

test("il tipo storico frontend porta parse_mode coerente col contratto backend (BH-03)", () => {
  assert.match(api, /parse_mode: "structured" \| "text" \| null;/);
});

test("il fallback testuale è segnalato come fatto sull'ultimo campione del provider, non come errore", () => {
  assert.match(
    providerChart,
    /const latestParseMode = samples\.length > 0 \? samples\[samples\.length - 1\]\.parse_mode : null;/,
  );
  assert.match(providerChart, /const textFallbackActive = latestParseMode === "text";/);
  assert.match(providerChart, /textFallbackActive && \(/);
  assert.match(providerChart, /Fallback testuale attivo per questo provider/);
  // Riferisce, non giudica: niente linguaggio di allarme intorno all'avviso.
  assert.doesNotMatch(providerChart, /Fallback testuale attivo per questo provider[\s\S]{0,120}(errore|attenzione)/i);
});

test("una riga senza parse_mode (pre-BH-03, 'non noto') non genera l'avviso di fallback testuale", () => {
  // `textFallbackActive` è vero soltanto per "text", mai per `null`/`undefined`:
  // una riga storica scritta prima di BH-03 non deve leggersi come fallback
  // in corso.
  assert.doesNotMatch(providerChart, /latestParseMode !== "structured"/);
  assert.doesNotMatch(providerChart, /latestParseMode == null/);
});

test("lo stile dell'avviso di fallback testuale riusa la classe neutra già in uso per il residuo, senza nuove dipendenze", () => {
  assert.match(providerChart, /className="budget-note budget-parse-mode-note"/);
  assert.match(styles, /\.budget-parse-mode-note/);
});
