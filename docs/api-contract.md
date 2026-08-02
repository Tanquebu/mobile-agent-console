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
Il nome viene normalizzato NFC, ha al massimo 64 caratteri e accetta lettere e
numeri Unicode, `_`, `-` e spazi singoli tra le parole; la directory deve essere
sotto una root configurata. I profili ammessi sono `shell`, `codex` e `claude`;
il server li risolve in argv costanti e il client non invia un comando
eseguibile.

## Archivio sessioni

- `GET /api/v1/archives`: elenca i metadati archiviati.
- `POST /api/v1/sessions/{id}/archive`: con `{"confirmed":true}` salva nome,
  directory, profilo, autore e data, quindi termina la sessione tmux.
- `POST /api/v1/archives/{id}/restore`: con `{"confirmed":true}` ricrea la
  sessione tramite il profilo server-side; per Codex e Claude apre il selettore
  nativo di resume e rimuove la voce dopo il successo.
- `DELETE /api/v1/archives/{id}`: con `{"confirmed":true}` elimina
  definitivamente i soli metadati.

Le mutazioni richiedono ruolo `operator` o `admin`. Nessun output, prompt,
environment, segreto o allegato entra nell'archivio.

## `GET /api/v1/audit`

Richiede ruolo `admin`. Restituisce gli eventi più recenti in ordine inverso;
`limit` è compreso tra 1 e 500 e vale 200 per default. Ogni evento contiene
`id`, `actor`, `action`, `target`, `outcome` e `created_at`. L'audit non
conserva body, query string, IP, prompt, output, filename o segreti.

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

## Snapshot di riavvio

`GET /api/v1/snapshots` elenca gli snapshot persistenti autenticati.

`POST /api/v1/snapshots` richiede CSRF e accetta soltanto id numerici e modalità
tipizzate; nomi e directory sono letti dal server tmux:

```json
{
  "name": "Prima del riavvio",
  "sessions": [
    {"session_id": "3", "mode": "codex"},
    {"session_id": "4", "mode": "manual"}
  ]
}
```

Le modalità sono `shell`, `codex`, `claude` e `manual`. Lo snapshot risultante
contiene nome, directory, comando osservato e data, ma non output, environment,
PID o comandi client.

`POST /api/v1/snapshots/{snapshot_id}/restore` con
`{"confirmed":true}` ricrea le sessioni mancanti. I conflitti di nome vengono
saltati. `codex` invia il comando costante `codex resume`; `claude` invia
`claude --resume`, aprendo il picker nativo nella directory ripristinata. La
risposta riporta per ogni sessione `restored`, `skipped`, `manual` o `error`.

`DELETE /api/v1/snapshots/{snapshot_id}` con `{"confirmed":true}` elimina lo
snapshot. Tutte le mutazioni richiedono CSRF.

Login e mutazioni sono soggetti a finestre di rate limit configurabili. Quando
il limite è superato l'API risponde `429` e include l'header `Retry-After`.

`POST /api/v1/auth/login` accetta `{"username":"admin","password":"..."}`.
L'username predefinito resta `admin` per compatibilità con i deployment
single-user; la password è verificata contro l'hash Argon2id persistente.

`GET /api/v1/users`, `POST /api/v1/users` e
`POST /api/v1/users/{username}/status` sono riservati agli amministratori.
I ruoli sono `admin`, `operator` e `viewer`; la password di un nuovo account
deve contenere almeno 16 caratteri. La disattivazione rende immediatamente
invalide anche le sessioni firmate già emesse.

## `GET /api/v1/sessions/{id}/output?lines=500`

`lines` è 1..2000. Risposta:

```json
{"session_id":"1","content":"...", "captured_at":"2026-07-24T10:00:00Z"}
```

`GET /api/v1/sessions/{id}/panes` elenca i pane della sessione con id numerico,
coordinate finestra/pane, stato attivo, comando, titolo e dimensioni.
`pane_id` può essere passato a output e WebSocket e nei body di input/tasti.
Il backend verifica sempre l'appartenenza alla sessione.

