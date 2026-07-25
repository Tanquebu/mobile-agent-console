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

## Vertical slice attuale

Il primo incremento restringe intenzionalmente l'MVP:

- elenca sessioni sul socket configurato;
- crea una nuova sessione shell dall’app;
- elenca e apre una sessione;
- cattura e aggiorna l'output;
- invia testo senza implicitamente premere Enter;
- invia Enter come comando distinto;
- usa login runtime, cookie HttpOnly e CSRF same-origin;
- sopravvive a refresh e disconnessioni.

Rinomina e termina sessioni tramite azioni dedicate. Creazione e rinomina
accettano nomi ASCII con lettere, numeri, `_`, `-` e spazi singoli tra le
parole; la directory resta dentro l’allowlist e il profilo server-side è
soltanto `shell`.

Gli snapshot di riavvio persistono nome, directory e modalità sicura di
rilancio per un insieme selezionato di sessioni. Non sono checkpoint dei
processi: dopo un reboot ricreano shell e, opzionalmente, aprono il selettore
di resume nativo di Codex o Claude.

## Requisiti non funzionali

- bind predefinito localhost, oppure IP Tailscale esplicito con `MAC_BIND_IP`;
- porta host predefinita `8081` per evitare conflitti con altri servizi già presenti sulla 8080;
- `subprocess` con argv e `shell=False`;
- nomi sessione lunghi al massimo 64 caratteri, con parole ASCII separate da
  spazi singoli (`_` e `-` consentiti);
- limite input 64 KiB e output iniziale 500 righe;
- WebSocket autenticato e riconnessione con snapshot idempotente;
- interfaccia usabile a 360 px, input multilinea e target touch >= 44 px;
- test senza dipendere da agenti reali.

## Assunzioni e compromessi

Un solo utente Linux possiede backend e sessioni tmux. Il socket dedicato
isola l'app dalle sessioni tmux personali, ma significa che sessioni sul socket
predefinito non sono visibili. `capture-pane` non ricostruisce perfettamente
applicazioni fullscreen o riscritture ANSI: terminal mode affronterà questi
casi. Il token inserito nella build Vite è accettabile soltanto per sviluppo e
sarà sostituito dal login con cookie HttpOnly prima del deployment.

## Runtime tmux MVP

Il MVP supporterà due modalità configurabili: `docker`, con socket nel runtime
isolato, e `host`, con un socket tmux dedicato dell’host montato nel backend.
La seconda serve a usare direttamente Codex, Claude, Gemini e sessioni create
fuori da Docker; la scelta definitiva è rinviata all’ADR 004.
