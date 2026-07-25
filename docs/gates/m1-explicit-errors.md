# M1 — Stati di errore espliciti

## Copertura

- errori HTTP tipizzati nel client;
- messaggi dedicati per autenticazione, sessione assente, conflitto di nome e
  backend/tmux non disponibile;
- distinzione WebSocket tra disconnessione temporanea e sessione chiusa;
- arresto dei tentativi di riconnessione e controlli disabilitati quando la
  sessione non esiste più;
- messaggio backend specifico per nomi tmux duplicati.

## Evidenza

Verifica del 25 luglio 2026:

- 53 test backend passati;
- build frontend completata;
- deploy mirato di `backend` e `web`, senza ricreare `tmux-runtime`;
- health pubblica con applicazione e tmux operativi;
- test manuale confermato per conflitto di nome e sessione chiusa.
