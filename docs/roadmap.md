# Roadmap tecnica

## Legenda

- [x] disponibile, deployato e validato quando la voce è funzionale;
- [ ] da realizzare;
- [~] parzialmente disponibile o da completare.

## Stato sintetico e ordine di avanzamento

- M0: concluso.
- M1: terminal mode xterm.js con resa ANSI reale validata sull'istanza
  pubblicata (colori e resize confermati); resta comunque il limite noto di
  scrollback per le app a schermo alternato (limite tmux, non risolvibile
  da qui).
- M2 e M2A: conclusi.
- M3: gran parte rilasciata; service worker, offline, notifiche locali e
  preferenze (vista predefinita) validati sull'istanza pubblicata (TLS via
  ADR 008).
- M4: cronologia Claude anticipata e conclusa; "Gestione allegati avanzata"
  completa (persistenza, anteprime, quote aggregate, deduplica, retention);
  prossimo blocco consigliato: ricerca/tag/template, multi-pane esteso, Web
  Push o riepiloghi.

Stato read-only dei task dell'orchestratore locale: resta solo in roadmap,
intenzionalmente non implementato — dipende da un sistema esterno privato,
non presente in questo repository pubblico e agent-agnostic per scelta; il
contratto (file JSON sanitizzato o collector su API locale, senza
credenziali/prompt/output/comandi di controllo) sarà formalizzato quando
verrà preso in carico.

Euristica "Attende feedback" troppo stretta (richiede `?` letterale): non
prioritaria, da riprendere — vedi `docs/backlog.md`.

Ordine corrente: operatività M4 restante → (se ripreso) stato orchestratore
locale / euristica attenzione.

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

- [x] Delta robusti per righe con riconnessione su base sequence inattesa;
  resa ANSI reale via terminal mode xterm.js (M3), fullscreen/scrollback
  delle app a schermo alternato resta un limite noto di `tmux capture-pane`
  (`docs/backlog.md`).
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
- [x] Controlli contestuali dei permessi: `/permissions` per Codex e
  `Shift+Tab` per Claude, validati sull'istanza pubblicata.
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
- [x] Gate: deployment Tailscale verificato senza porta pubblica
  (`docs/gates/tailscale-deployment.md`).

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
- [ ] Stato read-only dei task dell'orchestratore locale: provider, stato,
  pausa per capacità, prossimo tentativo, fallback e avanzamento del
  checkpoint. Da alimentare con un collector host-side sanitizzato, senza
  credenziali, prompt o comandi di controllo nella console.
- [x] Chat blocks opzionali per Codex/Claude con ritorno immediato alla vista
  terminale, validati sull'istanza pubblicata.
- [x] Euristiche di attenzione Codex/Claude con stati attivo, inattivo,
  feedback, autorizzazione e sconosciuto, validate sull'istanza pubblicata.
- [x] Badge separato per il livello permessi delle sessioni agentiche, con
  collector strutturato host-side, fallback euristico e legenda completa,
  validato sull'istanza pubblicata.
- [x] Percentuale della finestra di contesto per sessione Codex/Claude tramite
  metadati strutturati sanitizzati, validata sull'istanza pubblicata.
- [x] Notifiche PWA locali: avviso quando una sessione passa a "attende
  feedback"/"attende autorizzazione" mentre l'app è in background, gated da
  permesso e preferenza utente, senza contenuto di output/prompt nel corpo
  della notifica (coerente con l'invariante di sicurezza), validate
  sull'istanza pubblicata con TLS (ADR 008). Limite noto: il rilevamento
  gira solo mentre la lista sessioni è montata (non mentre si è dentro la
  console di un'altra sessione), perché lo stato euristico è interrogato
  lì — vedi `docs/backlog.md`.
- [x] Service worker con cache dell'app shell "network-first" per un
  caricamento offline best-effort (mai per le chiamate `/api/`, sempre
  autoritative) e banner "connessione assente" globale; manifest PWA
  presente. Validato sull'istanza pubblicata con TLS (ADR 008).
- [x] Preferenze: pannello "Preferenze" nella dashboard con la vista
  predefinita (Blocchi/Terminale) per l'apertura delle sessioni Codex/Claude,
  persistita in `localStorage`. Scope volutamente minimo per la prima
  versione; altre preferenze (es. consolidare qui il toggle Notifiche) restano
  da valutare in seguito.
- [x] Terminal mode xterm.js: la vista Terminale usa xterm.js in sola
  visualizzazione (`disableStdin`) con resa ANSI reale (`capture-pane -e`
  opt-in, solo per questa vista — euristiche di attenzione e altri
  consumatori restano su testo semplice), resize preciso via `FitAddon`.
  Protocollo e modello di input invariati per scelta esplicita: snapshot/
  delta e riconnessione autorevole restano gli stessi (niente byte-stream
  incrementale), input sempre compose-poi-invia via `load-buffer`/
  `paste-buffer` (niente digitazione live nel widget). "Tasti speciali"
  restano gli attuali bottoni dedicati verso `/keys`, invariati. Non risolve
  lo scrollback delle app a schermo alternato (limite `tmux capture-pane`,
  vedi `docs/backlog.md`).
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
- [x] Cronologia Claude opzionale con collector minimizzato, feature flag,
  fallback live e rollback isolato, validata sull'istanza pubblicata.
- [ ] Ricerca, tag e template.
- [ ] Supporto multi-pane esteso: layout, navigazione e gestione completa;
  selezione, split e resize di base sono già disponibili in M1.
- [x] Gestione allegati avanzata: persistenza dei metadati in tabella
  `attachments` (SQLite/Alembic, come utenti/archivi/audit), con backfill dai
  vecchi sidecar JSON in migrazione. Richiede il database (stesso gate 503
  già usato da archivi/audit se `MAC_DATABASE_AUTH_ENABLED` è spento).
  Anteprime: thumbnail JPEG best-effort (max 256×256, via Pillow) generata
  all'upload per le immagini, servita da un endpoint autenticato dedicato e
  rimossa insieme all'allegato (esplicita, per TTL o per fine sessione);
  mostrata nel composer al posto del solo nome file. Quote aggregate: limite
  di byte totali per sessione (`MAC_MAX_ATTACHMENT_BYTES_PER_SESSION`, oltre
  al limite per singolo file), verificato prima della scrittura su disco.
  Deduplica per sessione: upload con contenuto identico (stesso hash SHA-256)
  nella stessa sessione riusa il file fisico già presente invece di
  riscriverlo, con conteggio dei riferimenti al delete/TTL. Retention legata
  al ciclo di vita: terminare o archiviare una sessione rimuove subito i suoi
  allegati (non solo al TTL), perché tmux può riassegnare l'id numerico
  liberato a una sessione futura scollegata. Validato sull'istanza
  pubblicata, incluse le anteprime nel composer.
- [ ] Riepiloghi opzionali.

## M5 — Espansioni

- [ ] Multi-host con daemon su Tailscale.
- [ ] App Android riusando i contratti TypeScript.
- [ ] Orchestrazione agentica, solo dopo la stabilizzazione del core.
