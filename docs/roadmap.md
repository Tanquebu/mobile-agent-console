# Roadmap tecnica

## Legenda

- [x] disponibile nel repository;
- [ ] da realizzare;
- [~] parzialmente disponibile o da completare.

## M0 — Fondazioni e vertical slice

- [x] Documentazione iniziale e ADR.
- [x] Servizio tmux isolato.
- [x] API list/create/capture/input/Enter.
- [x] WebSocket a snapshot completi.
- [x] UI mobile-first.
- [x] Gateway fake e test API senza agenti reali.
- [ ] Verifica e registrazione formale del gate: flusso manuale completo
  affidabile.

## M1 — Hardening del runtime

- [ ] Gestione robusta dei delta e delle sequenze ANSI.
- [ ] Selezione pane e resize.
- [~] Stati di errore espliciti.
- [ ] Rate limit.
- [x] Origin policy per WebSocket formalizzata e coperta da test.
- [ ] Test di integrazione con tmux reale.
- [x] Modalità host-tmux sul socket predefinito dell'utente (ADR 005, che
  supera il socket dedicato previsto in origine).
- [x] Tasti `Up`/`Down`/`Esc` per i prompt di autorizzazione.
- [x] `C-c` (interrupt) dietro conferma esplicita.
- [x] Terminazione della sessione come endpoint separato e confermato.

## M2 — MVP sicuro e persistente

- [ ] SQLite/SQLAlchemy.
- [ ] Login con hash Argon2.
- [x] Cookie HttpOnly/SameSite.
- [x] Protezione CSRF.
- [ ] Ruoli.
- [x] Allowlist delle directory.
- [~] Profili server-side (presente il solo profilo `shell`).
- [x] Creazione sessioni.
- [ ] Rename e archive.
- [ ] Audit metadata.
- [~] Unit systemd da completare e validare per entrambe le modalità tmux.
- [ ] Backup.
- [ ] Gate: deployment Tailscale verificato senza porta pubblica.

### M2A — Allegati minimali ai prompt

Questa feature è anticipata rispetto all'upload operativo completo di M4.
Il terminale resta agent-agnostic: gli allegati sono file in un'area
controllata e il prompt riceve riferimenti ai relativi path, senza introdurre
API specifiche di Codex, Claude o altri agenti.

- [x] Storage locale dedicato, condiviso con il runtime tmux.
- [x] Upload autenticato e protetto da CSRF.
- [x] Nome fisico generato dal server e path traversal impedito.
- [x] Allowlist iniziale di immagini, PDF e file testuali.
- [x] Limite configurabile per file e massimo 5 allegati per prompt.
- [x] Composer mobile con selezione, stato upload e rimozione dal prompt.
- [x] Invio del testo con `attachment_ids`; riferimenti ai path composti dal
  backend.
- [x] Test manuale end-to-end da frontend con immagine leggibile dalla
  sessione agente.
- [x] Test per autorizzazione, limiti, tipi non ammessi, traversal e
  associazione alla sessione.
- [x] Limite coerente del request body sul reverse proxy.
- [x] Eliminazione esplicita dal composer e cleanup automatico TTL degli
  allegati temporanei.

## M3 — Esperienza MVP

- [ ] Chat blocks.
- [ ] Euristiche di attenzione configurabili.
- [ ] Notifiche PWA locali.
- [~] Manifest PWA presente; service worker e comportamento offline da
  completare.
- [ ] Preferenze.
- [ ] Terminal mode xterm.js e tasti speciali.
- [x] Rinominare il pulsante "Tasti speciali" in "Funzioni speciali".
- [x] Modale "Contenuto directory": elenco di file e cartelle della working
  directory della sessione (nome, tipo, dimensione, data di creazione) con
  pulsante di copy per voce, per agevolare comandi successivi (`cat`, `cd`,
  ecc.). Endpoint di sola lettura `GET /sessions/{id}/directory` che elenca
  la directory di lavoro corrente del pane lato server (mai un path
  arbitrario proveniente dal client) rispettando `MAC_ALLOWED_ROOTS`.
- [x] Form di creazione sessione responsive anche con path molto lunghi.
- [x] Autoscroll intelligente: pausa quando l'utente risale l'output e
  ripresa esplicita tramite pulsante.
- [x] Contenimento mobile dell'output e scroll limitato al riquadro terminale.
- [x] Guida rapida in-app con “What's new” limitato all'ultima funzionalità
  rilasciata.

Integrazione con sistemi esterni di monitoraggio degli agenti: un daemon
che osservi i pane sullo stesso server tmux host e ne classifichi lo stato
(es. `active`/`idle`/`stalled`/`waiting_input`) può alimentare, via API di
stato locale, badge di attenzione sulla lista sessioni e il caso "l'agente
attende un'autorizzazione", senza duplicare il monitoraggio nella console;
un canale di notifica esterno può coprire l'avviso remoto finché le
notifiche PWA non sono pronte. Da formalizzare: contratto di stato
condiviso e mappatura pane ↔ session id.

## M4 — Operatività

- [ ] Web Push.
- [ ] Cronologia opzionale.
- [ ] Ricerca, tag e template.
- [ ] Supporto multi-pane.
- [ ] Gestione allegati avanzata: persistenza dei metadati, anteprime,
  deduplicazione, quote aggregate e policy di conservazione.
- [ ] Riepiloghi opzionali.

## M5 — Espansioni

- [ ] Multi-host con daemon su Tailscale.
- [ ] App Android riusando i contratti TypeScript.
- [ ] Orchestrazione agentica, solo dopo la stabilizzazione del core.
