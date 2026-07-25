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

## `GET /api/v1/config`

Richiede il cookie di sessione. Espone la configurazione minima utile al
client: le root consentite per la creazione di sessioni (usate per
precompilare il campo directory) e i preset opzionali di directory
(`MAC_WORKSPACE_PRESETS`, formato `label=path,...` o oggetto JSON) mostrati
come select nel form:

```json
{"allowed_roots":["/workspace"],"workspace_presets":{"pipeline":"/workspace/pipeline"}}
```

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

## `GET /api/v1/sessions/{id}/directory`

Richiede il cookie di sessione. Elenca il contenuto della working directory
corrente del pane (`#{pane_current_path}` tmux, non la directory di
creazione della sessione), purché ricada ancora sotto una root consentita —
stessa validazione di `POST /sessions`. Utile per popolare comandi come
`cat`/`cd` dal client senza eseguire shell arbitrarie lato client.

```json
{
  "session_id": "1",
  "path": "/workspace/demo",
  "truncated": false,
  "entries": [
    {"name": "src", "type": "dir", "size": null, "created_at": "2026-07-20T09:00:00Z"},
    {"name": "notes.txt", "type": "file", "size": 42, "created_at": "2026-07-24T10:00:00Z"}
  ]
}
```

`type` è `dir`, `file` o `other` (socket, symlink rotto, ecc.); `size` è
`null` per le voci non-file. `created_at` è il birth time del filesystem
quando disponibile, altrimenti il ctime (data dell'ultima modifica dei
metadati) come approssimazione — non garantito su tutti i filesystem. Le
directory con più di 2000 voci vengono troncate (`truncated:true`), elencando
solo le prime 2000 in ordine cartelle-poi-file, alfabetico case-insensitive.

## `POST /api/v1/sessions/{id}/input`

Body `{"text":"...multiline...","attachment_ids":[]}`; massimo 65536
caratteri e massimo 5 allegati già caricati nella stessa sessione. Il backend
aggiunge al testo i path controllati degli allegati, incolla il risultato e
non invia Enter. Risposta `202 {"accepted":true}`.

## `POST /api/v1/sessions/{id}/attachments?filename=...`

Richiede autenticazione e CSRF. Il body è il contenuto binario del singolo
file e `Content-Type` deve essere uno dei tipi consentiti: PNG, JPEG, WebP,
PDF, testo UTF-8, Markdown, CSV, JSON o XML. La dimensione massima predefinita
è 10 MiB (`MAC_MAX_ATTACHMENT_BYTES`).

Risposta:

```json
{
  "id":"0123456789abcdef0123456789abcdef",
  "name":"screenshot.png",
  "media_type":"image/png",
  "size":12345,
  "path":"/workspace/.agent-attachments/1/0123456789abcdef0123456789abcdef.png"
}
```

L'id può essere usato soltanto nella sessione per cui è stato caricato.

## `DELETE /api/v1/sessions/{id}/attachments/{attachment_id}`

Richiede autenticazione e CSRF. Elimina immediatamente contenuto e metadati
dell'allegato, purché appartenga alla sessione indicata. Risposta `204`.
Gli allegati non eliminati esplicitamente scadono automaticamente dopo
`MAC_ATTACHMENT_TTL_SECONDS` (24 ore per default).

## `POST /api/v1/sessions/{id}/keys`

Body `{"key":"Enter","confirmed":false}`. Sono consentiti `Enter`, `Up`,
`Down`, `Escape` e `C-c`; l'interrupt `C-c` richiede obbligatoriamente
`"confirmed":true`. Risposta 202.

## `DELETE /api/v1/sessions/{id}`

Termina definitivamente la sessione tmux. Richiede autenticazione, CSRF e
body `{"confirmed":true}`; senza conferma esplicita risponde 400. Risposta
`204`.

Errori: `400` validazione dominio (incluso id non numerico), `401`
autenticazione, `404` sessione, `409` creazione impossibile (es. server
tmux host non attivo), `422` schema, `503` tmux non disponibile.
