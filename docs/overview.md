# Overview del progetto

## Stato

Mobile Agent Console è una PWA mobile-first operativa e pubblicata per
monitorare e controllare sessioni tmux persistenti. Il core resta
agent-agnostic: shell, REPL e CLI generiche usano lo stesso flusso terminale;
Codex e Claude aggiungono adapter opzionali per stato, permessi, quote,
contesto e cronologia.

M0 e M2 sono conclusi. Il runtime M1 include ora resa ANSI reale tramite
terminal mode xterm.js; lo scrollback delle app a schermo alternato resta un
limite noto di `tmux capture-pane`, non risolvibile lato rendering. M3 è in
gran parte rilasciato; una parte di M4 è stata anticipata per risolvere la
cronologia Claude.

## Capacità disponibili

- gestione mobile e desktop di sessioni e pane tmux, con output live, input,
  tasti, resize, split, chiusura del singolo pane, rinomina e terminazione
  confermata;
- modalità tmux Docker isolata oppure host sul socket predefinito;
- account persistenti, ruoli, CSRF, cookie sicuri, audit e rate limiting;
- snapshot di riavvio, archivio con resume, backup verificabili e restore
  offline;
- browser delle directory consentite, anteprima UTF-8, download e allegati ai
  prompt, con metadati persistiti in database (come utenti/archivi/audit),
  anteprima immagine, quota aggregata per sessione, deduplica per contenuto e
  pulizia alla terminazione/archiviazione della sessione;
- dashboard agentica con stato, permessi, consumo contesto e quote provider;
- viste Terminale (xterm.js, resa ANSI reale, sola visualizzazione) e Blocchi,
  più Cronologia Claude opzionale e isolata;
- service worker per shell offline best-effort, banner di connessione assente
  e notifiche locali opzionali quando una sessione attende feedback o
  autorizzazione ad app in background (richiede un contesto sicuro, vedi
  ADR 008);
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

1. operatività M4: Web Push, ricerca/tag/template, supporto multi-pane esteso.

Stato read-only dei task dell'orchestratore locale resta solo in roadmap:
dipende da un sistema esterno privato, intenzionalmente non referenziato in
questo repository pubblico e agent-agnostic; verrà ripreso con un contratto
sanitizzato dedicato solo quando servirà.

Multi-host, app Android e orchestrazione agentica mutativa restano M5 e non
devono anticipare la stabilizzazione del core.

## Riferimenti

- [Roadmap tecnica](roadmap.md)
- [Architettura](architecture.md)
- [Sicurezza e threat model](security.md)
- [Contratto API](api-contract.md)
- [Backlog e limiti noti](backlog.md)
- [Decisioni architetturali](adr/)
