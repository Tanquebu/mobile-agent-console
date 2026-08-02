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
- M3: gran parte rilasciata; service worker, offline e preferenze (vista
  predefinita) validati sull'istanza pubblicata (TLS via ADR 008); le
  notifiche locali di M3 sono state superate dal Web Push di M4.
- M4: concluso, con l'eccezione dello storico del consumo di budget e
  attribuzione per sessione (ADR 010), approvato il 02/08/2026 e in corso:
  fase A (serie storica della quota provider) implementata, non ancora
  deployata; fase B (attribuzione per sessione) in corso. Cronologia Claude
  anticipata; "Gestione allegati avanzata"
  completa (persistenza, anteprime, quote aggregate, deduplica, retention);
  "Supporto multi-pane esteso" completo (chiusura pane, split orizzontale/
  verticale; la vista con più pane simultanei è stata scartata
  deliberatamente per l'impatto mobile-first); Web Push completo (poller
  backend sempre attivo, sostituisce le notifiche locali client-side);
  ricerca testuale sessioni completa; correzioni rendering Blocchi/
  Terminale/Cronologia (larghezza pane, scroll touch, indicatore attività,
  lazy-load xterm.js); riepiloghi euristici di sessione completi. Tag/
  etichette e template di creazione restano da fare, non richiesti finora.

Lo stato read-only dei task dell'orchestratore è un adapter opzionale e
agent-agnostic: usa un endpoint configurato esclusivamente nell'environment
privato e pubblica alla console solo un file JSON sanitizzato, senza
credenziali, prompt, output o comandi di controllo.

Euristica "Attende feedback" troppo stretta (richiede `?` letterale): non
prioritaria, da riprendere — vedi `docs/backlog.md`.

Ordine corrente: operatività M4 restante → euristica attenzione.

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
- [~] Stato read-only dei task dell'orchestratore: provider, stato,
  pausa per capacità, prossimo tentativo, fallback e avanzamento del
  checkpoint. Implementato come collector host-side sanitizzato; resta da
  validare con un endpoint configurato nel deployment, senza credenziali,
  prompt o comandi di controllo nella console.
- [x] Chat blocks opzionali per Codex/Claude con ritorno immediato alla vista
  terminale, validati sull'istanza pubblicata.
- [x] Euristiche di attenzione Codex/Claude con stati attivo, inattivo,
  feedback, autorizzazione e sconosciuto, validate sull'istanza pubblicata.
- [x] Badge separato per il livello permessi delle sessioni agentiche, con
  collector strutturato host-side, fallback euristico e legenda completa,
  validato sull'istanza pubblicata.
- [x] Percentuale della finestra di contesto per sessione Codex/Claude tramite
  metadati strutturati sanitizzati, validata sull'istanza pubblicata.
- [x] Notifiche PWA locali: prima versione (M3) con trigger client-side
  gated da permesso/preferenza e limitato alla lista sessioni montata,
  poi sostituita dal poller backend di Web Push (M4) che rileva le
  transizioni indipendentemente dalla vista aperta — vedi M4.
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

- [x] Web Push: notifiche anche ad app completamente chiusa. Un task
  backend sempre attivo (indipendente da quale vista ha il frontend aperta —
  a differenza delle notifiche locali M3, che giravano solo con la lista
  sessioni montata) rileva le transizioni verso "attende feedback"/"attende
  autorizzazione" e invia una push reale (VAPID, chiave privata `0600`
  persistita lato server) a tutte le subscription registrate (tabella
  `push_subscriptions`, richiede il database come allegati/archivi/audit).
  Le notifiche locali client-side di M3 sono state rimosse: erano ridondanti
  e meno capaci (scattavano solo con la lista sessioni montata e la tab
  nascosta); il pulsante "Notifiche: on/off" ora gestisce direttamente la
  sottoscrizione push.
- [x] Cronologia Claude opzionale con collector minimizzato, feature flag,
  fallback live e rollback isolato, validata sull'istanza pubblicata.
- [x] Ricerca testuale nella lista sessioni: campo di filtro client-side su
  nome, comando corrente, provider e stato agente (icona/etichetta), nessuna
  chiamata di rete aggiuntiva. Tag ed etichette libere e template di
  creazione sessione restano da fare, non ancora richiesti.
