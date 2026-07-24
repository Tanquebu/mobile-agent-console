# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cos'è

Mobile Agent Console (PWA) — un'app mobile-first per controllare processi
interattivi persistenti in esecuzione in sessioni tmux. Il core tratta ogni
sessione come un terminale generico e non dipende da Codex né da alcun agente
specifico (vedi `docs/adr/002-agent-agnostic-core.md`).

La documentazione di progetto (in italiano) vive in `docs/`: `architecture.md`,
`security.md`, `api-contract.md`, `websocket-protocol.md`, `requirements.md`,
`roadmap.md`, e le ADR sotto `docs/adr/`. Leggere `docs/architecture.md` e
`docs/security.md` prima di modifiche strutturali o legate alla sicurezza —
in questo repo i compromessi sul threat model sono decisioni di primo livello,
non un ripensamento successivo.

Eventuali personalizzazioni specifiche del deployment vivono fuori dal
repo pubblico: istruzioni private per Claude Code in `CLAUDE.local.md`
(caricato automaticamente se presente) e file/script privati nella cartella
`customizations/` — entrambi in `.gitignore`. Non citare dettagli di
infrastruttura personale (host, IP, altri progetti privati) nei file
versionati.

## Architettura

Tre container, singolo host:

```
React PWA ── Nginx (same-origin) ── FastAPI backend
                                          │
                                  session/stream services
                                          │
                                  TmuxService (solo argv, shell=False)
                                          │
                        socket condiviso (volume Docker o file su host)
                                          │
                                    tmux-runtime container
```

- `web` (Nginx + build React) e `backend` (FastAPI) sono stateless e
  ricreabili — sicuro ricrearli a ogni deploy.
- `tmux-runtime` possiede il vero server tmux e le sessioni in esecuzione al
  suo interno. **Non ricrearlo mai durante un deploy normale** — farlo
  termina ogni sessione viva. Per modifiche di routine ricreare/riavviare
  solo `web`/`backend`.
- Il backend non esegue mai comandi shell a partire da input del client. Gli
  endpoint ricevono identificatori/operazioni tipizzati; `TmuxService`
  costruisce l'argv di tmux direttamente (mai una stringa di shell). I nomi
  di sessione alla creazione sono validati contro `^[A-Za-z0-9_-]{1,64}$`;
  l'identificatore canonico nell'API è però il session id tmux (`$N`,
  esposto come stringa numerica senza `$`, validato con `^\d{1,10}$`) — i
  nomi delle sessioni host preesistenti possono essere arbitrari e non vanno
  mai usati come target tmux.
- Due modalità di connettività a tmux controllate da `MAC_TMUX_MODE`:
  `docker` (socket su volume condiviso in `MAC_TMUX_SOCKET_PATH`, sessioni
  isolate nel container `tmux-runtime`) e `host` (socket tmux di default
  dell'utente host in `MAC_TMUX_SOCKET_FILE`, attivata con l'override
  `compose.host.yaml` e backend con UID/GID host — vedi
  `docs/adr/005-host-default-socket.md`). In modalità host il backend non
  deve mai avviare il server tmux (partirebbe dentro il container):
  `create_session` verifica prima che il server esista. Il contratto
  API/WebSocket è identico in entrambe le modalità.
- L'input di testo libero verso un pane tmux passa da `load-buffer -`/
  `paste-buffer` (mai `send-keys` con testo grezzo) così tmux non interpreta
  mai il payload come sequenze di tasti; l'invio di Enter è un endpoint
  separato e distinto (`POST /api/v1/sessions/{id}/keys`).
- Lo stream WebSocket (`/api/v1/ws/sessions/{id}`) fa polling di
  `capture-pane` e invia snapshot completi solo quando il contenuto cambia,
  rallentando da 500ms fino a 2s in inattività. Gli snapshot (non i diff)
  sono autorevoli — un client che si riconnette non deve riprodurre eventi
  persi. Vedi la sezione "Streaming" in `docs/architecture.md` prima di
  modificare questo loop.

## Modello di autenticazione

Password condivisa singola (`MAC_LOGIN_PASSWORD`/`_FILE`), nessun account
utente per ora. `SessionSecurity` (`backend/app/security.py`) emette un
cookie firmato HMAC, con timestamp, HttpOnly e `SameSite=Strict`, più un
token CSRF separato restituito nel body JSON (mai come cookie) che il
frontend deve ripetere in `X-CSRF-Token` su ogni richiesta mutante.
L'handler WebSocket verifica inoltre l'`Origin` rispetto a
`cors_origins`/stesso host prima di accettare la connessione. Quando si
tocca l'auth, mantenere intatti questi tre controlli indipendenti: cookie di
sessione firmato, header CSRF sulle POST, controllo Origin sull'upgrade WS.

## Comandi

