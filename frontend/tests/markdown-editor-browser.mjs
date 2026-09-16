import assert from "node:assert/strict";
import { chromium } from "playwright";

const baseUrl = process.env.MAC_BROWSER_BASE_URL || "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, args: ["--disable-gpu", "--renderer-process-limit=1"] });
try {
  for (const width of [375, 1024]) {
    const context = await browser.newContext({ viewport: { width, height: 800 }, locale: "it-IT", serviceWorkers: "block" });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on("pageerror", (error) => console.error(error.message));
    let document = { path: "/workspace/notes.md", content: "# Originale", revision: "a".repeat(64) };
    let failSave = false;
    const saved = [];
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (path === "/api/v1/auth/session") return json({ username: "admin", role: "admin", csrf_token: "csrf" });
      if (path === "/api/v1/config") return json({ allowed_roots: ["/workspace"], workspace_presets: {} });
      if (path === "/api/v1/sessions") return json({ sessions: [{ id: "1", name: "markdown-test", attached: false, windows: 1, current_command: "bash", activity_at: new Date().toISOString(), hidden: false }] });
      if (path === "/api/v1/agent-statuses") return json({ statuses: [] });
      if (path === "/api/v1/favorites") return json({ favorites: [] });
      if (path.endsWith("/panes")) return json({ panes: [] });
      if (path.endsWith("/directory")) return json({ session_id: "1", path: "/workspace", root: "/workspace", parent: null, entries: [{ name: "notes.md", type: "file", size: 11 }], truncated: false });
      if (path.endsWith("/file")) return json({ ...document, session_id: "1", size: 11, truncated: false, editable: true });
      if (path.endsWith("/file/markdown")) {
        if (request.method() === "GET") return json(document);
        assert.equal(request.headers()["x-csrf-token"], "csrf");
        if (failSave) return json({ detail: "File changed on disk" }, 409);
        const body = request.postDataJSON();
        assert.equal(body.revision, document.revision);
        document = { ...body, revision: "b".repeat(64) };
        saved.push(body);
        return json(document);
      }
      return json({ detail: "not found" }, 404);
    });
    await page.goto(baseUrl);
    await page.locator("button.session-card", { hasText: "markdown-test" }).click();
    await page.getByRole("button", { name: "Funzioni", exact: true }).click();
    await page.locator(".special-section-toggle").click();
    await page.getByRole("button", { name: "Contenuto directory", exact: true }).click();
    await page.locator(".directory-open", { hasText: "notes.md" }).click();
    await page.getByRole("button", { name: "Modifica Markdown", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "Modifica Markdown", exact: true });
    const input = editor.getByRole("textbox", { name: "Testo Markdown" });
    await input.fill("# Modificato 🌱\n\nTesto");
    await editor.getByRole("button", { name: "Formattato", exact: true }).click();
    await editor.getByRole("heading", { name: "Modificato 🌱", exact: true }).waitFor();
    await editor.getByRole("button", { name: "Sorgente", exact: true }).click();
    assert.equal(await input.inputValue(), "# Modificato 🌱\n\nTesto");
    // Escape is captured before handlers of the preview/directory underneath.
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.keyboard.press("Escape");
    assert.equal(await editor.count(), 1);
    await editor.getByRole("button", { name: "Salva", exact: true }).click();
    await editor.getByText("File salvato", { exact: true }).waitFor();
    assert.equal(saved.length, 1);
    await input.fill("Draft to preserve");
    failSave = true;
    await editor.getByRole("button", { name: "Salva", exact: true }).click();
    await editor.getByRole("alert").filter({ hasText: "Il file è cambiato" }).waitFor();
    assert.equal(await input.inputValue(), "Draft to preserve");
    failSave = false;
    await input.fill("");
    await editor.getByRole("button", { name: "Salva", exact: true }).click();
    await editor.getByText("File salvato", { exact: true }).waitFor();
    assert.equal(document.content, "");
    const box = await editor.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= width + 1);
    await editor.getByRole("button", { name: "Chiudi", exact: true }).last().click();
    assert.equal(await editor.count(), 0);
    await page.getByText("(file vuoto)", { exact: true }).waitFor();
    await context.close();
  }
} finally {
  await browser.close();
}
console.log("Markdown editing browser checks passed (mobile + desktop)");