- [x] Correzioni rendering sessioni Claude (Blocchi/Terminale/Cronologia),
  tre cause distinte:
  1. il pane tmux condiviso (stesso in Blocchi, Terminale e via `ssh`+`tmux
     attach`) veniva ristretto dinamicamente in base al viewport
     dell'ultimo client (spesso mobile, poche decine di colonne), wrappando
     contenuto tabellare su molte righe fisiche e consumando in fretta lo
     scrollback condiviso (`history-limit`). Blocchi (testo semplice, si
     reimpagina via CSS) ora richiede sempre almeno `MIN_PANE_COLUMNS`
     (120) colonne nel proprio resize client-side. Terminale (xterm.js con
     cursore ANSI posizionato) inizialmente forzava lo stesso minimo sul
     buffer scrollando in orizzontale, ma l'esperimento è stato revertito:
     la scrollbar verticale interna di xterm.js resta ancorata al bordo
     del buffer largo, non del riquadro visibile, e si disallinea
     scorrendo in orizzontale — oltre a introdurre problemi di geometria
     nel load-more (punto 4). Terminale è tornato ad adattarsi alla
     larghezza reale dello schermo, come da comportamento originale.
  2. bug di scroll touch su mobile: `body` usava `min-height: 100vh`
     (calcolato a barra indirizzi nascosta) mentre `.console` usa `100dvh`
     (altezza visibile reale) — il mismatch lasciava il documento più alto
     del viewport, rendendo l'intera pagina scrollabile e catturando il
     gesto touch al posto del contenitore interno. Allineato `body` a
     `100dvh` con `overscroll-behavior-y: none`, più `touch-action: pan-y`
     e `overscroll-behavior: contain` sui contenitori di output interni.
  3. la vista Cronologia (ADR 007) esclude ogni I/O di tool per non far
     trapelare contenuto di file/comandi — ma questo la lasciava
     completamente silenziosa durante l'esecuzione di tool o davanti al
     prompt nativo di conferma, dando l'impressione di essersi fermata
     proprio dove serve più continuità. Il normalizzatore ora emette un
     indicatore di attività col solo nome del tool (mai il suo
     input/output), marcato "in attesa" quando è l'ultima voce senza
     testo successivo — resta dentro il confine ADR 007, vedi il relativo
     addendum.
  4. la vista Terminale è (per design) uno snapshot delle ultime `lines`
     righe del pane a partire da adesso, non una connessione persistente
     allo scrollback — scrollare indietro in xterm.js non recupera righe
     più vecchie di quelle già scaricate. Aggiunto un "load more"
     all'indietro (come lo storico dell'app Claude): il WebSocket accetta
     ora un parametro `lines` (100-2000, vedi
     `docs/websocket-protocol.md`); quando l'utente scrolla in cima al
     buffer caricato, il frontend aumenta la profondità richiesta e
     riconnette, mostrando uno spinner ("Carico righe precedenti…") e
     ripristinando la posizione di scroll dopo il redraw — resta
     un'unica cattura autorevole (`capture-pane -S -{lines}` più ampio),
     nessun merge lato client. **Limite non risolvibile**: per Claude
     Code (schermo alternativo di tmux) `history_size` resta a 0 finché
     l'agente lavora, quindi non c'è nulla da caricare — la sua vera
     cronologia interna esiste solo nel TUI stesso (visibile con `tmux
     attach`), mai in `capture-pane`; per queste sessioni lo strumento
     giusto per rileggere lo storico resta Cronologia (legge la
     trascrizione di Claude direttamente, non `capture-pane`).
  5. lo scroll touch verticale in Terminale, anche dopo aver corretto
     l'hijack di pagina (punto 2), restava "a scatti": xterm.js ridisegna
     solo per righe intere (`Math.round(scrollTop / cellHeight)`, vedi
     `_handleScroll` nel suo sorgente) — limite architetturale di
     qualunque terminale a griglia di caratteri, non risolvibile con
     CSS/rendering (provati e scartati: `smoothScrollDuration`,
     `-webkit-overflow-scrolling`, renderer WebGL). Per rileggere
     comodamente lo storico su mobile restano Blocchi/Cronologia (div
     scrollabili nativi, senza questa quantizzazione); Terminale resta
     utile per la resa ANSI dal vivo e come unica vista per le sessioni
     shell semplici (Blocchi/Cronologia sono condizionati a sessioni
     Codex/Claude).
  6. xterm.js + addon-fit + addon-webgl (~113 KB gzip) sono ora caricati
     con `import()` dinamico solo all'apertura effettiva di Terminale,
     non nel bundle iniziale — chi resta su Blocchi/Cronologia scarica il
     60% di JS in meno all'avvio (76 KB contro 189 KB gzip). Nessuna
     funzionalità rimossa: Terminale resta disponibile ovunque, incluse
     le sessioni shell semplici dove è l'unica vista.
