import assert from "node:assert/strict";
import { chromium } from "playwright";

const baseUrl = process.env.MAC_BROWSER_BASE_URL || "http://127.0.0.1:4173";
const session = {
  id: "1",
  name: "preview navigation",
  attached: false,
  windows: 1,
  current_command: "bash",
  activity_at: "2026-08-22T10:00:00Z",
  hidden: false,
};
const artifacts = [
  { name: "alpha.md", media_type: "text/markdown", size: 5, modified_at: "2026-08-20T10:00:00Z" },
  { name: "manual.pdf", media_type: "application/pdf", size: 6, modified_at: "2026-08-21T10:00:00Z" },
  { name: "zeta.txt", media_type: "text/plain", size: 4, modified_at: "2026-08-22T10:00:00Z" },
  { name: "nested/newest.md", media_type: "text/markdown", size: 6, modified_at: "2026-08-23T10:00:00Z" },
];

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function assertPosition(page, position) {
  await page.locator(".preview-navigation", { hasText: position }).waitFor();
}

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 320, height: 720 },
    locale: "it-IT",
    permissions: ["clipboard-read", "clipboard-write"],
  });
  const page = await context.newPage();
  page.setDefaultTimeout(7_000);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/session") return json(route, { username: "admin", role: "admin", csrf_token: "csrf" });
    if (path === "/api/v1/config") return json(route, { allowed_roots: ["/workspace"], workspace_presets: {} });
    if (path === "/api/v1/sessions") return json(route, { sessions: [session] });
    if (path === "/api/v1/agent-statuses") return json(route, { statuses: [] });
    if (path === "/api/v1/provider-rate-limits" || path === "/api/v1/orchestrator-state") return json(route, null);
    if (path === "/api/v1/sessions/1/panes") return json(route, { panes: [] });
    if (path === "/api/v1/sessions/1/directory") {
      return json(route, {
        session_id: "1",
        root: "/workspace",
        path: "/workspace",
        parent: null,
        truncated: false,
        entries: [
          { name: "alpha.txt", type: "file", size: 5, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-20T10:00:00Z" },
          { name: "manual.pdf", type: "file", size: 6, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-23T10:00:00Z" },
          { name: "zeta.md", type: "file", size: 4, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-22T10:00:00Z" },
        ],
      });
    }
    if (path === "/api/v1/sessions/1/file") {
      const filePath = url.searchParams.get("path");
      return json(route, { session_id: "1", path: filePath, size: 4, content: filePath, truncated: false });
    }
    if (path === "/api/v1/sessions/1/artifacts") return json(route, artifacts);
    if (path === "/api/v1/sessions/1/artifact-directory") return json(route, { path: "/workspace/.agent-artifacts/1" });
    if (path.startsWith("/api/v1/sessions/1/artifacts/")) {
      return route.fulfill({ status: 200, contentType: "text/plain", body: path });
    }
    return json(route, { detail: "not found" }, 404);
  });

  await page.goto(baseUrl);

  // IMP-PW-02-R1 (Difetto 1): l'header condiviso `.help-modal > header` non
  // deve mai andare a capo per i modali con un solo bottone di chiusura
  // (regressione introdotta da `flex-wrap: wrap` in IMP-PW-02, poi rimosso).
  await page.getByRole("button", { name: "Altre azioni", exact: true }).click();
  await page.getByRole("button", { name: "Sessioni nascoste", exact: true }).click();
  await page.locator("#hidden-sessions-title").waitFor();
  const hiddenTitle = await page.locator(".help-modal > header h2").boundingBox();
  const hiddenClose = await page.locator(".help-modal > header .modal-close").boundingBox();
  assert.ok(
    hiddenClose.y < hiddenTitle.y + hiddenTitle.height && hiddenClose.y + hiddenClose.height > hiddenTitle.y,
    `HiddenSessionsModal header va a capo: title=${JSON.stringify(hiddenTitle)} close=${JSON.stringify(hiddenClose)}`,
  );
  await page.getByRole("button", { name: "Chiudi" }).click();

  await page.locator("button.session-card", { hasText: session.name }).click();
  await page.getByRole("button", { name: "Funzioni", exact: true }).click();
  await page.locator(".special-section-toggle").click();
  await page.getByRole("button", { name: "Contenuto directory", exact: true }).click();
  await page.getByLabel("Ordina").selectOption("date-desc");
  await page.locator(".directory-open", { hasText: "zeta.md" }).click();
  await assertPosition(page, "1 / 2");
  await page.locator(".preview-modified", { hasText: "Ultimo aggiornamento" }).waitFor();
  assert.match(await page.locator(".preview-modified").innerText(), /22\/08\/2026/);
  const copyPath = page.getByRole("button", { name: "Copia percorso: /workspace/zeta.md" });
  await copyPath.click();
  await page.locator(".preview-path-copy", { hasText: "Copiato!" }).waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), "/workspace/zeta.md");
  await page.getByRole("button", { name: "Schermo intero", exact: true }).click();
  await page.locator(".help-modal-fullscreen").waitFor();
  assert.equal(await page.getByRole("button", { name: "Esci da schermo intero", exact: true }).getAttribute("aria-pressed"), "true");
  assert.equal(await page.getByRole("button", { name: "File precedente" }).isDisabled(), true);
  await page.getByRole("button", { name: "File successivo" }).click();
  await assertPosition(page, "2 / 2");
  await page.locator(".help-modal-fullscreen").waitFor();
  await page.locator("h2.preview-file-name", { hasText: "alpha.txt" }).waitFor();
  assert.match(await page.locator(".preview-modified").innerText(), /20\/08\/2026/);
  assert.equal(await page.getByRole("button", { name: "File successivo" }).isDisabled(), true);
  await page.getByRole("button", { name: "Esci da schermo intero", exact: true }).click();
  assert.equal(await page.locator(".help-modal-fullscreen").count(), 0);

  // IMP-PW-02: minimizza -> tray -> ripristina -> chiudi dalla chip.
  await page.getByRole("button", { name: "Riduci a icona" }).click();
  assert.equal(await page.getByRole("dialog", { name: "Anteprima file" }).count(), 0);
  const trayChip = page.locator(".preview-tray-chip", { hasText: "alpha.txt" });
  await trayChip.waitFor();
  await trayChip.locator(".preview-tray-chip-open").click();
  await page.locator("h2.preview-file-name", { hasText: "alpha.txt" }).waitFor();
  await assertPosition(page, "2 / 2");
  await page.getByRole("button", { name: "Riduci a icona" }).click();
  await trayChip.waitFor();
  await trayChip.locator(".preview-tray-chip-close").click();
  assert.equal(await page.locator(".preview-tray-chip").count(), 0);
  assert.equal(await page.locator(".preview-tray").count(), 0);

  // IMP-PW-02-R1 (Difetto 2): il tray non deve mai comparire sovrapposto a
  // una finestra a fuoco (GATE-PW-02) — apre due file in sequenza dal
  // browser directory, minimizzando il primo prima di aprire il secondo.
  await page.locator(".directory-open", { hasText: "zeta.md" }).click();
  await assertPosition(page, "1 / 2");
  await page.getByRole("button", { name: "Riduci a icona" }).click();
  await page.locator(".preview-tray-chip", { hasText: "zeta.md" }).waitFor();
  await page.locator(".directory-open", { hasText: "alpha.txt" }).click();
  await page.locator("h2.preview-file-name", { hasText: "alpha.txt" }).waitFor();
  assert.equal(
    await page.locator(".preview-tray").count(),
    0,
    "il tray non deve essere nel DOM mentre una finestra e' a fuoco",
  );
  await page.getByRole("button", { name: "Riduci a icona" }).click();
  await page.locator(".preview-tray").waitFor();
  assert.equal(
    await page.locator(".preview-tray-chip").count(),
    2,
    "il tray deve mostrare 2 chip quando nessuna finestra e' a fuoco",
  );
  await page.locator(".preview-tray-chip", { hasText: "alpha.txt" }).locator(".preview-tray-chip-close").click();
  await page.locator(".preview-tray-chip", { hasText: "zeta.md" }).locator(".preview-tray-chip-close").click();
  assert.equal(await page.locator(".preview-tray").count(), 0);

  await page.getByRole("button", { name: "Chiudi" }).click();
  await page.getByRole("button", { name: "Artefatti", exact: true }).click();
  await page.getByLabel("Ordina").selectOption("date-desc");
  await page.locator(".directory-open", { hasText: "zeta.txt" }).click();
  await assertPosition(page, "1 / 2");
  assert.match(await page.locator(".preview-modified").innerText(), /22\/08\/2026/);
  await page.getByRole("button", { name: "File successivo" }).click();
  await assertPosition(page, "2 / 2");
  await page.locator("h2.preview-file-name", { hasText: "alpha.md" }).waitFor();
  assert.match(await page.locator(".preview-modified").innerText(), /20\/08\/2026/);

  const layout = await page.locator(".preview-navigation").evaluate((node) => ({
    scrollWidth: node.scrollWidth,
    clientWidth: node.clientWidth,
    buttonHeights: [...node.querySelectorAll("button")].map((button) => button.getBoundingClientRect().height),
  }));
  assert.ok(layout.scrollWidth <= layout.clientWidth, `overflow navigazione: ${JSON.stringify(layout)}`);
  assert.ok(layout.buttonHeights.every((height) => height >= 40), `target troppo piccoli: ${JSON.stringify(layout)}`);
  await context.close();

  // IMP-PW-03: template di layout affiancati (ADR 015, GATE-PW-03), a
  // viewport >=720px. Sessione/directory dedicate con tre file
  // anteprimabili (il terzo serve solo al test del tray sotto) per non
  // interferire con le posizioni "N / total" già verificate sopra.
  async function routePreviewSession(page, sessionId) {
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      if (path === "/api/v1/auth/session") return json(route, { username: "admin", role: "admin", csrf_token: "csrf" });
      if (path === "/api/v1/config") return json(route, { allowed_roots: ["/workspace"], workspace_presets: {} });
      if (path === "/api/v1/sessions") {
        return json(route, { sessions: [{ ...session, id: sessionId, name: `layout-${sessionId}` }] });
      }
      if (path === "/api/v1/agent-statuses") return json(route, { statuses: [] });
      if (path === "/api/v1/provider-rate-limits" || path === "/api/v1/orchestrator-state") return json(route, null);
      if (path === `/api/v1/sessions/${sessionId}/panes`) return json(route, { panes: [] });
      if (path === `/api/v1/sessions/${sessionId}/directory`) {
        return json(route, {
          session_id: sessionId,
          root: "/workspace",
          path: "/workspace",
          parent: null,
          truncated: false,
          entries: [
            { name: "uno.txt", type: "file", size: 4, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-20T10:00:00Z" },
            { name: "due.txt", type: "file", size: 4, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-21T10:00:00Z" },
            { name: "tre.txt", type: "file", size: 4, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-22T10:00:00Z" },
          ],
        });
      }
      if (path === `/api/v1/sessions/${sessionId}/file`) {
        const filePath = url.searchParams.get("path");
        return json(route, { session_id: sessionId, path: filePath, size: 4, content: filePath, truncated: false });
      }
      return json(route, { detail: "not found" }, 404);
    });
  }

  async function openDirectoryFile(page, fileName) {
    await page.locator(".directory-open", { hasText: fileName }).click();
  }

  async function openSessionDirectory(page, sessionName) {
    await page.locator("button.session-card", { hasText: sessionName }).click();
    await page.getByRole("button", { name: "Funzioni", exact: true }).click();
    await page.locator(".special-section-toggle").click();
    await page.getByRole("button", { name: "Contenuto directory", exact: true }).click();
  }

  async function minimizeVisible(page, fileName) {
    // Scoped al dialog/tile di preview (aria-label "Anteprima file", diverso
    // da "directory-title" di DirectoryModal, sempre montato sotto anche
    // quando coperto) che mostra fileName, così funziona sia nel percorso
    // solitario (PreviewWindowHost) sia dentro una tile.
    const scope = page.locator('[role="dialog"][aria-label="Anteprima file"]', { hasText: fileName });
    await scope.getByRole("button", { name: "Riduci a icona" }).click();
    await page.locator(".preview-tray-chip", { hasText: fileName }).waitFor();
  }

  async function openAndMinimize(page, fileName) {
    await openDirectoryFile(page, fileName);
    await page.locator("h2.preview-file-name", { hasText: fileName }).waitFor();
    await minimizeVisible(page, fileName);
  }

  async function restoreFromTray(page, fileName) {
    await page.locator(".preview-tray-chip", { hasText: fileName }).locator(".preview-tray-chip-open").click();
  }

  // Nota di ambiente scoperta scrivendo questo test: sia il percorso
  // solitario (`.modal-backdrop`, invariato dalla Fase 1) sia il nuovo
  // `.preview-workspace` sono overlay `position: fixed; inset: 0` che
  // coprono l'intero schermo — la lista della directory sottostante non è
  // mai cliccabile finché almeno una finestra di preview è visibile
  // (solitaria o in template). Per assemblare più finestre visibili
  // contemporaneamente bisogna quindi aprire ciascun file e minimizzarlo
  // subito (tornando alla directory), poi ripristinarle dal tray nella
  // combinazione voluta — non si può cliccare la lista mentre una preview è
  // a schermo. Il `PreviewLayoutSwitcher` fa eccezione (z-index 106, sopra
  // i 100 degli overlay) e resta cliccabile anche con una preview visibile.
  {
    const desktopContext = await browser.newContext({ viewport: { width: 1024, height: 768 }, locale: "it-IT" });
    const desktopPage = await desktopContext.newPage();
    desktopPage.setDefaultTimeout(7_000);
    await routePreviewSession(desktopPage, "2");
    await desktopPage.goto(baseUrl);
    await openSessionDirectory(desktopPage, "layout-2");

    // Apre uno.txt, poi (dopo averlo minimizzato) due.txt: senza cambiare
    // layout (default "1x1") la seconda apertura resta l'unica finestra
    // visibile, comportamento invariato rispetto alla Fase 2.
    await openDirectoryFile(desktopPage, "uno.txt");
    await desktopPage.locator("h2.preview-file-name", { hasText: "uno.txt" }).waitFor();
    assert.equal(await desktopPage.locator(".preview-tile").count(), 0, "layoutMode 1x1 di default: nessun tile, solo la finestra solitaria");
    assert.equal(await desktopPage.getByRole("dialog", { name: "Anteprima file" }).count(), 1);
    await minimizeVisible(desktopPage, "uno.txt");
    await openAndMinimize(desktopPage, "due.txt");
    await openAndMinimize(desktopPage, "tre.txt");
    assert.equal(await desktopPage.locator(".preview-tray-chip").count(), 3, "le tre finestre aperte e minimizzate devono comparire nel tray");

    // Passa al layout "2 verticali" (funziona anche senza nessuna finestra
    // visibile) e ripristina uno.txt e due.txt dal tray: entrambe devono
    // risultare visibili contemporaneamente come tile separati, affiancati
    // orizzontalmente (non un solo dialog).
    await desktopPage.getByRole("button", { name: "2 verticali", exact: true }).click();
    await restoreFromTray(desktopPage, "uno.txt");
    await restoreFromTray(desktopPage, "due.txt");
    await desktopPage.locator(".preview-tile").nth(1).waitFor();
    const tiles = desktopPage.locator(".preview-tile");
    assert.equal(await tiles.count(), 2, "layout 2 verticali con due finestre ripristinate: due tile, non un solo dialog");
    const boxUno = await tiles.filter({ hasText: "uno.txt" }).boundingBox();
    const boxDue = await tiles.filter({ hasText: "due.txt" }).boundingBox();
    assert.ok(
      boxUno.x + boxUno.width <= boxDue.x || boxDue.x + boxDue.width <= boxUno.x,
      `tile non affiancati in due colonne: ${JSON.stringify({ boxUno, boxDue })}`,
    );
    // Capacità 2 già raggiunta: tre.txt resta minimizzato, e con 2+ finestre
    // visibili in un template il tray può comparire assieme alle tile
    // (GATE-PW-03 punto 3, novità di questa fase).
    assert.equal(await desktopPage.locator(".preview-tray-chip", { hasText: "tre.txt" }).count(), 1);

    // Passa a "4 riquadri" (capacità 4) e ripristina anche tre.txt: tutte e
    // tre le finestre diventano visibili, il tray sparisce.
    await desktopPage.getByRole("button", { name: "4 riquadri", exact: true }).click();
    await restoreFromTray(desktopPage, "tre.txt");
    await desktopPage.locator(".preview-tile").nth(2).waitFor();
    assert.equal(await desktopPage.locator(".preview-tile").count(), 3, "layout 4 con tre finestre ripristinate: tre tile, nessuna in tray");
    assert.equal(await desktopPage.locator(".preview-tray").count(), 0);

    // Minimizza uno dei tre tile (due.txt): restano 2 tile visibili
    // (uno.txt, tre.txt) e il tray compare con la chip di due.txt — con 3
    // finestre visibili di partenza, minimizzarne una ne lascia comunque
    // 2+ visibili, che restano nel template invece di collassare al
    // percorso solitario (a differenza del caso "minimizzare l'unica altra
    // finestra visibile su due", che collasserebbe sempre al percorso
    // solitario per costruzione — GATE-PW-03 punto 3 — nascondendo il tray;
    // per questo il test parte da tre finestre visibili, non da due).
    await desktopPage.locator(".preview-tile", { hasText: "due.txt" }).getByRole("button", { name: "Riduci a icona" }).click();
    await desktopPage.locator(".preview-tray-chip", { hasText: "due.txt" }).waitFor();
    assert.equal(await desktopPage.locator(".preview-tile").count(), 2);
    assert.equal(await desktopPage.locator(".preview-tile", { hasText: "uno.txt" }).count(), 1);
    assert.equal(await desktopPage.locator(".preview-tile", { hasText: "tre.txt" }).count(), 1);

    // Ripristina dal tray: torna a tre tile visibili, tray sparisce.
    await restoreFromTray(desktopPage, "due.txt");
    await desktopPage.locator(".preview-tile").nth(2).waitFor();
    assert.equal(await desktopPage.locator(".preview-tile").count(), 3);
    assert.equal(await desktopPage.locator(".preview-tray").count(), 0);

    await desktopContext.close();
  }

  // IMP-PW-03: non-regressione mobile (<720px). Il PreviewLayoutSwitcher è
  // nascosto via CSS sotto 720px (`.preview-layout-switcher { display: none }`),
  // quindi da questo viewport non c'è modo per l'utente di cambiare
  // `layoutMode` dal suo default "1x1" (capacità 1): l'apertura di due file
  // in sequenza deve risultare sempre e solo in un'unica finestra fullscreen
  // visibile con l'altra in tray, esattamente come nelle Fasi 1-2.
  {
    const mobileContext = await browser.newContext({ viewport: { width: 375, height: 667 }, locale: "it-IT" });
    const mobilePage = await mobileContext.newPage();
    mobilePage.setDefaultTimeout(7_000);
    await routePreviewSession(mobilePage, "3");
    await mobilePage.goto(baseUrl);
    await openSessionDirectory(mobilePage, "layout-3");

    await openDirectoryFile(mobilePage, "uno.txt");
    await mobilePage.locator("h2.preview-file-name", { hasText: "uno.txt" }).waitFor();
    assert.equal(await mobilePage.locator(".preview-tile").count(), 0, "sotto 720px non deve mai comparire il workspace a template");
    assert.equal(await mobilePage.getByRole("dialog", { name: "Anteprima file" }).count(), 1);
    assert.equal(
      await mobilePage.locator(".preview-layout-switcher").isVisible(),
      false,
      "il selettore di layout deve restare nascosto sotto 720px",
    );
    await minimizeVisible(mobilePage, "uno.txt");
    await openDirectoryFile(mobilePage, "due.txt");
    await mobilePage.locator("h2.preview-file-name", { hasText: "due.txt" }).waitFor();

    // Con una finestra visibile in modalità solitaria il tray resta
    // nascosto (GATE-PW-03 punto 3, regola invariata dalla Fase 2): l'altra
    // finestra (uno.txt) è minimizzata ma non ancora mostrata come chip.
    assert.equal(await mobilePage.locator(".preview-tile").count(), 0);
    assert.equal(await mobilePage.getByRole("dialog", { name: "Anteprima file" }).count(), 1);
    assert.equal(await mobilePage.locator(".preview-tray").count(), 0);

    // Minimizzando anche due.txt, nessuna finestra resta visibile: il tray
    // compare con entrambe le chip, mai un template a più tile.
    await minimizeVisible(mobilePage, "due.txt");
    assert.equal(await mobilePage.locator(".preview-tile").count(), 0, "sotto 720px non deve mai comparire il workspace a template");
    assert.equal(await mobilePage.locator(".preview-tray-chip").count(), 2);

    await mobileContext.close();
  }

  // IMP-PW-04-FRONTEND: toggle stella dei preferiti dal browser directory
  // (ADR 015, GATE-PW-04). Sessione dedicata con mock di
  // GET/POST/DELETE /api/v1/favorites.
  {
    const favoritesRequests = [];
    let favoritesStore = [];
    let favoriteSeq = 0;
    const favContext = await browser.newContext({ viewport: { width: 375, height: 667 }, locale: "it-IT" });
    const favPage = await favContext.newPage();
    favPage.setDefaultTimeout(7_000);
    await favPage.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      if (path === "/api/v1/auth/session") return json(route, { username: "admin", role: "admin", csrf_token: "csrf" });
      if (path === "/api/v1/config") return json(route, { allowed_roots: ["/workspace"], workspace_presets: {} });
      if (path === "/api/v1/sessions") return json(route, { sessions: [{ ...session, id: "9", name: "favorites-star" }] });
      if (path === "/api/v1/agent-statuses") return json(route, { statuses: [] });
      if (path === "/api/v1/provider-rate-limits" || path === "/api/v1/orchestrator-state") return json(route, null);
      if (path === "/api/v1/sessions/9/panes") return json(route, { panes: [] });
      if (path === "/api/v1/sessions/9/directory") {
        return json(route, {
          session_id: "9",
          root: "/workspace",
          path: "/workspace",
          parent: null,
          truncated: false,
          entries: [
            { name: "favme.txt", type: "file", size: 4, created_at: "2026-08-19T10:00:00Z", modified_at: "2026-08-20T10:00:00Z" },
          ],
        });
      }
      if (path === "/api/v1/sessions/9/file") {
        const filePath = url.searchParams.get("path");
        return json(route, { session_id: "9", path: filePath, size: 4, content: filePath, truncated: false });
      }
      if (path === "/api/v1/favorites" && request.method() === "GET") {
        return json(route, { favorites: favoritesStore });
      }
      if (path === "/api/v1/favorites" && request.method() === "POST") {
        const body = request.postDataJSON();
        favoriteSeq += 1;
        const created = {
          id: `fav-${favoriteSeq}`,
          path: body.path,
          label: body.label ?? null,
          added_by: "admin",
          added_at: "2026-08-25T10:00:00Z",
        };
        favoritesStore = [created, ...favoritesStore];
        favoritesRequests.push({ method: "POST", path, body });
        return json(route, created, 201);
      }
      if (path.startsWith("/api/v1/favorites/") && request.method() === "DELETE") {
        const id = decodeURIComponent(path.slice("/api/v1/favorites/".length));
        favoritesStore = favoritesStore.filter((item) => item.id !== id);
        favoritesRequests.push({ method: "DELETE", path, id });
        return json(route, { accepted: true }, 200);
      }
      return json(route, { detail: "not found" }, 404);
    });

    await favPage.goto(baseUrl);
    await favPage.locator("button.session-card", { hasText: "favorites-star" }).click();
    await favPage.getByRole("button", { name: "Funzioni", exact: true }).click();
    await favPage.locator(".special-section-toggle").click();
    await favPage.getByRole("button", { name: "Contenuto directory", exact: true }).click();
    await favPage.locator(".directory-open", { hasText: "favme.txt" }).click();
    await favPage.locator("h2.preview-file-name", { hasText: "favme.txt" }).waitFor();

    const star = favPage.getByRole("button", { name: "Aggiungi ai preferiti" });
    await star.waitFor();
    assert.equal(await star.getAttribute("aria-pressed"), "false");
    await star.click();
    await favPage.getByRole("button", { name: "Rimuovi dai preferiti" }).waitFor();
    assert.equal(favoritesRequests.length, 1);
    assert.equal(favoritesRequests[0].method, "POST");
    assert.equal(favoritesRequests[0].body.path, "/workspace/favme.txt");
    assert.equal(await favPage.getByRole("button", { name: "Rimuovi dai preferiti" }).getAttribute("aria-pressed"), "true");

    await favPage.getByRole("button", { name: "Rimuovi dai preferiti" }).click();
    await favPage.getByRole("button", { name: "Aggiungi ai preferiti" }).waitFor();
    assert.equal(favoritesRequests.length, 2);
    assert.equal(favoritesRequests[1].method, "DELETE");
    assert.equal(favoritesRequests[1].id, "fav-1");
    assert.equal(await favPage.getByRole("button", { name: "Aggiungi ai preferiti" }).getAttribute("aria-pressed"), "false");

    await favContext.close();
  }
} finally {
  await browser.close();
}

console.log("Directory/artifact preview navigation browser checks passed");
