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
    directoryModal.indexOf("function closeFilePreview("),
  );
  assert.match(openEntry, /if \(isPreviewableDirectoryEntry\(entry\)\)/);
  assert.match(app, /function isPreviewableDirectoryEntry[\s\S]*previewKindFor\(entry\.name\)[\s\S]*!isDownloadable\(entry\.name\)/);
  assert.match(openEntry, /setOpenFile\(fullPath\)/);
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
  assert.match(directoryModal, /savedScrollTopRef\.current = modalRef\.current\?\.scrollTop \?\? 0/);
  assert.match(directoryModal, /modalRef\.current\.scrollTop = savedScrollTopRef\.current/);
  assert.match(directoryModal, /if \(openFile !== null\) closeFilePreview\(\)/);
  const closePreview = directoryModal.slice(
    directoryModal.indexOf("function closeFilePreview("),
    directoryModal.indexOf("function downloadEntry("),
  );
  assert.doesNotMatch(closePreview, /setCurrentPath|setDirectoryQuery|setDirectorySort|fetchDirectory/);
});

test("l'anteprima naviga tra i file anteprimabili della stessa directory nell'ordine selezionato", () => {
  assert.match(app, /type PreviewNavigation =/);
  assert.match(app, /aria-label=\{t\.previousPreview\}/);
  assert.match(app, /aria-label=\{t\.nextPreview\}/);
  assert.match(app, /navigation\.index \+ 1\} \/ \{navigation\.total/);
  assert.match(directoryModal, /sortedDirectoryEntries\.filter\([\s\S]*\.filter\(isPreviewableDirectoryEntry\)/);
  assert.match(directoryModal, /previewPaths\[openFileIndex - 1\]/);
  assert.match(directoryModal, /previewPaths\[openFileIndex \+ 1\]/);
  assert.match(artifactsModal, /artifactParentPath\(item\.name\) === previewParentPath/);
  assert.match(artifactsModal, /sortArtifacts\([\s\S]*artifactSort/);
  assert.match(artifactsModal, /previewItems\[previewItemIndex - 1\]/);
  assert.match(artifactsModal, /previewItems\[previewItemIndex \+ 1\]/);
});

test("l'anteprima può espandersi e torna alla dimensione normale quando viene chiusa", () => {
  assert.match(app, /className="modal-fullscreen"/);
  assert.match(app, /aria-pressed=\{fullscreen\}/);
  assert.match(app, /fullscreen \? t\.exitFullscreen : t\.enterFullscreen/);
  assert.match(directoryModal, /modal-backdrop-fullscreen/);
  assert.match(directoryModal, /help-modal-fullscreen/);
  assert.match(directoryModal, /setPreviewFullscreen\(false\)/);
  assert.match(artifactsModal, /modal-backdrop-fullscreen/);
  assert.match(artifactsModal, /help-modal-fullscreen/);
  assert.match(artifactsModal, /setPreviewFullscreen\(false\)/);
});

test("l'anteprima mostra la data di ultimo aggiornamento del file corrente", () => {
  assert.match(app, /className="preview-modified"/);
  assert.match(app, /dateTime=\{source\.modifiedAt\}/);
  assert.match(app, /formatDate\(source\.modifiedAt\)/);
  assert.match(directoryModal, /openFileEntry\?\.modified_at \?\? null/);
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