`GET /api/v1/agent-statuses` include `context_used_percent` (`0..100` oppure
`null`) accanto allo stato operativo e alla modalità permessi. Il valore deriva
da metadati provider sanitizzati e non espone conteggi, modelli o transcript.
Include anche `summary` (stringa o `null`): estratto euristico delle ultime
righe di testo semplice del pane (max 140 caratteri), filtrando prompt,
marcatori di tool/attività, barre di stato e suggerimenti tastiera noti. È
un'euristica su testo grezzo, non una sintesi comprensiva del contenuto — può
includere frammenti non descrittivi (es. comandi digitati dall'utente) e non
richiede mai l'opt-in ANSI.

`GET /api/v1/sessions/{id}/claude-history` è disponibile soltanto con
`MAC_CLAUDE_HISTORY_ENABLED=true`, per una sessione tmux viva il cui comando
corrente è Claude e con un file collector recente. Restituisce:

```json
{
  "session_id": "43",
  "collected_at": "2026-07-27T10:00:00Z",
  "source_updated_at": "2026-07-27T09:59:59Z",
  "truncated": false,
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "testo",
      "timestamp": "2026-07-27T09:59:00Z"
    }
  ]
}
```

Con flag spento, file assente/stale/malformato, sessione non-Claude o id non
valido risponde `404`. L'endpoint non cambia output o WebSocket.

`POST /api/v1/sessions/{id}/panes/{pane_id}/resize` accetta
`{"columns":100,"rows":30}` con limiti rispettivamente `20..500` e `5..300`.
`POST /api/v1/sessions/{id}/panes/split?pane_id=N&direction=horizontal`
crea un nuovo pane con il profilo shell costante `bash -l`; non accetta
comandi dal client e restituisce il pane creato. `direction` è
`horizontal` (default, side-by-side) o `vertical` (sopra/sotto).
`DELETE /api/v1/sessions/{id}/panes/{pane_id}` richiede
`{"confirmed":true}` e chiude il singolo pane (`kill-pane`), lasciando la
sessione e gli altri pane attivi; rifiuta con `400` se è l'unico pane della
sessione (va terminata la sessione stessa) e con `404` se il pane non
appartiene alla sessione. Risposta `204`.

## `WS /api/v1/ws/sessions/{id}`

La connessione riceve inizialmente uno `snapshot` completo con `sequence_id`.
Le modifiche successive sono messaggi `delta` per righe con
`base_sequence_id`, `sequence_id`, `start`, `delete_count` e `lines`. Il client
applica un delta soltanto se la sua sequenza corrente coincide con la base;
altrimenti riconnette per ottenere un nuovo snapshot autorevole.

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

## `GET /api/v1/sessions/{id}/file/download?path=...`

Scarica come allegato un file entro `MAC_ALLOWED_ROOTS`. Richiede il cookie di
sessione, valida l'id tmux numerico e risolve il path lato server. Sono
consentiti immagini (`bmp`, `gif`, `jpg/jpeg`, `png`, `tif/tiff`, `webp`), PDF
e documenti Word (`doc`, `docx`). Il file viene trasmesso in streaming con
`Content-Disposition: attachment`.

## `POST /api/v1/sessions/{id}/input`

Body `{"text":"...multiline...","attachment_ids":[]}`; massimo 65536
caratteri e massimo 5 allegati già caricati nella stessa sessione. Il backend
aggiunge al testo i path controllati degli allegati, incolla il risultato e
non invia Enter. Risposta `202 {"accepted":true}`.

## `POST /api/v1/sessions/{id}/attachments?filename=...`

Richiede autenticazione, CSRF e il database dei metadati (`503` se
`MAC_DATABASE_AUTH_ENABLED` è spento, come per archivi/audit). Il body è il
contenuto binario del singolo file e `Content-Type` deve essere uno dei tipi
consentiti: PNG, JPEG, WebP, PDF, testo UTF-8, Markdown, CSV, JSON o XML. La
dimensione massima predefinita è 10 MiB (`MAC_MAX_ATTACHMENT_BYTES`); la
somma degli allegati della sessione non può superare
`MAC_MAX_ATTACHMENT_BYTES_PER_SESSION` (100 MiB per default). Se il contenuto
(hash SHA-256) coincide con un allegato già presente nella stessa sessione,
il file fisico viene riusato invece di riscritto (righe di metadati distinte,
stesso file su disco).

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

## `GET /api/v1/sessions/{id}/attachments/{attachment_id}/preview`

Richiede autenticazione (qualsiasi ruolo). Restituisce una thumbnail JPEG
best-effort (max 256×256) generata al momento dell'upload per gli allegati
immagine; `404` per allegati non immagine o se la generazione è fallita.

## `DELETE /api/v1/sessions/{id}/attachments/{attachment_id}`

Richiede autenticazione e CSRF. Elimina immediatamente metadati e, se nessun
altro allegato della sessione referenzia lo stesso contenuto (deduplica),
anche il file fisico. Risposta `204`. Gli allegati non eliminati
esplicitamente scadono automaticamente dopo `MAC_ATTACHMENT_TTL_SECONDS` (24
ore per default), oppure prima se la sessione viene terminata o archiviata:
l'id numerico liberato può essere riassegnato da tmux a una sessione futura
scollegata, quindi gli allegati non sopravvivono alla sessione che li ha
caricati.

## `POST /api/v1/sessions/{id}/keys`

Body `{"key":"Enter","confirmed":false}`. Sono consentiti `Enter`, `Up`,
`Down`, `Escape` e `C-c`; l'interrupt `C-c` richiede obbligatoriamente
`"confirmed":true`. Risposta 202.

## `POST /api/v1/sessions/{id}/rename`

Rinomina la sessione identificata dal suo id numerico. Richiede autenticazione
e CSRF. Body `{"name":"Refactoring Codex"}` con gli stessi vincoli applicati
alla creazione. Il nome viene passato a tmux come argomento argv separato e non
viene mai usato come target. Risposta `200 {"accepted":true}`.

## `DELETE /api/v1/sessions/{id}`

Termina definitivamente la sessione tmux. Richiede autenticazione, CSRF e
body `{"confirmed":true}`; senza conferma esplicita risponde 400. Risposta
`204`.

## `GET /api/v1/push/public-key`

Richiede autenticazione (qualsiasi ruolo) e il database dei metadati (`503`
se `MAC_DATABASE_AUTH_ENABLED` è spento). Restituisce
`{"public_key":"..."}`, la chiave pubblica VAPID in formato raw base64url,
da passare come `applicationServerKey` a `PushManager.subscribe()`.

## `POST /api/v1/push/subscriptions`

Richiede autenticazione e CSRF. Body `{"endpoint":"...","keys":{"p256dh":
"...","auth":"..."}}` (lo stesso oggetto restituito da
`PushSubscription.toJSON()`). Ri-sottoscrivere lo stesso `endpoint`
aggiorna le chiavi invece di duplicare la riga. Risposta `204`.

## `DELETE /api/v1/push/subscriptions`

Richiede autenticazione e CSRF. Body `{"endpoint":"..."}`. Rimuove la
subscription; nessun errore se non esisteva. Risposta `204`. Le subscription
vengono rimosse automaticamente anche quando il push service esterno segnala
che non sono più valide (404/410 alla consegna).

Un task backend sempre attivo (indipendente da quale vista ha il frontend
aperta) rileva le transizioni verso "attende feedback"/"attende
autorizzazione" e invia una push a tutte le subscription registrate; il
payload contiene solo titolo/corpo/tag generico, mai output o prompt
(coerente con l'invariante delle notifiche, `docs/security.md`).

Errori: `400` validazione dominio (incluso id non numerico), `401`
autenticazione, `404` sessione, `409` creazione impossibile (es. server
tmux host non attivo), `422` schema, `503` tmux non disponibile o database
dei metadati assente.