- [x] Supporto multi-pane esteso: chiusura di un singolo pane (`kill-pane`,
  con conferma esplicita), che lascia sessione e altri pane attivi — rifiuta
  se è l'unico pane rimasto (va terminata la sessione). Scelta tra split
  orizzontale (side-by-side) e verticale (sopra/sotto), invece del solo
  orizzontale fisso di prima; l'effetto è visibile lato tmux (es. `tmux
  attach`), non nella vista MAC che mostra un pane alla volta. Selezione e
  resize di base restano quelli di M1. Una vista con più pane visibili
  contemporaneamente in MAC (al posto del selettore a tendina) è stata
  valutata e scartata deliberatamente: l'app è mobile-first e uno split
  reale sarebbe scomodo su schermi stretti; il selettore resta la
  soluzione adottata.
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
- [x] Riepiloghi opzionali: estratto euristico (nessuna chiamata esterna, nessun
  costo/latenza aggiuntivi) delle ultime righe di testo semplice del pane,
  esposto in `GET /api/v1/agent-statuses` (`summary`, max 140 caratteri) e
  mostrato nella lista sessioni sotto nome/comando, incluso nella ricerca
  testuale. Filtra prompt, marcatori di tool/attività, barre di stato
  ("Sonnet 5 | ~/percorso | main | ...", "gpt-5.6-terra medium · ~/percorso ·
  ...") e suggerimenti tastiera noti — verificato su output reali di Claude
  Code e Codex. Resta un'euristica su testo grezzo, non una sintesi
  comprensiva: può includere frammenti non descrittivi (es. comandi digitati
  dall'utente in una sessione shell).
- [x] Console: menu di cambio rapido sessione (chiuso di default, icona ☰
  nell'header) con elenco sessioni, stato/permessi agentici e passaggio
  diretto senza tornare alla lista — poll condiviso con la barra info sotto,
  attivo solo mentre il menu è aperto o la sessione è agentica. Barra info
  agente (solo sessioni Codex/Claude) con stato corrente, contesto usato e
  quote del provider di questa sessione, sempre visibile in Console (prima
  disponibili solo nella lista sessioni). Il passaggio tra sessioni
  rimonta il componente Console (`key={session.id}`); gli allegati non inviati
  vengono eliminati al cambio, mentre la bozza testuale resta in memoria React
  separata per id sessione e viene ripristinata tornando alla stessa console.
- [~] Storico del consumo di budget e attribuzione per sessione (ADR 010,
  `docs/contracts/budget-history-v1.md`): a differenza dello snapshot quote
  già in dashboard, la serie storica conserva i campioni nel tempo invece di
  mostrarne uno solo. Fase A (quota globale): il collector timer scrive anche
  `provider-rate-limits-history.jsonl` con deduplica e ritenzione 14 giorni,
  esposto da `GET /api/v1/provider-rate-limits/history`; un aggiornamento
  forzato on-demand (`POST /api/v1/provider-rate-limits/refresh`, admin-only,
  opt-in, rate limit dedicato) resta l'unica azione che interroga il
  provider. Implementata e testata, non ancora deployata sull'istanza
  pubblicata. Fase B (attribuzione per sessione): collector che scopre i
  transcript per tempo di modifica invece che per pane tmux, rende osservabile
  anche il consumo headless, arrotola i subagent sotto la sessione madre e
  distingue `origin: mac`/`headless`; espone `GET /api/v1/session-usage`. In
  corso. Il drill-down sul contenuto dei turni resta esplicitamente fuori
  scope, rimandato a una fase C separata.

## M5 — Espansioni

- [ ] Multi-host con daemon su Tailscale.
- [ ] App Android riusando i contratti TypeScript.
- [ ] Orchestrazione agentica, solo dopo la stabilizzazione del core.
