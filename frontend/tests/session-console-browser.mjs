import assert from "node:assert/strict";
import { chromium } from "playwright";

const baseUrl = process.env.MAC_BROWSER_BASE_URL || "http://127.0.0.1:4174";

const sessions = [
  { id: "1", name: "osservabilità", attached: false, windows: 1, current_command: "codex", activity_at: "2026-08-02T10:00:00Z", hidden: false },
  { id: "2", name: "analisi qualità", attached: false, windows: 1, current_command: "claude", activity_at: "2026-08-02T10:00:00Z", hidden: false },
];

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
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
  await page.addInitScript(() => {
    class PreviewTestWebSocket {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = 0;
      onopen = null;
      onmessage = null;
      onclose = null;
      constructor() {
        window.setTimeout(() => {
          this.readyState = PreviewTestWebSocket.OPEN;
          this.onopen?.({});
          this.onmessage?.({
            data: JSON.stringify({
              type: "snapshot",
              sequence_id: 1,
              content: "• Ho creato il report `/tmp/mac-preview-browser/report.md`.",
            }),
          });
        }, 0);
      }
      close() {
        this.readyState = PreviewTestWebSocket.CLOSED;
        this.onclose?.({});
      }
    }
    window.WebSocket = PreviewTestWebSocket;
  });
  const commands = [];
  let attachmentSequence = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/session") return json(route, { username: "admin", role: "admin", csrf_token: "csrf" });
    if (path === "/api/v1/config") return json(route, { allowed_roots: ["/workspace"], workspace_presets: {}, claude_history_enabled: false, host_observability_enabled: false });
    if (path === "/api/v1/sessions") return json(route, { sessions });
    if (path === "/api/v1/agent-statuses") return json(route, { statuses: [] });
    if (path === "/api/v1/provider-rate-limits") return json(route, null);
    if (path === "/api/v1/orchestrator-state") return json(route, null);
    if (/^\/api\/v1\/sessions\/\d+\/panes$/.test(path)) return json(route, {
      panes: [{ id: "1", index: 0, title: "main", active: true, width: 80, height: 24 }],
    });
    if (/^\/api\/v1\/sessions\/\d+\/file\/metadata$/.test(path)) return json(route, {
      session_id: "1",
      path: url.searchParams.get("path"),
      size: 19,
      modified_at: "2026-08-22T11:45:00Z",
      media_type: "text/markdown",
    });
    if (/^\/api\/v1\/sessions\/\d+\/file$/.test(path)) return json(route, {
      session_id: "1",
      path: url.searchParams.get("path"),
      size: 19,
      content: "# Report esterno\n",
      truncated: false,
    });
    if (/^\/api\/v1\/sessions\/\d+\/attachments$/.test(path) && request.method() === "POST") {
      attachmentSequence += 1;
      const name = url.searchParams.get("filename");
      return json(route, {
        id: `attachment-${attachmentSequence}`,
        name,
        path: `/workspace/.agent-attachments/1/${name}`,
        media_type: "text/plain",
        size: request.postDataBuffer()?.length || 0,
      }, 201);
    }
    if (/^\/api\/v1\/sessions\/\d+\/(input|keys)$/.test(path) && request.method() === "POST") {
      commands.push({ path, body: request.postDataJSON() });
      return route.fulfill({ status: 202, body: "" });
    }
    return json(route, { detail: "not found" }, 404);
  });

  await page.goto(baseUrl);
  await page.locator("button.session-card", { hasText: "osservabilità" }).click();
  const composer = page.getByPlaceholder("Scrivi o incolla un prompt…");
  await composer.fill("bozza prima sessione");

  await page.getByRole("button", { name: "Cambia sessione" }).click();
  await page.locator(".session-switcher-item", { hasText: "analisi qualità" }).click();
  await composer.fill("bozza seconda sessione");
  await page.getByRole("button", { name: "Cambia sessione" }).click();
  await page.locator(".session-switcher-item", { hasText: "osservabilità" }).click();
  assert.equal(await composer.inputValue(), "bozza prima sessione");

  const previewLink = page.getByRole("button", { name: /Apri anteprima file: \/tmp\/mac-preview-browser\/report\.md/ });
  await previewLink.waitFor();
  await previewLink.click();
  const previewDialog = page.getByRole("dialog", { name: "Anteprima file" });
  await previewDialog.waitFor();
  assert.match(await previewDialog.locator(".preview-modified").innerText(), /22\/08\/2026/);
  await previewDialog.getByRole("heading", { name: "Report esterno" }).waitFor();
  const copyPreviewPath = previewDialog.getByRole("button", {
    name: "Copia percorso: /tmp/mac-preview-browser/report.md",
  });
  await copyPreviewPath.click();
  await previewDialog.locator(".preview-path-copy", { hasText: "Copiato!" }).waitFor();
  assert.equal(
    await page.evaluate(() => navigator.clipboard.readText()),
    "/tmp/mac-preview-browser/report.md",
  );
  await previewDialog.getByRole("button", { name: "Schermo intero" }).click();
  await page.locator(".help-modal-fullscreen").waitFor();
  await previewDialog.getByRole("button", { name: "Torna all'elenco" }).click();
  assert.equal(await previewDialog.count(), 0);

  await page.getByRole("button", { name: "Funzioni", exact: true }).click();
  const specialActions = page.locator(".special-actions");
  await specialActions.waitFor({ state: "visible" });
  const specialActionsBox = await specialActions.boundingBox();
  assert.ok(specialActionsBox && specialActionsBox.width <= 296, "il menu Funzioni deve restare entro il composer mobile");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await page.waitForTimeout(200);
  assert.deepEqual(commands.slice(-2), [
    { path: "/api/v1/sessions/1/input", body: { text: "/clear", attachment_ids: [], pane_id: "1" } },
    { path: "/api/v1/sessions/1/keys", body: { key: "Enter", confirmed: false, pane_id: "1" } },
  ]);
  await page.locator(".file-input").setInputFiles([
    { name: "Screenshot_20260809-013106-con-un-nome-molto-lungo.txt", mimeType: "text/plain", buffer: Buffer.from("uno") },
    { name: "Screenshot_20260809-013107-con-un-altro-nome-molto-lungo.txt", mimeType: "text/plain", buffer: Buffer.from("due") },
  ]);
  await page.locator(".attachment-chip").nth(1).waitFor();

  const widths = await page.evaluate(() => Object.fromEntries(
    ["html", ".console", ".composer", ".attachments", "textarea"].map((selector) => {
      const node = selector === "html" ? document.documentElement : document.querySelector(selector);
      return [selector, [node.scrollWidth, node.clientWidth]];
    }),
  ));
  assert.equal(widths.html[0] <= widths.html[1], true, `document overflow: ${JSON.stringify(widths)}`);
  assert.equal(widths[".console"][1] <= widths.html[1], true, `console oltre il viewport: ${JSON.stringify(widths)}`);
  assert.equal(widths[".composer"][1] <= widths.html[1], true, `composer oltre il viewport: ${JSON.stringify(widths)}`);
  assert.equal(await page.locator(".composer").evaluate((node) => getComputedStyle(node).overflowX), "visible");
  assert.equal(widths.textarea[0] <= widths.textarea[1], true, `textarea overflow: ${JSON.stringify(widths)}`);
  assert.equal(widths[".attachments"][0] > widths[".attachments"][1], true, "gli allegati devono scorrere dentro il form");
  await context.close();
} finally {
  await browser.close();
}

console.log("Session console browser checks passed (block preview, Unicode, drafts, Clear, attachment overflow)");
