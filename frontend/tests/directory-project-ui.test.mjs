import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const directoryModal = app.slice(
  app.indexOf("function DirectoryModal("),
  app.indexOf("const PREVIEWABLE_TEXT_TYPES"),
);
const sessionList = app.slice(
  app.indexOf("function SessionList("),
  app.indexOf("function Console("),
);
const artifactsModal = app.slice(
  app.indexOf("function ArtifactsModal("),
  app.indexOf("function suggestedSnapshotMode("),
);
// IMP-PW-01: apertura/navigazione/fullscreen delle anteprime sono state
// sollevate dai tre modal (DirectoryModal, ArtifactsModal, blocchi in
// Console) a un unico window manager, colocato subito prima di PreviewModal.
const previewWindowManager = app.slice(
  app.indexOf("type PreviewWindowState ="),
  app.indexOf("function PreviewModal("),
);

test("la directory espone ricerca e ordinamento senza mutare il listing autorevole", () => {
  assert.match(directoryModal, /directoryQuery/);
  assert.match(directoryModal, /directorySort/);
  assert.match(directoryModal, /sortDirectoryEntries\(listing\.entries, directorySort\)/);
  assert.match(app, /compareNullableDates\(a\.modified_at, b\.modified_at/);
  assert.match(directoryModal, /sortedDirectoryEntries\.filter/);
  assert.match(directoryModal, /sortDirectoryEntries/);
  assert.match(directoryModal, /displayedEntries\.map/);
});

test("immagini e video aprono l'anteprima prima del ramo download", () => {
  const openEntry = directoryModal.slice(
    directoryModal.indexOf("function openEntry("),
    directoryModal.indexOf("function downloadEntry("),
  );
  assert.match(openEntry, /if \(isPreviewableDirectoryEntry\(entry\)\)/);
  assert.match(app, /function isPreviewableDirectoryEntry[\s\S]*previewKindFor\(entry\.name\)[\s\S]*!isDownloadable\(entry\.name\)/);
  assert.match(openEntry, /openPreviewWindow\(\{/);
  assert.match(openEntry, /initialPath: fullPath/);
  assert.match(openEntry, /\} else if \(entry\.type === "file"\) \{\s*downloadEntry\(entry\);/);
});

test("i file MP3 restano scaricabili e possono anche usare il player audio", () => {
  assert.match(app, /DOWNLOADABLE_FILE = \/.*mp3/);
  assert.match(app, /PREVIEWABLE_AUDIO.*m4a\|mp3/);
  assert.match(app, /mediaType === "audio\/mpeg"/);
  assert.match(app, /<audio className="file-media" src=\{source\.url/);
});

test("i file M4A aprono il player audio in directory e artefatti", () => {
  assert.match(app, /PREVIEWABLE_AUDIO.*m4a\|mp3/);
  assert.match(app, /return "audio"/);
  assert.match(app, /mediaType === "audio\/mp4"/);
  assert.match(app, /filePreviewUrl\(sessionId, path\)/);
  assert.match(app, /artifactDownloadUrl\(sessionId, item\.name\)/);
});

test("la chiusura dell'anteprima conserva scroll, path e filtri della directory", () => {
  // IMP-PW-01: prima, aprire un file sostituiva la lista nello stesso
  // contenitore scrollabile (DirectoryModal.openFile), quindi chiudere la
  // preview richiedeva un meccanismo dedicato di salvataggio/ripristino
  // dello scroll. Ora la preview vive in una finestra separata del window
  // manager globale e la lista non viene mai smontata: non c'è più stato
  // locale di preview da poter alterare scroll/path/filtri, quindi non deve
  // più esistere nessun meccanismo di questo tipo dentro DirectoryModal.
  assert.doesNotMatch(directoryModal, /openFile|previewFullscreen|savedScrollTopRef|restoreScrollRef|closeFilePreview/);
  assert.match(directoryModal, /const \{ openPreviewWindow, hasActivePreviewWindow \} = usePreviewWindows\(\);/);
  assert.match(directoryModal, /if \(event\.key !== "Escape" \|\| hasActivePreviewWindow\) return;/);
});

test("l'anteprima naviga tra i file anteprimabili della stessa directory nell'ordine selezionato", () => {
  assert.match(app, /type PreviewNavigation =/);
  assert.match(app, /aria-label=\{t\.previousPreview\}/);
  assert.match(app, /aria-label=\{t\.nextPreview\}/);
  assert.match(app, /navigation\.index \+ 1\} \/ \{navigation\.total/);
  // IMP-PW-01: prev/next non sono più duplicati per modal (openFileIndex per
  // DirectoryModal, previewItemIndex per ArtifactsModal) — la stessa
  // aritmetica sull'indice vive una sola volta in navigateWindow, dentro il
  // window manager; ogni modal si limita a fornire l'elenco ordinato dei
  // path anteprimabili come `siblings` al momento dell'apertura.
  assert.match(previewWindowManager, /const index = entry\.siblings\.indexOf\(entry\.currentPath\);/);
  assert.match(previewWindowManager, /const nextIndex = index \+ direction;/);
  assert.match(previewWindowManager, /return \{ \.\.\.entry, currentPath: entry\.siblings\[nextIndex\] \};/);
  assert.match(directoryModal, /sortedDirectoryEntries\.filter\([\s\S]*\.filter\(isPreviewableDirectoryEntry\)/);
  assert.match(directoryModal, /siblings: previewPaths/);
  assert.match(artifactsModal, /artifactParentPath\(candidate\.name\) === parentPath/);
  assert.match(artifactsModal, /sortArtifacts\([\s\S]*artifactSort/);
  assert.match(artifactsModal, /siblings: siblingItems\.map\(\(candidate\) => candidate\.name\)/);
});

test("l'anteprima può espandersi e torna alla dimensione normale quando viene chiusa", () => {
  assert.match(app, /className="modal-fullscreen"/);
  assert.match(app, /aria-pressed=\{fullscreen\}/);
  assert.match(app, /fullscreen \? t\.exitFullscreen : t\.enterFullscreen/);
  // IMP-PW-01: il fullscreen è ora uno stato per-finestra nel window manager
  // (PreviewWindowHost/PreviewWindowsProvider), non più duplicato come
  // `previewFullscreen` locale in ciascun modal — DirectoryModal e
  // ArtifactsModal non conoscono più il fullscreen della preview.
  assert.match(previewWindowManager, /modal-backdrop\$\{entry\.fullscreen \? " modal-backdrop-fullscreen" : ""\}/);
  assert.match(previewWindowManager, /help-modal directory-modal\$\{entry\.fullscreen \? " help-modal-fullscreen" : ""\}/);
  assert.match(previewWindowManager, /fullscreen: !entry\.fullscreen/);
  assert.doesNotMatch(directoryModal, /previewFullscreen/);
  assert.doesNotMatch(artifactsModal, /previewFullscreen/);
});

test("l'anteprima mostra la data di ultimo aggiornamento del file corrente", () => {
  assert.match(app, /className="preview-modified"/);
  assert.match(app, /dateTime=\{source\.modifiedAt\}/);
  assert.match(app, /formatDate\(source\.modifiedAt\)/);
  assert.match(directoryModal, /match\?\.modified_at \?\? null/);
  assert.match(app, /modifiedAt: item\.modified_at/);
});

test("la PreviewModal centralizza anche la copia del path completo", () => {
  assert.match(app, /className="preview-path-copy"/);
  assert.match(app, /copyToClipboard\(source\.name\)/);
  assert.match(app, /pathCopied \? t\.copied : t\.copyPath/);
});

test("il selettore progetto mostra ricerca, ordinamento e risultati accessibili", () => {
  assert.match(sessionList, /projectSearchPlaceholder/);
  assert.match(sessionList, /projectSortNameAsc/);
  assert.match(sessionList, /projectSortNameDesc/);
  assert.match(sessionList, /displayedPresets\.map/);
  assert.match(sessionList, /role="listbox"/);
  assert.match(sessionList, /aria-selected=\{directory === path\}/);
});

test("il progetto master è fissato in cima alla lista alfabetica dei preset, senza preselezione", () => {
  assert.match(sessionList, /masterPreset = presets\.find\(\(\[label\]\) => label\.localeCompare\("master"/);
  assert.match(sessionList, /\[masterPreset, \.\.\.filteredAndSorted\.filter\(\(preset\) => preset !== masterPreset\)\]/);
  assert.match(sessionList, /setDirectory\(\(value\) => value \|\| entries\[0\]\?\.\[1\]/);
  assert.match(sessionList, /setDirectory\(\(value\) => value \|\| entries\[0\]\?\.\[1\] \|\| config\.allowed_roots\[0\] \|\| ""/);
});

test("la modale artefatti mostra e copia il percorso fornito dal backend", () => {
  assert.match(artifactsModal, /fetchArtifactDirectory\(sessionId\)/);
  assert.match(artifactsModal, /artifactFolderLabel/);
  assert.match(artifactsModal, /copyToClipboard\(artifactDirectory\)/);
  assert.match(artifactsModal, /directoryCopied \? t\.copied : t\.copyPath/);
});
