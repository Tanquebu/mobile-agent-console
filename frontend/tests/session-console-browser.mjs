import assert from "node:assert/strict";
import { chromium } from "playwright";

const sessions = [
  { id: "1", name: "osservabilità", attached: false, windows: 1, current_command: "codex", activity_at: "2026-08-02T10:00:00Z", hidden: false },
  { id: "2", name: "analisi qualità", attached: false, windows: 1, current_command: "claude", activity_at: "2026-08-02T10:00:00Z", hidden: false },
];

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 320, height: 720 } });
  const page = await context.newPage();
  page.setDefaultTimeout(7_000);
  const commands = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/session") return json(route, { username: "admin", role: "admin", csrf_token: "csrf" });
    if (path === "/api/v1/config") return json(route, { allowed_roots: ["/workspace"], workspace_presets: {}, claude_history_enabled: false, host_observability_enabled: false });
    if (path === "/api/v1/sessions") return json(route, { sessions });
    if (path === "/api/v1/agent-statuses") return json(route, { statuses: [] });
    if (path === "/api/v1/provider-rate-limits") return json(route, null);
    if (path === "/api/v1/orchestrator-state") return json(route, null);
    if (/^\/api\/v1\/sessions\/\d+\/panes$/.test(path)) return json(route, { panes: [] });
    if (/^\/api\/v1\/sessions\/\d+\/(input|keys)$/.test(path) && request.method() === "POST") {
      commands.push({ path, body: request.postDataJSON() });
      return route.fulfill({ status: 202, body: "" });
    }
    return json(route, { detail: "not found" }, 404);
  });

  await page.goto("http://127.0.0.1:4174");
  await page.locator("button.session-card", { hasText: "osservabilità" }).click();
  const composer = page.getByPlaceholder("Scrivi o incolla un prompt…");
  await composer.fill("bozza prima sessione");

  await page.getByRole("button", { name: "Cambia sessione" }).click();
  await page.locator(".session-switcher-item", { hasText: "analisi qualità" }).click();
  await composer.fill("bozza seconda sessione");
  await page.getByRole("button", { name: "Cambia sessione" }).click();
  await page.locator(".session-switcher-item", { hasText: "osservabilità" }).click();
  assert.equal(await composer.inputValue(), "bozza prima sessione");

  await page.getByRole("button", { name: "Funzioni speciali" }).click();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await page.getByRole("button", { name: "Clear", exact: true }).waitFor();
  assert.deepEqual(commands.slice(-2), [
    { path: "/api/v1/sessions/1/input", body: { text: "/clear", attachment_ids: [] } },
    { path: "/api/v1/sessions/1/keys", body: { key: "Enter", confirmed: false } },
  ]);
  assert.equal(await page.locator("html").evaluate((node) => node.scrollWidth <= node.clientWidth), true);
  await context.close();
} finally {
  await browser.close();
}

console.log("Session console browser checks passed (Unicode, per-session drafts, Clear)");
