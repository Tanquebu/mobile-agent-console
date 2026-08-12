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

test("la directory espone ricerca e ordinamento senza mutare il listing autorevole", () => {
  assert.match(directoryModal, /directoryQuery/);
  assert.match(directoryModal, /directorySort/);
  assert.match(directoryModal, /listing\.entries\.filter/);
  assert.match(directoryModal, /sortDirectoryEntries/);
  assert.match(directoryModal, /displayedEntries\.map/);
});

test("immagini e video aprono l'anteprima prima del ramo download", () => {
  const openEntry = directoryModal.slice(
    directoryModal.indexOf("function openEntry("),
    directoryModal.indexOf("function closeFilePreview("),
  );
  assert.ok(openEntry.indexOf("mediaPreviewKind") < openEntry.indexOf("isDownloadable"));
  assert.match(openEntry, /setOpenFile\(fullPath\)/);
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

test("il selettore progetto mostra ricerca, ordinamento e risultati accessibili", () => {
  assert.match(sessionList, /projectSearchPlaceholder/);
  assert.match(sessionList, /projectSortNameAsc/);
  assert.match(sessionList, /projectSortNameDesc/);
  assert.match(sessionList, /displayedPresets\.map/);
  assert.match(sessionList, /role="listbox"/);
  assert.match(sessionList, /aria-selected=\{directory === path\}/);
});
