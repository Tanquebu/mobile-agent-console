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
const console_ = app.slice(
  app.indexOf("function Console("),
  app.indexOf("export default function App("),
);
const artifactsModal = app.slice(
  app.indexOf("function ArtifactsModal("),
  app.indexOf("function suggestedSnapshotMode("),
);
// IMP-PW-04-FRONTEND: PreviewModal ospita solo la stella dei preferiti (il
// bottone copia-path resta invariato); FavoritesContext/useFavorites/
// FavoritesProvider/FavoritesModal sono colocati subito dopo, prima di
// DirectoryModal.
const previewModal = app.slice(
  app.indexOf("function PreviewModal("),
  app.indexOf("type FavoritesContextValue ="),
);
const favoritesBlock = app.slice(
  app.indexOf("type FavoritesContextValue ="),
  app.indexOf("function DirectoryModal("),
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

test("i file MP4 sono ammessi dall'uploader di progetto e restano scaricabili", () => {
  assert.match(app, /DOWNLOADABLE_FILE = \/.*mp4/);
  assert.match(app, /const defaultAllowedExtensions = \[[\s\S]*"\.mp4"/);
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

// IMP-PW-03: fase 3 del window manager delle anteprime, template di layout
// affiancati (ADR 015, GATE-PW-03).
const previewTile = app.slice(
  app.indexOf("function PreviewTile("),
  app.indexOf("function PreviewLayoutSwitcher("),
);

test("il window manager espone il tipo LayoutMode e i suoi slot", () => {
  assert.match(previewWindowManager, /type LayoutMode = "1x1" \| "2v" \| "2h" \| "4";/);
  assert.match(previewWindowManager, /function slotsForLayout\(mode: LayoutMode\): number \{/);
  assert.match(previewWindowManager, /mode === "1x1" \? 1 : mode === "4" \? 4 : 2;/);
});

test("al più una finestra fullscreen alla volta (GATE-PW-03 punto 7)", () => {
  assert.match(
    previewWindowManager,
    /if \(entry\.id === id\) return \{ \.\.\.entry, fullscreen: !entry\.fullscreen \};\s*return entry\.fullscreen \? \{ \.\.\.entry, fullscreen: false \} : entry;/,
  );
});

test("PreviewTile non intercetta Escape (GATE-PW-03 punto 6)", () => {
  assert.doesNotMatch(previewTile, /addEventListener\("keydown"/);
  assert.match(previewTile, /role="dialog" aria-modal="false"/);
});

test("PreviewWindowHost e PreviewTray non hanno variazioni testuali in questa fase", () => {
  assert.match(previewWindowManager, /const closeOnEscape = \(event: KeyboardEvent\) => \{/);
  assert.match(previewWindowManager, /if \(event\.key === "Escape"\) close\(\);/);
  assert.match(previewWindowManager, /role="toolbar" aria-label=\{t\.previewTray\}/);
  assert.match(previewWindowManager, /className="preview-tray-chip-close"/);
});

test("il selettore di layout è separato dal tray e usa le 4 etichette dei template", () => {
  assert.match(previewWindowManager, /function PreviewLayoutSwitcher\(\)/);
  assert.match(previewWindowManager, /const \{ layoutMode, changeLayoutMode \} = usePreviewWindows\(\);/);
  assert.match(previewWindowManager, /role="group" aria-label=\{t\.previewLayoutPicker\}/);
  assert.match(previewWindowManager, /label: t\.layout1x1/);
  assert.match(previewWindowManager, /label: t\.layout2Vertical/);
  assert.match(previewWindowManager, /label: t\.layout2Horizontal/);
  assert.match(previewWindowManager, /label: t\.layout4/);
});

test("il tray resta nascosto in modalità solitaria e riappare nel workspace con 2+ finestre", () => {
  assert.match(
    previewWindowManager,
    /\{visibleWindows\.length === 0 && minimizedWindows\.length > 0 && <PreviewTray windows=\{minimizedWindows\} \/>\}/,
  );
  assert.match(
    previewWindowManager,
    /\{minimizedWindows\.length > 0 && <PreviewTray windows=\{minimizedWindows\} \/>\}/,
  );
  assert.match(previewWindowManager, /function PreviewWorkspace\(/);
});

// IMP-PW-04-FRONTEND: Preferiti (Fase 4, ADR 015, GATE-PW-04). La stella
// compare solo sulle preview aperte tramite path assoluto di filesystem
// (filePreviewSource: DirectoryModal e blocchi agente in Console), mai su
// quelle aperte da ArtifactsModal (artifactPreviewSource) — decisione di
// scope vincolante di questa voce.

test("filePreviewSource imposta favoritePath, artifactPreviewSource no", () => {
  const filePreviewSource = app.slice(
    app.indexOf("function filePreviewSource("),
    app.indexOf("function artifactPreviewSource("),
  );
  const artifactPreviewSource = app.slice(
    app.indexOf("function artifactPreviewSource("),
    app.indexOf("type PreviewNavigation ="),
  );
  assert.match(filePreviewSource, /favoritePath: path,/);
  assert.doesNotMatch(artifactPreviewSource, /favoritePath/);
  assert.match(app, /favoritePath\?: string \| null;/);
});

test("FavoritesProvider/useFavorites esistono con reset su !active, stesso pattern di PreviewWindowsProvider", () => {
  assert.match(favoritesBlock, /const FavoritesContext = createContext<FavoritesContextValue \| null>\(null\);/);
  assert.match(favoritesBlock, /function useFavorites\(\): FavoritesContextValue \{/);
  assert.match(favoritesBlock, /throw new Error\("useFavorites usato fuori da FavoritesProvider"\);/);
  assert.match(favoritesBlock, /function FavoritesProvider\(\{ children, active \}: \{ children: ReactNode; active: boolean \}\) \{/);
  assert.match(
    favoritesBlock,
    /if \(!active\) \{\s*setFavorites\(\[\]\);\s*setFavoritesError\(""\);\s*return;\s*\}/,
  );
  assert.match(favoritesBlock, /listFavorites\(\)/);
  assert.match(favoritesBlock, /toggleFavorite = useCallback\(async \(path: string\) => \{/);
  assert.match(favoritesBlock, /removeFavoriteById = useCallback\(async \(id: string\) => \{/);
});

test("la stella dei preferiti compare solo quando source.favoritePath è impostato", () => {
  assert.match(previewModal, /const \{ isFavorite, toggleFavorite \} = useFavorites\(\);/);
  assert.match(previewModal, /\{source\.favoritePath && \(/);
  assert.match(previewModal, /className="preview-favorite-toggle"/);
  assert.match(previewModal, /aria-pressed=\{isFavorite\(source\.favoritePath\)\}/);
  assert.match(previewModal, /aria-label=\{isFavorite\(source\.favoritePath\) \? t\.removeFavorite : t\.addFavorite\}/);
  // Il bottone resta nella riga del nome file, non nel gruppo di azioni del
  // modal-header (già affollato di 3 bottoni dalla Fase 2).
  const pathRow = previewModal.slice(
    previewModal.indexOf('<div className="preview-path-row">'),
    previewModal.indexOf('<div className="modal-header-actions">'),
  );
  assert.match(pathRow, /preview-favorite-toggle/);
});

test("FavoritesModal apre un preferito tramite fetchFileMetadata + openPreviewWindow e permette la rimozione", () => {
  assert.match(favoritesBlock, /function FavoritesModal\(\{ onClose, sessionId \}: \{ onClose: \(\) => void; sessionId: string \| null \}\) \{/);
  assert.match(favoritesBlock, /const \{ openPreviewWindow \} = usePreviewWindows\(\);/);
  assert.match(favoritesBlock, /const metadata = await fetchFileMetadata\(sessionId, favorite\.path\);/);
  assert.match(favoritesBlock, /resolveSource: \(path\) => filePreviewSource\(sessionId, path, metadata\.modified_at, metadata\.media_type\),/);
  assert.match(favoritesBlock, /siblings: \[favorite\.path\],/);
  assert.match(favoritesBlock, /className="favorites-item-remove"/);
  assert.match(favoritesBlock, /onClick=\{\(\) => void removeFavoriteById\(favorite\.id\)\}/);
});

test("il bottone \"apri\" resta disabilitato senza sessione e mostra favoritesNoSession", () => {
  assert.match(favoritesBlock, /className="favorites-item-open"/);
  assert.match(favoritesBlock, /disabled=\{!sessionId \|\| opening === favorite\.id\}/);
  assert.match(favoritesBlock, /\{!sessionId && <p className="favorites-hint">\{t\.favoritesNoSession\}<\/p>\}/);
  assert.match(favoritesBlock, /async function openFavorite\(favorite: Favorite\) \{\s*if \(!sessionId\) return;/);
});

test("api.ts espone listFavorites/addFavorite/deleteFavorite", () => {
  const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
  assert.match(api, /export type Favorite = \{/);
  assert.match(api, /export async function listFavorites\(\): Promise<Favorite\[\]> \{/);
  assert.match(api, /export async function addFavorite\(path: string, label\?: string \| null\): Promise<Favorite> \{/);
  assert.match(api, /export async function deleteFavorite\(id: string\): Promise<void> \{/);
  assert.match(api, /await request\(`\/api\/v1\/favorites\/\$\{encodeURIComponent\(id\)\}`, \{ method: "DELETE" \}\);/);
});

test("i punti di ingresso dashboard e Console aprono FavoritesModal, non ristretti per ruolo", () => {
  assert.match(sessionList, /const \[showFavorites, setShowFavorites\] = useState\(false\);/);
  assert.match(sessionList, /setShowFavorites\(true\); \}\} aria-label=\{t\.favorites\}/);
  assert.match(sessionList, /<FavoritesModal onClose=\{\(\) => setShowFavorites\(false\)\} sessionId=\{sessions\[0\]\?\.id \?\? null\}/);
  assert.match(console_, /const \[showFavorites, setShowFavorites\] = useState\(false\);/);
  assert.match(console_, /onClick=\{\(\) => setShowFavorites\(true\)\}/);
  assert.match(console_, /<FavoritesModal onClose=\{\(\) => setShowFavorites\(false\)\} sessionId=\{session\.id\}/);
});

test("App() avvolge il contenuto sia in FavoritesProvider sia in PreviewWindowsProvider", () => {
  assert.match(app, /<FavoritesProvider active=\{identity != null\}>\s*<PreviewWindowsProvider active=\{identity != null\}>/);
});
