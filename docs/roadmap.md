# Roadmap tecnica

## M0 — Fondazioni e vertical slice

Documenti, servizio tmux isolato, API list/create/capture/input/Enter, WebSocket
snapshot, UI mobile e fake test. Gate: flusso manuale completo affidabile.

## M1 — Hardening del runtime

Delta robusti, ANSI, pane selection, resize, error state, rate limit, Origin
policy formalizzata e test di integrazione con tmux reale. La modalità
host-tmux è già realizzata sul socket di default dell'utente (ADR 005, che
supera il socket dedicato previsto qui in origine). Estensione della
whitelist di `send_key` per rispondere ai prompt di autorizzazione degli
agenti da mobile: `Up`/`Down`/`Esc` e, dietro conferma esplicita, `C-c`
(interrupt); terminazione della sessione come endpoint separato.

## M2 — MVP sicuro e persistente

SQLite/SQLAlchemy, login Argon2, cookie HttpOnly/SameSite, CSRF, ruoli,
allowlist directory, profili, create/rename/archive, audit metadata, systemd e
backup. Gate: deployment Tailscale senza porta pubblica.

## M3 — Esperienza MVP

Chat blocks, euristiche attenzione configurabili, notifiche PWA locali,
manifest/service worker completi, preferenze, terminal mode xterm.js e tasti
speciali.

Integrazione con sistemi esterni di monitoraggio degli agenti: un daemon
che osservi i pane sullo stesso server tmux host e ne classifichi lo stato
(es. `active`/`idle`/`stalled`/`waiting_input`) può alimentare, via API di
stato locale, badge di attenzione sulla lista sessioni e il caso "l'agente
attende un'autorizzazione", senza duplicare il monitoraggio nella console;
un canale di notifica esterno può coprire l'avviso remoto finché le
notifiche PWA non sono pronte. Da formalizzare: contratto di stato
condiviso e mappatura pane ↔ session id.

## M4 — Operatività

Web Push, cronologia opzionale, ricerca/tag/template, più pane, upload
controllato e riepiloghi opzionali.

## M5 — Espansioni

Prima multi-host con daemon su Tailscale, poi app Android riusando contratti
TypeScript; orchestrazione agentica solo dopo stabilizzazione del core.
