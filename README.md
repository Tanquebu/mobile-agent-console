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
  in a session-scoped workspace area, referenced by path in the prompt and
  automatically removed after a configurable TTL;
- respond to agent permission prompts by typing the option number, then
  Enter if needed;
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

### Host-tmux mode

1. Make sure a host tmux server is running **before** `docker compose up`
   (your normal tmux is enough; otherwise start a keepalive):

   ```bash
   tmux new-session -d -s keepalive
   ```

   If `/tmp/tmux-<uid>` did not exist, Docker would create it root-owned
   and tmux would refuse it — hence the ordering.

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

## Tests

```bash
docker compose run --rm backend-test     # pytest + ruff
docker compose run --rm frontend-build   # tsc -b && vite build
docker compose config --quiet
```

## Documentation

Project documentation lives in [`docs/`](docs/) — architecture, threat
model, API and WebSocket contracts, requirements, roadmap, and ADRs. It is
currently written in Italian (as are the UI labels); the API surface,
configuration, and code are in English.

## License

[MIT](LICENSE)
