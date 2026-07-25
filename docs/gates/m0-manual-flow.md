# Gate M0 — Flusso manuale completo

## Obiettivo

Dimostrare che il vertical slice è affidabile sull'istanza pubblicata, usando
un browser reale e un server tmux reale. Il gate si chiude soltanto dopo
verifiche automatiche, deploy e completamento della checklist manuale.

## Evidenze automatiche

Esecuzione del 25 luglio 2026 sul commit `3f1821f`:

- [x] `docker compose run --build --rm backend-test`: 49 test passati;
- [x] `docker compose run --build --rm frontend-build`: TypeScript e build
  Vite completati;
- [x] `docker compose config --quiet`;
- [x] istanza pubblicata con `GET /health` → `{"status":"ok","tmux":"ok"}`;
- [x] `web` e `backend` attivi senza ricreare `tmux-runtime`.

I due warning della suite backend non sono bloccanti: deprecazione
Starlette/httpx e cache pytest non scrivibile nel container read-only.

## Checklist manuale

Usare una sessione sacrificabile per le operazioni distruttive.

- [x] Login e ripristino della sessione applicativa dopo refresh.
- [x] Elenco e apertura di una sessione tmux reale.
- [x] Ricezione dell'output tramite WebSocket.
- [x] Creazione dalla dashboard di una sessione chiamata `Gate M0 Test`.
- [x] Invio di testo senza Enter implicito, seguito da Enter separato.
- [x] Riconnessione dopo refresh con sessione tmux ancora attiva.
- [x] Navigazione di una sottodirectory e ritorno tramite parent/root.
- [x] Apertura in sola lettura di un file testuale.
- [x] Rinomina della sessione dalla toolbar della dashboard.
- [x] Verifica della conferma e terminazione della sola sessione
  `Gate M0 Test`.
- [x] Verifica che le altre sessioni tmux restino attive.

## Esito

**Superato il 25 luglio 2026.** Tutti i punti manuali sono stati confermati
sull'istanza pubblicata basata sul commit `3f1821f`; le sessioni operative
preesistenti sono rimaste attive.
