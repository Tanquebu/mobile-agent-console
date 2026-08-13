import assert from "node:assert/strict"
import { chromium } from "playwright"

const baseURL = process.env.MAC_LIVE_BASE_URL
const password = process.env.MAC_LIVE_ADMIN_PASSWORD
assert.ok(baseURL && password, "MAC_LIVE_BASE_URL e MAC_LIVE_ADMIN_PASSWORD sono richiesti")
const iterations = Number.parseInt(process.env.MAC_LIVE_ITERATIONS ?? "1", 10)
assert.ok(Number.isSafeInteger(iterations) && iterations >= 1 && iterations <= 10)
const abortRefresh = process.env.MAC_LIVE_ABORT_REFRESH === "1"

const browser = await chromium.launch({ headless: true })
try {
  for (let iteration = 0; iteration < iterations; iteration += 1) {
  const context = await browser.newContext({
    viewport: { width: 320, height: 720 },
    ignoreHTTPSErrors: true,
  })
  await context.addInitScript(() => Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: async (value) => { window.__hostCopied = value } },
  }))
  const page = await context.newPage()
  page.setDefaultTimeout(10_000)
  let hostRequests = 0
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/host-observability") hostRequests += 1
  })
  await page.goto(baseURL)
  await page.getByLabel("Nome utente").fill("admin")
  await page.locator('input[type="password"]').fill(password)
  await page.getByRole("button", { name: "Continua" }).click()
  await page.getByRole("heading", { name: "Sessions" }).waitFor()
  await page.locator("button.dashboard-more-actions").click()
  const initialResponsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/host-observability",
  )
  await page.getByRole("button", { name: "Host" }).click()
  const initialResponse = await initialResponsePromise
  assert.ok(initialResponse.ok(), `initial Host response: ${initialResponse.status()}`)
  const latestSnapshot = await initialResponse.json()
  await initialResponse.finished()
  await page.locator('[data-observability-version="3"]').waitFor()
  assert.equal(latestSnapshot.tmux_orphans?.available, true)
  assert.equal(latestSnapshot.tmux_orphans?.items?.length, 1)
  assert.equal(hostRequests, 1)
  assert.equal(await page.evaluate(() => document.activeElement?.tagName), "H1")
  const cards = page.locator("details.host-card")
  assert.equal(await cards.count(), 8)
  assert.equal(await cards.evaluateAll((items) => items.every((item) => !item.open)), true)
  const processGroups = cards.filter({ has: page.getByRole("heading", { name: /^(Policy sui processi|Process policies)$/ }) })
  assert.equal(await processGroups.locator(".host-process-list").isVisible(), false)
  await processGroups.locator("summary").click()
  assert.equal(await processGroups.locator(".host-process-list").isVisible(), true)
  assert.ok(await page.getByText("Raggiungibilità esterna: non accertata", { exact: true }).count() > 0)
  assert.doesNotMatch(await page.locator("main").innerText(), /raggiungibilità[^\n]*(sicura|chiusa)/i)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  assert.ok(overflow <= 0, `overflow orizzontale: ${overflow}px`)
  await page.waitForTimeout(3_200)
  assert.equal(hostRequests, 1, "la vista live non deve effettuare polling Host")

  await page.getByText("Esporta snapshot JSON", { exact: true }).click()
  const textarea = page.getByRole("textbox", { name: "JSON snapshot osservabilità host" })
  assert.deepEqual(JSON.parse(await textarea.inputValue()), latestSnapshot)
  await page.getByRole("button", { name: "Copia JSON" }).click()
  assert.equal(await page.evaluate(() => window.__hostCopied), await textarea.inputValue())
  assert.equal(hostRequests, 1)
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined }))
  await page.getByRole("button", { name: "Copia JSON" }).click()
  assert.equal(await textarea.evaluate((node) => document.activeElement === node), true)
  assert.deepEqual(await textarea.evaluate((node) => [node.selectionStart, node.selectionEnd]), [0, (await textarea.inputValue()).length])

  const refreshResponsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/host-observability",
  )
  await page.getByRole("button", { name: "Aggiorna osservabilità host" }).click()
  const refreshResponse = await refreshResponsePromise
  assert.ok(refreshResponse.ok(), `refresh Host response: ${refreshResponse.status()}`)
  const refreshedSnapshot = await refreshResponse.json()
  await refreshResponse.finished()
  await page.waitForFunction(() => !document.querySelector("button.host-refresh")?.hasAttribute("disabled"))
  assert.deepEqual(JSON.parse(await textarea.inputValue()), refreshedSnapshot)
  assert.equal(hostRequests, 2)
  if (abortRefresh) {
    const abortRequestPromise = page.waitForRequest(
      (request) => new URL(request.url()).pathname === "/api/v1/host-observability",
    )
    const abortClick = page.getByRole("button", { name: "Aggiorna osservabilità host" }).click()
    await abortRequestPromise
    await context.close()
    await abortClick.catch(() => undefined)
  } else {
    await context.close()
  }
  }
} finally {
  await browser.close()
}

console.log(`Live Host v3 browser gate passed ${iterations}× (320px, orphan scope, export, clipboard, no polling${abortRefresh ? ", controlled abort" : ""})`)
