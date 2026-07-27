# Mobile Agent Console

[![CI](https://github.com/Tanquebu/mobile-agent-console/actions/workflows/ci.yml/badge.svg)](https://github.com/Tanquebu/mobile-agent-console/actions/workflows/ci.yml)

A mobile-first PWA to monitor and control interactive terminal processes
running in tmux sessions — AI coding agents (Claude Code, Codex, …), REPLs,
long-running jobs — from your phone, over your private network (e.g.
Tailscale). The core is agent-agnostic: every session is treated as a
generic terminal, with no dependency on any specific vendor or tool.

## Features

- List tmux sessions and create new shell sessions from mobile;
- near-realtime output stream over WebSocket (full-snapshot polling that
  backs off when idle);
- reliable text input — including multiline paste — via tmux buffers, with
  `Enter` as a deliberate, separate action (nothing runs by accident);
- controlled prompt attachments (images, PDF and UTF-8 text files), stored
  in a session-scoped workspace area, referenced by path in the prompt,
  metadata persisted in the same database as users/archives/audit, with an
  image thumbnail preview in the composer, a per-session aggregate storage
  quota on top of the per-file limit, and automatic removal after a
  configurable TTL;
- respond to agent permission prompts by typing the option number, then
  Enter if needed;
- special-key controls for permission prompts, plus explicitly confirmed
  interrupt and session termination actions;
- contextual permission controls: `/permissions` for Codex and `Shift+Tab`
  for Claude;
- persistent session snapshots that recreate shells after a host reboot and
  can open the native Codex or Claude resume picker;
- heuristic Codex/Claude badges for active, idle, feedback and authorization
  states, without persisting terminal content;
- opt-in chat blocks over the authoritative tmux snapshot, with an immediate
  switch back to the terminal view, rendered read-only by xterm.js with real
  ANSI colors (input stays the existing compose-then-send flow — no live
  keystroke capture);
- per-session context-window usage beside Codex/Claude in the dashboard;
- provider rate-limit usage and normalized permission state in the dashboard;
- an optional, isolated Claude transcript history view that never replaces
  the authoritative live tmux stream;
- allowed-directory navigation with UTF-8 preview and authenticated downloads;
- persistent users and roles, audit, archives, verified backups and offline
  restore;
- offline-tolerant PWA shell via a service worker (API calls always stay
  live), a connection-lost banner, and opt-in local notifications when a
  session starts waiting for feedback or authorization while the app is in
  the background;
- a Preferences panel (default view for Codex/Claude sessions: Blocks or
  Terminal), stored client-side;
- an in-app quick guide whose “What's new” section shows only the latest
  shipped roadmap item;
- directory suggestions in the new-session form, prefilled from the
  backend's allowed roots and optionally from your own presets
  (`MAC_WORKSPACE_PRESETS=label=path,...` in `.env`);
- login with an HMAC-signed HttpOnly cookie, CSRF header on every mutation,
  and Origin check on the WebSocket upgrade;
- two connectivity modes: an isolated containerized tmux, or your host's
  own tmux server (host CLIs, aliases, and pre-existing sessions included).

## Architecture

Three containers on a single host:

```
React PWA ── Nginx (same-origin) ── FastAPI backend
                                          │
                                  TmuxService (argv only, shell=False)
                                          │
                  docker mode: shared socket volume ── tmux-runtime container
                  host mode:   the host user's default tmux socket
```

- `web` (Nginx + React build) and `backend` (FastAPI) are stateless and safe
  to recreate on every deploy.
- In **docker mode** (default) a dedicated `tmux-runtime` container owns the
  tmux server: fully isolated, but sessions only see what is installed in
  that container. Never recreate it during a routine deploy — that kills
  every live session.
- In **host mode** ([ADR 005](docs/adr/005-host-default-socket.md)) the
  backend connects to the host user's default tmux socket: sessions run on
  the host with your PATH and shell aliases, and the console sees and
  controls your pre-existing tmux sessions. Read the security trade-off in
  [docs/security.md](docs/security.md) before enabling it.

The backend never builds shell strings from client input: endpoints receive
typed identifiers and operations, tmux is always invoked with argv lists,
and session targets are validated server-side.

## Quickstart (docker mode)

Requirements: Docker Engine with Docker Compose.

```bash
cp .env.example .env
mkdir -p .secrets
openssl rand -base64 32 > .secrets/login_password
openssl rand -base64 48 > .secrets/session_secret
docker compose build
docker compose up -d
```

Open `http://127.0.0.1:8081` and log in with the content of
`.secrets/login_password`. Secrets are mounted at runtime only — never baked
into images or committed. Set `MAC_WORKSPACE_ROOT` in `.env` to the
directory tree sessions may start in (mounted at `/workspace`).

### Avvio automatico con systemd

Le unit incluse sono **user unit** e usano Compose; non avviano Uvicorn
direttamente. Configurare il path del checkout senza modificare le unit:

```bash
mkdir -p ~/.config/systemd/user ~/.config/mobile-agent-console
cp deploy/systemd/mobile-agent-console-docker.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-host.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-tmux-host.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-provider-session-states.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-provider-session-states.timer ~/.config/systemd/user/
# Opzionali: installare solo se si abilita la cronologia Claude.
cp deploy/systemd/mobile-agent-console-claude-history.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-claude-history.timer ~/.config/systemd/user/
cp deploy/systemd/environment.example ~/.config/mobile-agent-console/environment
```

Modificare `MAC_INSTALL_DIR` nel file `environment`, quindi scegliere **una
sola** unit applicativa:

```bash
# Modalità Docker tmux
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-docker.service

# Oppure modalità host tmux
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-host.service
```

In modalità host la seconda unit avvia automaticamente anche il keepalive
tmux. Nessuna unit usa `PrivateTmp`: il socket predefinito in `/tmp/tmux-$UID`
resta raggiungibile. `stop` ferma soltanto `backend` e `web`, preservando
`tmux-runtime` e le sessioni; `reload` ricrea solo i servizi stateless. Per
l'avvio prima del primo login abilitare il lingering con
`loginctl enable-linger "$USER"`.

### Host-tmux mode

1. Make sure a host tmux server is running **before** `docker compose up`
   (your normal tmux is enough; otherwise start a keepalive):

   ```bash
   tmux new-session -d -s keepalive
   ```

   If `/tmp/tmux-<uid>` did not exist, Docker would create it root-owned
   and tmux would refuse it — hence the ordering.

   Per il recupero automatico dopo un reboot usare la procedura systemd sopra.
   La unit keepalive ricrea `/tmp/tmux-$UID` con modo `0700` e non contiene
   `ExecStop`, quindi fermarla o aggiornarla non termina le sessioni operative.

2. In `.env`, uncomment the host-tmux block (see `.env.example`):
   `COMPOSE_FILE=compose.yaml:compose.host.yaml`, `MAC_UID`/`MAC_GID`,
   `MAC_TMUX_SOCKET_DIR`, `MAC_TMUX_SOCKET_FILE`, `MAC_WORKSPACE_ROOT`.
   With **rootful** Docker use your real `id -u`/`id -g`; with **rootless**
   Docker use `0`/`0` (container uid 0 maps to the user owning the daemon
   and the socket, while a non-zero uid would map to an inaccessible
   subuid).

3. `docker compose up -d --build`, then verify:

   ```bash
   curl -s http://127.0.0.1:8081/health   # {"status":"ok","tmux":"ok"}
   ```

   If `tmux` reports an error ("no server running", "protocol version
   mismatch"), the backend never starts a tmux server on your behalf: start
   tmux on the host, or align versions. The backend's tmux client is
   compiled at the version pinned by the `TMUX_VERSION` build arg in
   `backend/Dockerfile` — keep it aligned with your host tmux. Rollback:
   remove `COMPOSE_FILE` from `.env` and `docker compose up -d`.

In host mode, the "directory" field when creating a session takes real host
paths under `MAC_WORKSPACE_ROOT`, not `/workspace`.

Session snapshots are stored under `.agent-snapshots` in the configured
workspace root, so they survive recreation of `web`/`backend` and a host
reboot. They save names, working directories and a safe restore mode, not
terminal output, process memory, environment variables or arbitrary commands.
In host mode the tmux server must be running again before restoring. Codex and
Claude history must also remain available in their normal persistent user
directories.

## Backup and restore

Administrators can create, list, download and delete backups from the
dashboard. Each ZIP contains a consistent SQLite copy, session snapshot JSON
files and a manifest with per-file SHA-256 checksums. By default the newest ten
archives are retained (`MAC_BACKUP_RETENTION`).

Restore is intentionally offline. Keep `tmux-runtime` (or host tmux) running,
stop only the stateless services, then restore the selected archive:

```bash
docker compose stop backend web
docker compose run --rm --no-deps backend \
  python scripts/restore_backup.py /workspace/.mobile-agent-console/backups/BACKUP_ID.zip \
  --database /workspace/.mobile-agent-console/app.db \
  --snapshots /workspace/.agent-snapshots
docker compose up -d --no-deps backend web
```

In host mode use the real `MAC_WORKSPACE_ROOT` paths instead of `/workspace`.
The restore validates every checksum and SQLite integrity before replacement.
Copy downloaded archives to encrypted off-host storage: local retention alone
does not protect against loss of the VPS.

## Provider rate limits

The optional user timer `mobile-agent-console-rate-limits.timer` runs the local
Codex and Claude rate-limit scripts once per minute, without Claude `--fresh`,
and writes a sanitized status file below `.mobile-agent-console`. Install the
service and timer beside the other user units, ensure
`MAC_WORKSPACE_ROOT` is set in
`~/.config/mobile-agent-console/environment`, then enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-rate-limits.timer
```

The dashboard refreshes these values once per minute. Provider credentials and
Codex transcripts are never mounted into the backend container.

In host-tmux mode the optional
`mobile-agent-console-provider-session-states.timer` correlates panes with
Codex and Claude transcripts every five seconds and writes only the normalized
permission level to `.mobile-agent-console/provider-session-states.json`.
Prompts and responses are never copied. Enable it with:

```bash
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-provider-session-states.timer
```

Codex context usage is read directly from its structured transcript. Claude
provides the exact percentage to status-line commands; the included minimal
`deploy/claude-context-cache.mjs` can be configured as Claude's `statusLine`
command, or its small cache-writing section can be merged into an existing
custom status line. It writes one `0600` JSON file per session under
`~/.claude/context-window-cache`, containing only percentage, window size,
timestamp and tmux pane id.

## Cronologia Claude opzionale

Claude usa lo schermo alternativo, quindi tmux non può fornire la cronologia
che resta visibile con `tmux attach`. In modalità host il collector opzionale
legge il transcript sull'host, conserva soltanto messaggi testuali
utente/assistente e pubblica un file derivato `0600` sotto
`.mobile-agent-console`. Thinking, tool input/output, allegati, sidechain e
metadati sono esclusi.

L'opt-in richiede entrambe le azioni:

```bash
# in .env
MAC_CLAUDE_HISTORY_ENABLED=true

systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-claude-history.timer
docker compose up -d --build --no-deps backend web
```

La vista `Cronologia` è separata da `Blocchi` e `Terminale`; lo stream tmux
continua a essere autorevole e non viene modificato. Rollback:

```bash
# impostare MAC_CLAUDE_HISTORY_ENABLED=false in .env
systemctl --user disable --now mobile-agent-console-claude-history.timer
docker compose up -d --no-deps backend web
```

Il file derivato può poi essere eliminato manualmente. Disabilitare la feature
non termina né ricrea sessioni tmux. Limiti e motivazioni sono in ADR 007.

## Secure exposure

The published port binds to `127.0.0.1` or to an explicit Tailscale IP
(`MAC_BIND_IP`) — never `0.0.0.0`. Recommended:

```bash
tailscale serve --bg http://127.0.0.1:8081
```

or set `MAC_BIND_IP` to your `tailscale ip -4` address and adjust
`MAC_CORS_ORIGINS` accordingly. Verify with `ss -ltnp` that nothing listens
on public interfaces. See [docs/security.md](docs/security.md) and
`deploy/tailscale/`.

With the direct-IP bind, nginx still serves plain `http://`, which browsers
treat as a non-secure context — the Notification and ServiceWorker APIs
silently refuse to work there even though Tailscale already encrypts the
traffic. `deploy/tailscale/README.md` documents terminating TLS in nginx
with a real certificate from `tailscale cert` for your tailnet's MagicDNS
name, so the app stays reachable only over Tailscale but as `https://`. An
optional user timer keeps the certificate renewed:

```bash
cp deploy/systemd/mobile-agent-console-tls-renew.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-tls-renew.timer ~/.config/systemd/user/
# set MAC_TAILNET_HOSTNAME in ~/.config/mobile-agent-console/environment
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-tls-renew.timer
```

## Tests

```bash
docker compose run --rm backend-test     # pytest + ruff
docker compose run --rm frontend-build   # tsc -b && vite build
docker compose config --quiet
```

## Documentation

Project documentation lives in [`docs/`](docs/) — architecture, threat
model, API and WebSocket contracts, requirements, roadmap, feature backlog,
and ADRs. It is currently written in Italian (as are the UI labels); the API
surface, configuration, and code are in English.

Start from the current [project overview](docs/overview.md) and
[technical roadmap](docs/roadmap.md).

## License

[MIT](LICENSE)