Tutti i comandi assumono Docker Compose (non esiste un loop di sviluppo
bare-metal supportato per lo stack completo).

```bash
# setup una tantum
cp .env.example .env
mkdir -p .secrets
openssl rand -base64 32 > .secrets/login_password
openssl rand -base64 48 > .secrets/session_secret

docker compose build
docker compose up -d
```

Test (ciascuno è un servizio one-shot con profilo `test`, non un container a
lunga esecuzione):

```bash
docker compose run --rm backend-test     # pytest + ruff, backend/
docker compose run --rm frontend-build   # tsc -b && vite build
docker compose config --quiet            # valida il file compose
```

Eseguire i test backend direttamente (iterazione più rapida, richiede
l'extra `dev` installato in locale):

```bash
cd backend
pytest                                # suite completa (testpaths = tests/)
pytest tests/test_api.py::test_name   # singolo test
pytest tests/test_tmux_service.py
ruff check .
```

Dev server frontend (richiede un backend con cui parlare — normalmente si
esegue tramite Compose):

```bash
cd frontend
npm run dev
npm run build      # tsc -b && vite build
```

Non è definito uno script di lint per il frontend in `package.json`;
affidarsi a `tsc -b` (incluso in `npm run build`) per il type checking.

## Struttura backend (`backend/app/`)

- `config.py` — `Settings` (pydantic-settings, prefisso env `MAC_`). I
  segreti possono essere passati direttamente o via path `_FILE` (Docker
  secrets); `read_secret` impone un minimo di 16 caratteri.
  `allowed_roots`/`cors_origins` accettano sia un array JSON che una stringa
  separata da virgole; `workspace_presets` (`MAC_WORKSPACE_PRESETS`,
  formato `label=path,...` o oggetto JSON) alimenta i suggerimenti di
  directory esposti da `GET /api/v1/config` — i valori reali stanno solo
  nel `.env`, mai nel repo.
- `security.py` — `SessionSecurity`: verifica password, emissione/validazione
  cookie di sessione, derivazione del token CSRF (HMAC sul cookie, non un
  valore memorizzato).
- `services/tmux_service.py` — Protocol `TmuxGateway` + `TmuxService`
  (implementazione reale via subprocess). `backend/tests/fakes.py` fornisce
  un gateway fake per i test delle API, così i test delle route non
  richiedono mai un binario tmux reale.
- `main.py` — factory `create_app(settings, tmux)` (entrambi gli argomenti
  iniettabili per i test); route e handler WebSocket vivono qui
  direttamente, non esistono ancora moduli router separati.
- `schemas.py` — modelli Pydantic di richiesta/risposta; i vincoli di
  validazione (es. `max_length` di `TextInput.text`, il pattern di
  `CreateSessionInput.name`) sono il contratto applicato, non solo hint di
  tipo.

Il whitelisting delle directory per la creazione di sessioni
(`MAC_ALLOWED_ROOTS`) è applicato nell'handler `create_session` in
`main.py` tramite `Path.resolve()` + controllo dei parent, non dentro
`TmuxService`.

## Struttura frontend (`frontend/src/`)

Attualmente piatta: `api.ts` (wrapper fetch + chiamate tipizzate, mantiene il
token CSRF in memoria, costruisce l'URL `ws(s)://` per lo stream) e
`App.tsx` (tutti i componenti/stato: login, lista sessioni + form di
creazione, vista console con WebSocket riconnettente e backoff
esponenziale). Nessun router, nessuna libreria di stato — solo
`useState`/`useEffect`. Mantenere il nuovo codice frontend coerente con
questo stile a dipendenze minime, salvo che una modifica lo richieda
davvero.

## Invarianti legati alla sicurezza (non allentarli senza leggere `docs/security.md`)

- Compose lega la porta pubblicata a `127.0.0.1` (o a un IP Tailscale
  esplicito) — mai `0.0.0.0`.
- Tutte le chiamate a tmux passano per liste argv, mai una stringa di shell.
- I target tmux sono sempre session id validati (`TARGET_ID`, `^\d{1,10}$`,
  interpolati come `$N`); i nomi alla creazione sono validati contro
  `SESSION_NAME` (`^[A-Za-z0-9_-]{1,64}$`). Nessuna stringa del client
  arriva a un target tmux senza passare da una di queste due validazioni.
- I container girano come non-root: `user: "10001:10001"` in modalità
  docker, l'UID/GID dell'utente host (`MAC_UID`/`MAC_GID`) in modalità
  host-tmux; sempre con `read_only: true` e `tmpfs` per i path scrivibili.
- In modalità host-tmux il backend non avvia mai il server tmux: se il
  server host non esiste deve fallire in modo esplicito (guardia in
  `TmuxService.create_session`, ADR 005).
- I segreti sono montati solo a runtime (`secrets:` di Compose), mai
  incorporati nelle immagini né committati — `.secrets/` è in gitignore.
