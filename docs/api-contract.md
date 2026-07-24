# Contratto API v1

Base path: `/api/v1`. Tutte le risposte JSON. Le API protette richiedono il
cookie HttpOnly `mac_session`; le mutazioni richiedono `X-CSRF-Token`.

L'`{id}` nei path è il session id tmux in forma numerica (`"3"` per la
sessione tmux `$3`), come restituito da `GET /sessions`. Il `name` è solo
descrittivo: può contenere caratteri arbitrari per le sessioni host
preesistenti e non è un identificatore valido negli URL.

## `POST /api/v1/auth/login`

Body `{"password":"..."}`. Imposta il cookie e restituisce
`{"csrf_token":"..."}`. Il client mantiene il CSRF soltanto in memoria.

## `POST /api/v1/auth/logout`

Richiede cookie e CSRF; elimina il cookie.

## `POST /api/v1/sessions`

Richiede CSRF. Body: `{"name":"demo","directory":"/workspace","profile":"shell"}`.
Il nome deve rispettare `^[A-Za-z0-9_-]{1,64}$`; la directory deve essere sotto
una root configurata. Il client non invia un comando eseguibile.

## `GET /api/v1/auth/session`

Valida il cookie e restituisce un nuovo token CSRF, permettendo refresh e
riapertura della PWA senza conservare segreti in storage JavaScript.

## `GET /health`

Endpoint non autenticato di liveness. Risposta `{"status":"ok"}`; in
modalità host-tmux include anche `"tmux":"ok"` oppure il messaggio d'errore
del server tmux ("no server running...", "protocol version mismatch...").
Non rivela sessioni o altra configurazione.

## `GET /api/v1/sessions`

Risposta `200`:

```json
{"sessions":[{"id":"1","name":"demo","attached":false,"windows":1,"current_command":"python3","activity_at":"2026-07-24T10:00:00Z"}]}
```

## `GET /api/v1/sessions/{id}/output?lines=500`

`lines` è 1..2000. Risposta:

```json
{"session_id":"1","content":"...", "captured_at":"2026-07-24T10:00:00Z"}
```

## `POST /api/v1/sessions/{id}/input`

Body `{"text":"...multiline..."}`; massimo 65536 byte UTF-8. Incolla
esattamente il testo e non invia Enter. Risposta `202 {"accepted":true}`.

## `POST /api/v1/sessions/{id}/keys`

Body `{"key":"Enter"}`. Nello slice è consentito solo `Enter`. Risposta 202.

Errori: `400` validazione dominio (incluso id non numerico), `401`
autenticazione, `404` sessione, `409` creazione impossibile (es. server
tmux host non attivo), `422` schema, `503` tmux non disponibile.
