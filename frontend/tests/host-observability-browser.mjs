import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { chromium } from "playwright"

const fixture = (name) => JSON.parse(readFileSync(new URL(`fixtures/${name}`, import.meta.url), "utf8"))
const v1 = fixture("host-observability-v1.json")
const v2 = fixture("host-observability-v2.json")

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

async function openHost(browser, snapshot, role = "admin") {
  // La UI sceglie la lingua da navigator.language: senza locale esplicita il
  // probe girerebbe in inglese e non troverebbe nessuna delle etichette attese.
  const context = await browser.newContext({ viewport: { width: 320, height: 720 }, locale: "it-IT" })
  await context.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (value) => { window.__hostCopied = value } },
    })
  })
  const page = await context.newPage()
  page.setDefaultTimeout(7_000)
  let hostRequests = 0
  let failNextHostRequest = false
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/v1/auth/session") return json(route, { username: role, role, csrf_token: "csrf" })
    if (path === "/api/v1/config") return json(route, {
      allowed_roots: ["/workspace"], workspace_presets: {}, claude_history_enabled: false,
      host_observability_enabled: true,
    })
    if (path === "/api/v1/sessions") return json(route, { sessions: [] })
    if (path === "/api/v1/agent-statuses") return json(route, { statuses: [] })
    if (path === "/api/v1/orchestrator-state") return json(route, null)
    if (path === "/api/v1/provider-rate-limits") return json(route, null)
    if (path === "/api/v1/host-observability") {
      hostRequests += 1
      if (failNextHostRequest) {
        failNextHostRequest = false
        return json(route, { detail: "collector unavailable" }, 503)
      }
      return json(route, snapshot)
    }
    return json(route, { detail: "not found" }, 404)
  })
  await page.goto("http://127.0.0.1:4174")
  await page.getByRole("button", { name: /^(Mostra altre azioni|Altre azioni)$/ }).click()
  const hostButton = page.getByRole("button", { name: "Host", exact: true })
  if (role !== "admin") {
    await assert.rejects(hostButton.waitFor({ state: "visible", timeout: 500 }))
    return { context, page, hostRequests: () => hostRequests }
  }
  await hostButton.click()
  await page.locator(`[data-observability-version="${snapshot.schema_version}"]`).waitFor()
  return {
    context, page,
    hostRequests: () => hostRequests,
    failRefresh: () => { failNextHostRequest = true },
  }
}

async function assertNoHorizontalOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
    host: [document.querySelector(".host-view").scrollWidth, document.querySelector(".host-view").clientWidth],
  }))
  assert.ok(sizes.document[0] <= sizes.document[1], `document overflow: ${sizes.document}`)
  assert.ok(sizes.host[0] <= sizes.host[1], `host overflow: ${sizes.host}`)
}

