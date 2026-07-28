# Overview del progetto

## Stato

Mobile Agent Console è una PWA mobile-first operativa e pubblicata per
monitorare e controllare sessioni tmux persistenti. Il core resta
agent-agnostic: shell, REPL e CLI generiche usano lo stesso flusso terminale;
Codex e Claude aggiungono adapter opzionali per stato, permessi, quote,
contesto e cronologia.

M0 e M2 sono conclusi. Il runtime M1 include ora resa ANSI reale tramite
terminal mode xterm.js; lo scrollback delle app a schermo alternato resta un
limite noto di `tmux capture-pane`, non risolvibile lato rendering — per
Claude Code (sempre a schermo alternato mentre lavora) lo strumento giusto
per rileggere lo storico resta Cronologia, non Terminale. M3 è in gran parte
rilasciato. M4 è concluso.

## Capacità disponibili

- gestione mobile e desktop di sessioni e pane tmux, con output live, input,
  tasti, resize, split orizzontale/verticale, chiusura del singolo pane,
  rinomina e terminazione confermata;
- ricerca testuale nella lista sessioni (nome, comando corrente, provider e
  stato agente), filtro client-side senza chiamate di rete aggiuntive;
- modalità tmux Docker isolata oppure host sul socket predefinito;
- account persistenti, ruoli, CSRF, cookie sicuri, audit e rate limiting;
- snapshot di riavvio, archivio con resume, backup verificabili e restore
  offline;
- browser delle directory consentite, anteprima UTF-8, download e allegati ai
  prompt, con metadati persistiti in database (come utenti/archivi/audit),
  anteprima immagine, quota aggregata per sessione, deduplica per contenuto e
  pulizia alla terminazione/archiviazione della sessione;
- dashboard agentica con stato, permessi, consumo contesto, quote provider e
  riepilogo euristico di sessione (estratto di testo semplice, nessuna
  chiamata esterna), mostrato in lista e incluso nella ricerca;
- viste Terminale (xterm.js con addon caricati solo all'apertura, resa ANSI
  reale, sola visualizzazione, "load more" sullo scrollback tmux) e Blocchi
  (larghezza minima garantita per la leggibilità), più Cronologia Claude
  opzionale e isolata con indicatore di attività (solo nome tool) durante i
  tratti senza testo; scroll touch corretto su mobile;
- service worker per shell offline best-effort e banner di connessione
  assente;
- notifiche Web Push opzionali (richiede un contesto sicuro, vedi ADR 008):
  un task backend sempre attivo rileva quando una sessione attende feedback
  o autorizzazione, indipendentemente dalla vista aperta nel frontend, e
  avvisa anche ad app completamente chiusa;
- TLS in nginx con certificato Tailscale reale sullo stesso bind diretto
  sull'IP Tailscale, rinnovo automatico via user timer;
- pannello Preferenze con vista predefinita (Blocchi/Terminale) per le
  sessioni Codex/Claude, persistita lato client;
- deploy systemd/Compose che ricrea solo web e backend e preserva tmux.

## Invarianti operative

- tmux è autorevole per sessioni vive e output recente;
- web e backend sono stateless e sostituibili;
- un deploy ordinario non ricrea mai `tmux-runtime`;
- uno step funzionale è concluso solo dopo test automatici, deploy mirato e
  validazione sull'istanza pubblicata;
- gli adapter provider-specifici devono fallire senza degradare il terminale
  generico;
- “What's new” descrive soltanto l'ultimo round significativo rilasciato.

## Prossimo percorso consigliato

M4 è concluso. Eventuali tag/etichette sessione e template di creazione
restano da definire se e quando servissero; nessun altro item M4 aperto.

Lo stato read-only dei task dell'orchestratore è un adapter opzionale:
l'endpoint esterno e le credenziali sono configurati esclusivamente
nell'environment privato, mentre la console riceve soltanto un file JSON
sanitizzato.

Multi-host, app Android e orchestrazione agentica mutativa restano M5 e non
devono anticipare la stabilizzazione del core.

## Riferimenti

- [Roadmap tecnica](roadmap.md)
- [Architettura](architecture.md)
- [Sicurezza e threat model](security.md)
- [Contratto API](api-contract.md)
- [Backlog e limiti noti](backlog.md)
- [Decisioni architetturali](adr/)
