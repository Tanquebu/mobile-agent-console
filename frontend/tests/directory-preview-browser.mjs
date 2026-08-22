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
  await page.locator("button.session-card", { hasText: session.name }).click();
  await page.getByRole("button", { name: "Funzioni", exact: true }).click();
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
  await page.locator("h2.directory-path", { hasText: "alpha.txt" }).waitFor();
  assert.match(await page.locator(".preview-modified").innerText(), /20\/08\/2026/);
  assert.equal(await page.getByRole("button", { name: "File successivo" }).isDisabled(), true);
  await page.getByRole("button", { name: "Esci da schermo intero", exact: true }).click();
  assert.equal(await page.locator(".help-modal-fullscreen").count(), 0);

  await page.getByRole("button", { name: "Torna all'elenco" }).click();
  await page.getByRole("button", { name: "Chiudi" }).click();
  await page.getByRole("button", { name: "Artefatti", exact: true }).click();
  await page.getByLabel("Ordina").selectOption("date-desc");
  await page.locator(".directory-open", { hasText: "zeta.txt" }).click();
  await assertPosition(page, "1 / 2");
  assert.match(await page.locator(".preview-modified").innerText(), /22\/08\/2026/);
  await page.getByRole("button", { name: "File successivo" }).click();
  await assertPosition(page, "2 / 2");
  await page.locator("h2.directory-path", { hasText: "alpha.md" }).waitFor();
  assert.match(await page.locator(".preview-modified").innerText(), /20\/08\/2026/);

  const layout = await page.locator(".preview-navigation").evaluate((node) => ({
    scrollWidth: node.scrollWidth,
    clientWidth: node.clientWidth,
    buttonHeights: [...node.querySelectorAll("button")].map((button) => button.getBoundingClientRect().height),
  }));
  assert.ok(layout.scrollWidth <= layout.clientWidth, `overflow navigazione: ${JSON.stringify(layout)}`);
  assert.ok(layout.buttonHeights.every((height) => height >= 40), `target troppo piccoli: ${JSON.stringify(layout)}`);
  await context.close();
} finally {
  await browser.close();
}

console.log("Directory/artifact preview navigation browser checks passed");
