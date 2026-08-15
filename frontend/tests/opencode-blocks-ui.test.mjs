import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const tsModule = ts.default ?? ts;

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const fixturesDir = new URL("fixtures/opencode-tui/", import.meta.url);
const consoleView = app.slice(app.indexOf("function Console("), app.indexOf("export default function App()"));

// Stessa convenzione di budget-view.test.mjs: il parser opencode è una
// funzione pura senza JSX/React, quindi la estraiamo dal sorgente e la
// eseguiamo davvero sulle fixture reali della TUI OpenCode, invece di
// limitarci a cercare stringhe.
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

function loadOpenCodeBlocks() {
  const ansiMarker = "const ANSI_SEQUENCE =";
  const ansiStart = app.indexOf(ansiMarker);
  assert.ok(ansiStart >= 0, "costante ANSI_SEQUENCE non trovata nel sorgente");
  const ansi = app.slice(ansiStart, app.indexOf("\n", ansiStart));
  const thresholdMarker = "const BLOCK_COLLAPSE_THRESHOLD =";
  const thresholdStart = app.indexOf(thresholdMarker);
  assert.ok(thresholdStart >= 0, "costante BLOCK_COLLAPSE_THRESHOLD non trovata nel sorgente");
  const threshold = app.slice(thresholdStart, app.indexOf("\n", thresholdStart));
  const chrome = extractFunction(app, "opencodeChrome");
  const blocks = extractFunction(app, "opencodeChatBlocks");
  const snippet = `${ansi}\n${threshold}\n\n${chrome}\n\n${blocks}\n\nmodule.exports = { opencodeChrome, opencodeChatBlocks };\n`;
  const { outputText } = tsModule.transpileModule(snippet, {
    compilerOptions: { module: tsModule.ModuleKind.CommonJS, target: tsModule.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}

const opencode = loadOpenCodeBlocks();

function fixture(name) {
  return readFileSync(new URL(name, fixturesDir), "utf8");
}

test("la vista Blocchi è abilitata per OpenCode via agenticView, senza estendere agentic", () => {
  assert.match(consoleView, /const agenticStatus = agentic \|\| opencode;/);
  assert.match(consoleView, /const agenticView = agenticStatus;/);
  assert.match(consoleView, /\{agenticView && \(\s*<span className="output-mode"/);
  assert.match(consoleView, /outputMode === "blocks" && agenticView/);
  // agentic resta riservato ai provider con classificatore backend; opencode
  // estende lo stato via agenticStatus (Compact/Clear sono comandi TUI validi).
  assert.match(consoleView, /const agentic = \/codex\|claude\|agy\|antigravity\/i\.test\(session\.current_command\);/);
});

test("chatBlocks indirizza il provider opencode al parser dedicato", () => {
  assert.match(app, /if \(\/opencode\/i\.test\(provider\)\) return opencodeChatBlocks\(content\);/);
});

test("turno completato: utente, esecuzione tool, risposta e attività in blocchi distinti", () => {
  const blocks = opencode.opencodeChatBlocks(fixture("04-completato.txt"));
  assert.deepEqual(blocks.map((block) => block.kind), ["user", "activity", "agent", "activity"]);
  assert.equal(blocks[0].content, "Quante righe ha dati.txt? Rispondi in una riga.");
  assert.ok(blocks[1].content.includes("$ wc -l /workspace/progetto/dati.txt"), "il comando shell resta in attività");
  assert.ok(blocks[1].content.includes("2 /workspace/progetto/dati.txt"), "l'output del comando resta in attività");
  assert.equal(blocks[2].content, "2 righe.");
  assert.ok(blocks[3].content.includes("▣  Build · Big Pickle · 10.1s"));
});

test("frame idle e prompt non inviato non producono blocchi (chrome ripetuto filtrato)", () => {
  assert.equal(opencode.opencodeChatBlocks(fixture("01-idle.txt")).length, 0, "idle non deve mostrare messaggi finti");
  assert.equal(opencode.opencodeChatBlocks(fixture("02-prompt-inserito.txt")).length, 0, "il draft non inviato non è un messaggio utente");
});

test("turno attivo: solo prompt utente e attività di build", () => {
  const blocks = opencode.opencodeChatBlocks(fixture("03-attivo.txt"));
  assert.deepEqual(blocks.map((block) => block.kind), ["user", "activity"]);
  assert.ok(blocks[1].content.includes("Build · Big Pickle"));
});

test("richiesta di autorizzazione: il dialog Permission required resta visibile", () => {
  const blocks = opencode.opencodeChatBlocks(fixture("07-autorizzazione.txt"));
  assert.deepEqual(blocks.map((block) => block.kind), ["user", "activity"]);
  assert.ok(blocks[1].content.includes("Permission required"), "il dialog di autorizzazione non deve sparire");
  assert.ok(blocks[1].content.includes("Allow once"));
  assert.ok(blocks[1].content.includes("$ wc -l f.txt"));
});

test("interruzione: l'output compresso del tool e lo stato interrupted restano attività", () => {
  const confirm = opencode.opencodeChatBlocks(fixture("05-conferma-interrupt.txt"));
  assert.deepEqual(confirm.map((block) => block.kind), ["activity"]);
  assert.ok(confirm[0].content.includes("Click to expand"));
  const interrupted = opencode.opencodeChatBlocks(fixture("06-interrotto.txt"));
  assert.deepEqual(interrupted.map((block) => block.kind), ["activity"]);
  assert.ok(interrupted[0].content.includes("interrupted"));
});

test("il chrome della TUI è riconosciuto esplicitamente", () => {
  assert.ok(opencode.opencodeChrome("╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀"));
  assert.ok(opencode.opencodeChrome("tab agents  ctrl+p commands"));
  assert.ok(opencode.opencodeChrome("   ● Tip Run /connect to add an AI provider and start coding"));
  assert.ok(opencode.opencodeChrome("/workspace/progetto  8.5K (4%)  ctrl+p commands"));
  assert.ok(opencode.opencodeChrome("   ⬝⬝⬝⬝⬝⬝⬝⬝  esc again to interrupt"));
  assert.ok(!opencode.opencodeChrome("Quante righe ha dati.txt? Rispondi in una riga."));
  assert.ok(!opencode.opencodeChrome("2 righe."));
});

test("la vista Blocchi usa lo storico OpenCode persistito quando disponibile", () => {
  assert.match(consoleView, /fetchOpencodeHistory\(session\.id\)/);
  assert.match(consoleView, /opencode && opencodeHistory && opencodeHistory\.blocks\.length > 0/);
});

test("il parser Markdown inline riconosce testo formattato, link e codice", () => {
  const inlineFn = extractFunction(app, "parseInlineTokens");
  const { outputText } = tsModule.transpileModule(`${inlineFn}\nmodule.exports = { parseInlineTokens };\n`, {
    compilerOptions: { module: tsModule.ModuleKind.CommonJS, target: tsModule.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function("module", "exports", outputText)(module, module.exports);
  const tokens = module.exports.parseInlineTokens("Test **grassetto**, *corsivo*, `codice` e [sito](https://example.com)");
  assert.equal(tokens.length, 8);
  assert.equal(tokens[1].type, "bold");
  assert.equal(tokens[1].value, "grassetto");
  assert.equal(tokens[3].type, "italic");
  assert.equal(tokens[3].value, "corsivo");
  assert.equal(tokens[5].type, "code");
  assert.equal(tokens[5].value, "codice");
  assert.equal(tokens[7].type, "link");
  assert.equal(tokens[7].text, "sito");
  assert.equal(tokens[7].href, "https://example.com");
});

test("il parser Markdown a blocchi separa code fence, elenchi e titoli", () => {
  const blockFn = extractFunction(app, "parseMarkdownBlocks");
  const { outputText } = tsModule.transpileModule(`${blockFn}\nmodule.exports = { parseMarkdownBlocks };\n`, {
    compilerOptions: { module: tsModule.ModuleKind.CommonJS, target: tsModule.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function("module", "exports", outputText)(module, module.exports);
  const text = `# Titolo
Paragrafo introduttivo

- Punto A
- Punto B

\`\`\`bash
echo 123
\`\`\`
`;
  const blocks = module.exports.parseMarkdownBlocks(text);
  assert.equal(blocks[0].type, "heading");
  assert.equal(blocks[0].text, "Titolo");
  assert.equal(blocks[1].type, "paragraph");
  assert.equal(blocks[2].type, "ul");
  assert.deepEqual(blocks[2].items, ["Punto A", "Punto B"]);
  assert.equal(blocks[3].type, "code_block");
  assert.equal(blocks[3].lang, "bash");
  assert.equal(blocks[3].code, "echo 123");
});

