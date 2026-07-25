# AGENTS.md

Istruzioni per gli agenti di sviluppo che lavorano in questo repository.
La documentazione di progetto è in italiano sotto `docs/`; prima di modifiche
strutturali o di sicurezza leggere almeno `docs/architecture.md` e
`docs/security.md`. Le decisioni architetturali sono registrate in `docs/adr/`.

## Contesto

Mobile Agent Console è una PWA mobile-first per monitorare e controllare
processi interattivi persistenti in tmux. Il core è agent-agnostic: sessioni
Codex, Claude, shell, REPL e altri CLI sono trattati come terminali generici.

Le personalizzazioni del deployment non appartengono al repository pubblico.
Non inserire nei file versionati host, IP o riferimenti ad altri progetti
privati. `CLAUDE.local.md` e `customizations/`, quando presenti, sono locali e
ignorati da Git.

## Architettura e invarianti

- `web` e `backend` sono stateless e possono essere ricreati durante il deploy.
- In modalità `docker`, `tmux-runtime` possiede le sessioni: non ricrearlo
  durante un deploy ordinario, perché terminerebbe le sessioni attive.
- In modalità `host`, il backend usa il socket tmux predefinito dell'utente
  tramite `compose.host.yaml`; non deve mai avviare un server tmux nel
  container. Vedere `docs/adr/005-host-default-socket.md`.
- Invocare tmux solo con liste argv e `shell=False`. Non costruire comandi
  shell da input client.
- I target API sono session id tmux numerici validati con `^\d{1,10}$` e
  trasformati in `$N` soltanto lato server. Non usare il nome della sessione
  come target tmux.
- I nomi in creazione e rinomina hanno al massimo 64 caratteri e rispettano
  `^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$`.
- Inviare testo libero tramite `load-buffer -` e `paste-buffer`; `Enter` e gli
  altri tasti restano operazioni separate.
- L'allowlist delle directory è applicata in `backend/app/main.py` con
  `Path.resolve()` e controllo dei parent.
- Lo stream WebSocket invia snapshot completi autorevoli quando il contenuto
  cambia; non presupporre che il client possa recuperare eventi intermedi.

## Sicurezza

Non allentare questi controlli senza aggiornare consapevolmente il threat
model:

- bind su `127.0.0.1` o su un IP Tailscale esplicito, mai `0.0.0.0`;
- cookie di sessione HMAC `HttpOnly` e `SameSite=Strict`;
- token CSRF nel body di login e header `X-CSRF-Token` su ogni mutazione;
- verifica `Origin` durante l'upgrade WebSocket;
- container non-root, filesystem read-only e `tmpfs` per i path scrivibili;
- segreti montati a runtime, mai nelle immagini o nel repository.

## Struttura corrente

- `backend/app/config.py`: impostazioni `MAC_*`, secret file, allowed roots,
  CORS e `MAC_WORKSPACE_PRESETS` (`label=path,...` oppure oggetto JSON).
- `backend/app/security.py`: cookie firmato e token CSRF.
- `backend/app/services/tmux_service.py`: gateway tmux reale.
- `backend/app/main.py`: app factory, route e WebSocket.
- `backend/app/schemas.py`: contratti e vincoli Pydantic.
- `backend/tests/fakes.py`: gateway fake per test senza tmux reale.
- `frontend/src/api.ts`: client HTTP/WebSocket e token CSRF in memoria.
- `frontend/src/App.tsx`: UI e stato React, senza router o state library.

Mantenere il frontend a dipendenze minime finché una modifica non richiede
esplicitamente una struttura diversa.

## Verifica

Uno step funzionale è concluso soltanto dopo implementazione, verifiche
automatiche, deploy mirato e test sull'istanza pubblicata. Non chiedere
all'utente di testare una modifica che non è ancora stata deployata. Durante
il deploy ricreare soltanto i servizi stateless coinvolti e preservare sempre
`tmux-runtime`, salvo richiesta esplicita contraria.

Lo stack completo è supportato tramite Docker Compose:

```bash
docker compose run --rm backend-test
docker compose run --rm frontend-build
docker compose config --quiet
```

Per iterazioni locali, se le dipendenze dev sono già installate:

```bash
cd backend
pytest
ruff check .

cd ../frontend
npm run build
```

Non esiste uno script lint frontend separato: `npm run build` esegue `tsc -b`
prima della build Vite.
