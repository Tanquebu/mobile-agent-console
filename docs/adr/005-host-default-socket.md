# ADR 005: modalità host sul socket tmux di default dell'utente

Stato: accettata. Supera la scelta del socket dedicato di ADR 004.

## Contesto

Le sessioni create in modalità Docker girano nel container `tmux-runtime`,
che contiene solo tmux: gli agenti CLI installati sull'host (`claude`,
`codex`), gli alias/funzioni dell'utente e le sessioni tmux già esistenti
sull'host sono invisibili. Il socket dedicato proposto da ADR 004 avrebbe
risolto i comandi ma non la visibilità delle sessioni preesistenti, che
vivono sul socket di default dell'utente (`/tmp/tmux-<uid>/default`).

## Decisione

In modalità `host` il backend (ancora containerizzato) si collega al
**socket tmux di default dell'utente host**, eseguendo come **UID/GID
dell'utente host** (`MAC_UID`/`MAC_GID`, richiesti dal file override
`compose.host.yaml`). Configurazione, tutta esplicita in `.env`:

```env
COMPOSE_FILE=compose.yaml:compose.host.yaml
MAC_UID=1000
MAC_GID=1000
MAC_TMUX_SOCKET_DIR=/tmp/tmux-1000
MAC_TMUX_SOCKET_FILE=/tmp/tmux-1000/default
MAC_WORKSPACE_ROOT=/home/user/projects
```

Scelte vincolanti:

- **Opt-in esplicito**: la modalità host richiede `MAC_TMUX_SOCKET_FILE`
  esplicito (`Settings` fallisce altrimenti) e l'attivazione manuale
  dell'override Compose. Nessun default silenzioso.
- **UID e Docker rootless**: `MAC_UID`/`MAC_GID` devono corrispondere al
  proprietario del socket *visto dal container*. Con Docker rootful sono
  l'uid/gid reali dell'utente; con Docker rootless sono `0/0`, perché il
  daemon gira nello user namespace dell'utente e l'uid host dell'utente è
  mappato su root del container (un uid non-zero nel container corrisponde
  a un subuid host senza accesso al socket). In rootless "root nel
  container" non conferisce privilegi reali sull'host.
- **Guardia anti auto-start**: se il server tmux host non è attivo, un
  `new-session` dal container avvierebbe il server *dentro il container*
  (filesystem e PATH sbagliati, in modo silenzioso). In modalità host il
  backend non avvia mai il server: `create_session` verifica prima che il
  server esista e altrimenti fallisce con errore esplicito. Resta una
  micro-race (server che muore tra verifica e `new-session`), resa teorica
  da una sessione keepalive e comunque evidente dal comportamento.
- **Mount della directory del socket, non del file**: il bind di un file
  socket blocca l'inode; se il server tmux riparte ricrea il socket e il
  container resterebbe su un inode morto. Si monta `/tmp/tmux-<uid>`.
- **Identificatore canonico = session id tmux (`$N`)**, esposto in API come
  stringa numerica senza `$`. I nomi delle sessioni host possono contenere
  caratteri fuori da `^[A-Za-z0-9_-]{1,64}$` e `-t <nome>` fa
  prefix-matching ambiguo; l'id è assegnato dal server, univoco e validato
  con `^\d{1,10}$`. Il nome resta per display, creazione e rinomina: viene
  normalizzato NFC e limitato a parole Unicode di lettere/numeri con `_`, `-`
  e spazi singoli, ma non diventa mai un target tmux.
- **Target = `$N`** (pane attivo della window corrente), non `:0.0`: le
  sessioni preesistenti possono avere `base-index 1` o più window.
- **`bash -l`** per le nuove sessioni: il pane è già interattivo (pty),
  `-l` carica anche `~/.profile`/`~/.bash_profile` (PATH degli agenti CLI).
- **Path host reali**: in modalità host `MAC_ALLOWED_ROOTS` e il workspace
  montato usano gli stessi path dell'host, perché la working directory
  delle sessioni è risolta dal server tmux host.

## Conseguenze e trade-off di sicurezza

- Una compromissione del backend consente di leggere e inviare input a
  **tutte** le sessioni tmux dell'utente host, ovvero esecuzione di comandi
  arbitrari come quell'utente. È il rischio residuo già dichiarato in
  `docs/security.md` ("compromissione del backend ≡ compromissione
  dell'utente"), ora senza la mitigazione del socket dedicato: la scelta è
  deliberata e va riconsiderata se il deployment smette di essere
  single-user su rete Tailscale privata.
- I tre controlli indipendenti (cookie firmato, CSRF header, Origin check
  sul WebSocket) e il bind su loopback/IP Tailscale restano invariati e
  diventano più critici.
- Il client tmux nel container e il server tmux host devono parlare lo
  stesso protocollo: il Dockerfile del backend compila tmux dal sorgente
  alla versione pinnata `TMUX_VERSION` (build arg, oggi `3.6a`), da tenere
  allineata alla versione dell'host quando la si aggiorna. Un eventuale
  mismatch viene comunque rilevato a runtime ("protocol version mismatch")
  ed esposto dal campo `tmux` di `/health` e nei log di startup.
- Il server tmux host deve esistere prima di `docker compose up`: se
  `/tmp/tmux-<uid>` non esiste, Docker creerebbe la directory come root e
  tmux host rifiuterebbe di usarla. Consigliata una user unit systemd o una
  sessione keepalive (vedi README).
- L'unità utente
  `deploy/systemd/mobile-agent-console-tmux-host.service` prepara
  `/tmp/tmux-$UID` con permessi `0700` e avvia `keepalive` dopo il reboot.
  Non contiene `ExecStop`, così fermarla o aggiornarla non termina le
  sessioni operative.
- La modalità Docker resta la modalità di default per sviluppo e test
  isolati; il contratto API/WebSocket è identico nelle due modalità.
