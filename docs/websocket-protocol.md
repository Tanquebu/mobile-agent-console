# Protocollo WebSocket v1

Endpoint:

```text
GET /api/v1/ws/sessions/{id}
```

Il cookie HttpOnly same-origin autentica la connessione. Nessun segreto compare
nell'URL; l'endpoint verifica anche l'Origin configurato.
Quando si usa Docker con bind Tailscale, Nginx inoltra `Host` comprensivo della
porta pubblicata (`100.x.x.x:8081`), necessario per il controllo same-origin.

Query string opzionale: `pane_id` (pattern `^\d{1,10}$`, pane targetato invece
di quello attivo), `ansi` (`true` per includere le sequenze di escape via
`capture-pane -e`, usato dalla vista Terminale/xterm.js), `lines` (100-2000,
default 500 — profondità della cattura `capture-pane -S -{lines}`; la vista
Terminale la aumenta e riconnette quando l'utente scrolla in cima al buffer
già caricato, per un "load more" all'indietro — lo snapshot più grande resta
l'unica fonte autorevole, nessun merge lato client).

Messaggi server JSON:

```json
{"type":"snapshot","session_id":"1","sequence_id":1,"timestamp":"...","content":"..."}
{"type":"heartbeat","session_id":"1","sequence_id":2,"timestamp":"..."}
{"type":"session_closed","session_id":"1","sequence_id":3,"timestamp":"..."}
{"type":"error","code":"tmux_unavailable","message":"..."}
```

`sequence_id` è monotono nella singola connessione, non globale. Lo snapshot
iniziale e quello successivo a una riconnessione sono autorevoli. Il client
ignora sequence non crescenti, mostra lo stato connessione e usa backoff
esponenziale con jitter (1–15 secondi).

Nessun input è accettato sul WebSocket nello slice: le mutazioni usano HTTP,
semplificando autorizzazione, limiti e audit. Il polling parte a 500 ms, passa
a 1 s dopo 10 cicli invariati e a 2 s dopo 30.
