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
- [x] Verifica e registrazione formale del gate: flusso manuale completo
  affidabile.

## M1 — Hardening del runtime

- [~] Delta robusti per righe con riconnessione su base sequence inattesa;
  resa ANSI/fullscreen rinviata al terminal mode.
- [x] Selezione, creazione e resize dei pane, con targeting coerente di
  output, input e tasti.
- [x] Stati espliciti per sessione chiusa, disconnessione, backend/tmux non
  disponibile, autenticazione scaduta e conflitto di nome.
- [x] Rate limit configurabile per login e mutazioni, con `Retry-After`.
- [x] Origin policy per WebSocket formalizzata e coperta da test.
- [x] Test di integrazione con tmux reale su socket temporaneo isolato.
- [x] Modalità host-tmux sul socket predefinito dell'utente (ADR 005, che
  supera il socket dedicato previsto in origine).
- [x] Tasti `Up`/`Down`/`Esc` per i prompt di autorizzazione.
- [x] `C-c` (interrupt) dietro conferma esplicita.
- [x] Terminazione della sessione come endpoint separato e confermato.

## M2 — MVP sicuro e persistente

- [x] SQLite/SQLAlchemy con migrazioni Alembic e storage persistente
  validati sull'istanza pubblicata.
- [x] Login con account persistente e hash Argon2id validato sull'istanza
  pubblicata.
- [x] Cookie HttpOnly/SameSite.
- [x] Protezione CSRF.
- [x] Ruoli `admin`/`operator`/`viewer`, gestione utenti e revoca sessioni
  validati sull'istanza pubblicata.
- [x] Allowlist delle directory.
- [x] Profili server-side `shell`/`codex`/`claude` validati sull'istanza
  pubblicata.
- [x] Creazione sessioni.
- [x] Rinomina sessioni tramite id numerico, con nomi contenenti spazi.
- [x] Archive di metadati con rilancio, selettore resume ed eliminazione
  validato sull'istanza pubblicata.
- [x] Audit append-only dei metadati delle operazioni sensibili con vista
  admin validato sull'istanza pubblicata.
- [x] User unit systemd Compose per modalità Docker e host installate e
  validate sull'istanza pubblicata, preservando le sessioni tmux.
- [x] Backup amministrativi di database e snapshot con manifest, checksum,
  retention, download e restore offline validati sull'istanza pubblicata.
- [x] Snapshot persistenti create/list/restore/delete verificati end-to-end
  dopo riavvio VPS.
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

- [x] Quote rate-limit Codex e Claude nella dashboard tramite collector
  sanitizzato host-side, validate sull'istanza pubblicata.
- [ ] Chat blocks.
- [ ] Euristiche di attenzione configurabili.
- [ ] Notifiche PWA locali.
- [~] Manifest PWA presente; service worker e comportamento offline da
  completare.
- [ ] Preferenze.
- [ ] Terminal mode xterm.js e tasti speciali.
- [x] Rinominare il pulsante "Tasti speciali" in "Funzioni speciali".
- [x] Browser "Contenuto directory": navigazione tra cartelle entro
  `MAC_ALLOWED_ROOTS`, ritorno al parent/root, metadati e copy rapido delle
  voci.
- [x] Anteprima in sola lettura dei file UTF-8, con rifiuto dei binari e
  troncamento sicuro a 256 KiB.
- [x] Download autenticato di immagini, PDF e documenti Word dalla directory.
- [x] Filename completi nel browser directory, leggibili su più righe anche
  su schermi mobili.
- [x] Toolbar contestuale per sessione nella dashboard con rinomina e
  terminazione confermata.
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
