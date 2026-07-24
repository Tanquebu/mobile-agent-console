# ADR 003: PWA prima dell'app nativa

Stato: accettata.

## Decisione

Realizzare prima React PWA responsive con API e protocollo realtime versionati.
Il futuro client Android riuserà contratti e, dove possibile, logica
TypeScript, senza dipendere dai componenti web.

## Conseguenze

Consegna e aggiornamenti sono rapidi e l'accesso Tailscale resta semplice.
Notifiche/background hanno limiti di piattaforma; l'app nativa viene rimandata
finché i flussi operativi non sono stabili.

