# Requisiti

## Obiettivo e confine

Mobile Agent Console offre una chat operativa mobile-first sopra processi
interattivi persistenti in tmux. tmux è il runtime e la fonte primaria
dell'output recente; il browser e il backend sono sostituibili senza perdere la
sessione.

Il core deve funzionare con shell, REPL e CLI arbitrarie avviate da profili
consentiti. Le integrazioni specifiche sono adapter opzionali.

## MVP

L'MVP comprende login, elenco, creazione da profilo, lettura/stream, testo
multilinea, tasti separati, interrupt/terminazione, PWA, allowlist, audit,
systemd e accesso Tailscale. Non comprende multi-tenancy, multi-host,
orchestrazione agentica o API vendor.

## Prodotto attuale

L'applicazione pubblicata comprende:

- elenco, creazione, rinomina, archivio, ripristino e terminazione delle
  sessioni;
- selezione, split e resize dei pane;
- output WebSocket, input multilinea, Enter e tasti come operazioni separate;
- browser delle directory consentite, preview, download e allegati;
- account persistenti con ruoli, audit, snapshot e backup;
- dashboard Codex/Claude con stato, permessi, quote e consumo del contesto;
- viste Terminale e Blocchi, con Cronologia Claude opzionale;
- modalità tmux Docker o host e avvio/deploy tramite user unit systemd.

Creazione e rinomina accettano nomi normalizzati NFC con lettere e numeri
Unicode, `_`, `-` e spazi singoli tra le parole. Directory e file restano entro
l'allowlist; i profili eseguibili sono risolti server-side e il nome non viene
mai usato come target tmux.

Gli snapshot non sono checkpoint dei processi: dopo un reboot ricreano shell
e possono aprire il selettore di resume nativo di Codex o Claude. La
cronologia Claude è un adapter read-only separato e non sostituisce lo stream
tmux.

## Requisiti non funzionali

- bind predefinito localhost, oppure IP Tailscale esplicito con `MAC_BIND_IP`;
- porta host predefinita `8081` per evitare conflitti con altri servizi già presenti sulla 8080;
- `subprocess` con argv e `shell=False`;
- nomi sessione NFC lunghi al massimo 64 caratteri, con parole Unicode di
  lettere/numeri separate da spazi singoli (`_` e `-` consentiti);
- limite input 64 KiB e snapshot WebSocket autorevoli;
- WebSocket autenticato e riconnessione con snapshot idempotente;
- interfaccia usabile a 360 px, input multilinea e target touch >= 44 px;
- test senza dipendere da agenti reali.

## Assunzioni e compromessi

Un solo utente Linux possiede backend e sessioni tmux. La modalità Docker usa
un runtime isolato; la modalità host collega deliberatamente il backend al
socket tmux predefinito dell'utente e amplia quindi il suo confine di fiducia.
`capture-pane` non ricostruisce perfettamente applicazioni fullscreen o
riscritture ANSI: il futuro terminal mode affronterà questi casi. Gli adapter
provider-specifici sono opt-in e devono lasciare intatto il fallback tmux.

## Runtime tmux MVP

Il prodotto supporta due modalità configurabili: `docker`, con socket nel
runtime isolato, e `host`, con il socket tmux predefinito dell'utente montato
nel backend. La modalità host usa direttamente CLI, alias e sessioni esistenti;
la decisione corrente è formalizzata in ADR 005, che supera ADR 004.