const browser = await chromium.launch({ headless: true })
try {
  {
    const run = await openHost(browser, v2)
    const { page } = run
    assert.equal(run.hostRequests(), 1)
    assert.equal(await page.locator("h1").textContent(), "Host")
    assert.equal(await page.evaluate(() => document.activeElement?.tagName), "H1")
    const cards = page.locator("details.host-card")
    assert.equal(await cards.count(), 7)
    assert.equal(await cards.evaluateAll((items) => items.every((item) => !item.open)), true)
    const processGroups = cards.filter({ has: page.getByRole("heading", { name: "Policy sui processi" }) })
    assert.equal(await processGroups.getAttribute("open"), null)
    assert.equal(await processGroups.locator(".host-process-list").isVisible(), false)
    await processGroups.locator("summary").click()
    assert.equal(await processGroups.locator(".host-process-list").isVisible(), true)

    // verdetto, tessere e tabella dei consumatori sono sopra il dettaglio
    const verdict = page.locator(".host-verdict")
    assert.match(await verdict.innerText(), /1 segnalazione, nessuna critica|segnalazioni, nessuna critica|problem[ai] critic/)
    const kpiText = await page.locator(".host-kpis").innerText()
    assert.match(kpiText, /CARICO PER CPU\n0\.10/i)
    assert.match(kpiText, /SWAP\n68/i)
    assert.match(kpiText, /Attività non accertata: campione non disponibile/)

    const consumers = page.locator(".host-consumers")
    assert.match(await consumers.innerText(), /Swap attribuita ai processi osservati: 600 B su 700 B/)
    // swap non accertata per tmux: "n/a", mai 0
    assert.match(await consumers.locator("tbody").innerText(), /tmux[\s\S]*n\/a/)
    await consumers.getByRole("tab", { name: "Swap" }).click()
    const swapRows = await consumers.locator("tbody tr").allInnerTexts()
    assert.match(swapRows[0], /gnome-shell/, "la classifica per swap non segue quella per memoria")
    assert.match(swapRows[1], /Agents/)
    await consumers.getByRole("tab", { name: "Gruppi" }).click()
    assert.match(await consumers.locator("tbody").innerText(), /Workers[\s\S]*n\/a/)
    await consumers.getByRole("tab", { name: "Container" }).click()
    const containerRows = await consumers.locator("tbody").innerText()
    assert.match(containerRows, /Backend[\s\S]*attivo[\s\S]*117 MB/)
    // il non critico fermo va in cima: è lì che c'è una decisione da prendere
    assert.match(containerRows, /Web[\s\S]*non critico[\s\S]*fermo/)
    assert.ok(containerRows.indexOf("Web") < containerRows.indexOf("Backend"))
    // e compare fra le righe da vedere, senza contare come segnalazione
    assert.match(await page.locator(".host-issues").innerText(), /Web: fermo/)
    assert.match(await page.locator(".host-verdict").innerText(), /2 non critici fermi/)
    assert.match(await consumers.innerText(), /Stato Docker raccolto 27s fa, non all'apertura di questa pagina/)
    assert.match(await consumers.innerText(), /2 container senza label configurata non sono elencati/)

    await consumers.getByRole("tab", { name: "Servizi" }).click()
    const serviceRows = await consumers.locator("tbody").innerText()
    // il non critico fermo va in cima, come per i container
    assert.ok(serviceRows.indexOf("Example frontend") < serviceRows.indexOf("Example API"))
    assert.match(serviceRows, /Example API[\s\S]*systemd utente · strategico · 4 riavvii[\s\S]*attivo/)
    assert.match(serviceRows, /Batch runner[\s\S]*non accertato/)
    // un supervisore muto non è la prova che i suoi servizi siano caduti: la
    // riga lo nomina come non accertato, non come fermo
    const issueText = await page.locator(".host-issues").innerText()
    assert.match(issueText, /Supervisore non raggiunto/)
    assert.match(issueText, /Interessati: Batch runner \(non accertato\)/)
    assert.match(issueText, /Example frontend: fermo/)
    assert.doesNotMatch(issueText, /Batch runner: /)
    assert.match(await consumers.innerText(), /1 app pm2 senza policy configurata non sono elencate/)
    assert.match(await consumers.innerText(), /I riavvii sono mostrati ma non giudicati/)
    await consumers.getByRole("tab", { name: "Memoria" }).click()
    await cards.evaluateAll((items) => items.forEach((item) => { item.open = true }))
    await page.locator("details.host-reading-guide").evaluate((item) => { item.open = true })
    await page.getByText("Fatti locali", { exact: true }).first().waitFor()
    await page.getByText("Valutazione", { exact: true }).first().waitFor()
    await page.getByText("Non accertato", { exact: true }).first().waitFor()
    const emptyAssessmentMatrix = {
      ok: "Nessuna anomalia rilevata dai controlli disponibili.",
      warning: "Attenzione rilevata; il collector non ha fornito un dettaglio della valutazione.",
      critical: "Stato critico rilevato; il collector non ha fornito un dettaglio della valutazione.",
      unknown: "Valutazione non disponibile: l’esito non è accertato.",
    }
    for (const [status, expectedText] of Object.entries(emptyAssessmentMatrix)) {
      const assessments = page.locator(`.host-card.status-${status} .host-assessment`)
      await assessments.filter({ hasText: expectedText }).first().waitFor()
      if (status !== "ok") {
        assert.equal(
          await assessments.filter({ hasText: "Nessuna anomalia rilevata" }).count(),
          0,
          `${status} con reasons vuoti non deve essere presentato come privo di anomalie`,
        )
      }
    }
    await page.getByText(/Valutazione policy: Policy locale violata/).first().waitFor()
    await page.getByText(/Valutazione policy: Policy locale non configurata/).first().waitFor()
    assert.equal(await page.getByText("Raggiungibilità esterna: non accertata", { exact: true }).count(), 3)
    assert.match(await page.locator("main").innerText(), /non viene interpretato come attività zero/i)
    assert.doesNotMatch(await page.locator("main").innerText(), /raggiungibilità[^\n]*(sicura|chiusa)/i)
    for (const port of [22, 8080, 9090]) await page.getByText(`TCP ${port}`, { exact: true }).waitFor()
    await assertNoHorizontalOverflow(page)

    const buttons = await page.locator("main button:visible").all()
    for (const button of buttons) {
      const box = await button.boundingBox()
      assert.ok(box && box.height >= 44, `touch target too short: ${box?.height}`)
    }

    await page.getByText("Esporta snapshot JSON", { exact: true }).click()
    const textarea = page.getByRole("textbox", { name: "JSON snapshot osservabilità host" })
    const expected = JSON.stringify(v2, null, 2)
    assert.equal(await textarea.inputValue(), expected)
    assert.deepEqual(JSON.parse(await textarea.inputValue()), v2)
    await page.getByRole("button", { name: "Copia JSON" }).click()
    assert.equal(await page.evaluate(() => window.__hostCopied), expected)
    assert.equal(run.hostRequests(), 1)

    await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined }))
    await page.getByRole("button", { name: "Copia JSON" }).click()
    assert.equal(await textarea.evaluate((node) => document.activeElement === node), true)
    assert.deepEqual(await textarea.evaluate((node) => [node.selectionStart, node.selectionEnd]), [0, expected.length])

    await page.getByRole("button", { name: "Aggiorna osservabilità host" }).click()
    await page.waitForFunction(() => !document.querySelector("button.host-refresh")?.hasAttribute("disabled"))
    assert.equal(run.hostRequests(), 2)
    await page.waitForTimeout(3200)
    assert.equal(run.hostRequests(), 2, "la vista Host non deve introdurre polling")

    run.failRefresh()
    await page.getByRole("button", { name: "Aggiorna osservabilità host" }).click()
    await page.getByText(/backend o tmux non è disponibile/i).waitFor()
    assert.equal(await textarea.inputValue(), expected, "un refresh fallito deve preservare l'ultimo snapshot")
    await run.context.close()
  }

  {
    const run = await openHost(browser, v1)
    const { page } = run
    assert.equal(run.hostRequests(), 1)
    assert.match(await page.locator("main").innerText(), /Contratto v1 legacy/)
    await page.locator("details.host-card").evaluateAll((items) => items.forEach((item) => { item.open = true }))
    assert.match(await page.locator("main").innerText(), /Snapshot legacy v1: policy locale e raggiungibilità esterna non sono disponibili/i)
    assert.equal(await page.getByText("Raggiungibilità esterna: non accertata", { exact: true }).count(), 0)
    assert.equal(await page.getByText("TCP 8081", { exact: true }).count(), 1)
    await assertNoHorizontalOverflow(page)
    await page.getByText("Esporta snapshot JSON", { exact: true }).click()
    assert.deepEqual(JSON.parse(await page.getByRole("textbox", { name: "JSON snapshot osservabilità host" }).inputValue()), v1)
    await run.context.close()
  }

  {
    // swap piena ma ferma: il caso che la vista deve saper distinguere
    const idle = {
      ...v2,
      memory: {
        ...v2.memory,
        reasons: ["swap_used_high"],
        swap_used_bytes: 1024, swap_used_percent: 100,
        swap_io_sample: { available: true, duration_ms: 101, pages_in_delta: 0, pages_out_delta: 0 },
      },
    }
    const run = await openHost(browser, idle)
    const { page } = run
    assert.match(await page.locator(".host-verdict").innerText(), /memoria parcheggiata, non un collo di bottiglia/)
    assert.match(await page.locator(".host-kpis").innerText(), /inattiva/i)
    assert.match(await page.locator(".host-kpis").innerText(), /Nessuna pagina letta o scritta in 101 ms/)
    await assertNoHorizontalOverflow(page)
    await run.context.close()
  }

  for (const role of ["viewer", "operator"]) {
    const run = await openHost(browser, v2, role)
    assert.equal(run.hostRequests(), 0, `${role} non deve effettuare richieste Host`)
    await run.context.close()
  }
} finally {
  await browser.close()
}

console.log("Host observability browser checks passed (320px, v1/v2, roles, copy, refresh)")
