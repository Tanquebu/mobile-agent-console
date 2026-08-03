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
  live) and a connection-lost banner;
- opt-in Web Push notifications when a session starts waiting for feedback
  or authorization — detected by an always-on backend task, independent of
  whatever view the frontend has open, so it works even with the app fully
  closed;
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
  own tmux server (host CLIs, aliases, and pre-existing sessions included);
- opt-in, admin-only host observability collected on demand through a hardened
  Unix socket boundary, with no `/proc`, `/sys` or Docker socket mounted in the
  backend and no polling from the Host view;
- opt-in budget history: a provider quota time series (with reset-aware
  windows and staleness marking) and a per-session token breakdown that
  discovers transcripts by modification time — so headless, pane-less runs
  are attributed too — with subagents rolled up under the session that
  spawned them, in a `Budget` view in the dashboard.

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

### Automatic startup with systemd

The included units are **user units** and drive Compose; they do not start
Uvicorn directly. Configure the checkout path without editing the units:

```bash
mkdir -p ~/.config/systemd/user ~/.config/mobile-agent-console
cp deploy/systemd/mobile-agent-console-docker.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-host.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-tmux-host.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-provider-session-states.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-provider-session-states.timer ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-orchestrator-state.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-orchestrator-state.timer ~/.config/systemd/user/
# Optional: install only if you enable Claude history.
cp deploy/systemd/mobile-agent-console-claude-history.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-claude-history.timer ~/.config/systemd/user/
cp deploy/systemd/environment.example ~/.config/mobile-agent-console/environment
```

Set `MAC_INSTALL_DIR` in the `environment` file, then enable **exactly
one** application unit:

```bash
# Docker tmux mode
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-docker.service

# Or host tmux mode
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-host.service
```

In host mode the second unit also starts the tmux keepalive automatically.
No unit uses `PrivateTmp`: the default socket under `/tmp/tmux-$UID` stays
reachable. `stop` only stops `backend` and `web`, preserving `tmux-runtime`
and the sessions; `reload` recreates only the stateless services. To start
before the first login, enable lingering with
`loginctl enable-linger "$USER"`.

### Host-tmux mode

1. Make sure a host tmux server is running **before** `docker compose up`
   (your normal tmux is enough; otherwise start a keepalive):

   ```bash
   tmux new-session -d -s keepalive
   ```

   If `/tmp/tmux-<uid>` did not exist, Docker would create it root-owned
   and tmux would refuse it — hence the ordering.

   For automatic recovery after a reboot, use the systemd procedure above.
   The keepalive unit recreates `/tmp/tmux-$UID` with mode `0700` and has no
   `ExecStop`, so stopping or updating it does not terminate live sessions.

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

### Host observability

The optional Host view reports a minimized snapshot of memory, load,
configured filesystems, processes, unexpected listeners and mapped Docker
problems. Collection is one-shot and admin-only; it is disabled unless
`compose.host-observability.yaml` is explicitly included. The collector
config supports the legacy v1 shape and the v2 contract, which adds
per-process and per-listener policy scoring (allowed scopes, RSS/count
thresholds) without changing the endpoint, auth or export format — see
[docs/contracts/host-observability-v2.md](docs/contracts/host-observability-v2.md).
The expandable JSON export copies the exact already-sanitized API snapshot,
without another fetch or UI-only metadata. Copying or sharing it is an
explicit administrator action: the minimized operational data can still be
sensitive outside its intended context. Installation, rootless UID mapping,
security checks, rollback and the complete release gate are documented in
[docs/gates/host-observability.md](docs/gates/host-observability.md). The
example configuration contains placeholders only and must be copied outside
the repository with exact mode `0600`.

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
and writes a sanitized status file below `.mobile-agent-console`. The same
collector run also appends a sample to the quota history JSONL described
below. Install the service and timer beside the other user units, ensure
`MAC_WORKSPACE_ROOT` is set in
`~/.config/mobile-agent-console/environment`, then enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-rate-limits.timer
```

The dashboard refreshes these values once per minute. Provider credentials and
Codex transcripts are never mounted into the backend container.

## Budget history

Beside the instantaneous quota snapshot above, an opt-in feature set adds a
historical view of provider quota consumption and a per-session breakdown of
where it went — see [ADR 010](docs/adr/010-storico-consumo-budget.md) and the
[budget history contract](docs/contracts/budget-history-v1.md).

The existing `mobile-agent-console-rate-limits.timer` from the section above
already appends each sample to `provider-rate-limits-history.jsonl` as a
structured time series, with no extra unit needed: each row carries a
`resets_at` epoch per window (so the physiological decay of the rolling
5-hour window doesn't read as usage dropping), a `stale` flag when the
underlying source is older than the configured threshold, and a `parse_mode`
that records whether the row came from the provider's structured `--json`
output or from the historical text-parsing fallback. Consecutive identical
samples are not appended, and the file rotates under a retention window long
enough to cover the 7-day quota window with margin.

A second, independent collector (`mobile-agent-console-session-usage.timer`,
every 5 minutes) attributes token consumption to individual sessions. It
discovers transcripts by modification time rather than by walking tmux panes
— which is what makes consumption from pane-less, headless runs (an external
orchestrator, scheduled jobs) visible at all, instead of only sessions with a
live tmux pane. Responses are deduplicated by request id to avoid
double-counting streaming partials, and subagent transcripts are rolled up
under the session that spawned them, since subagent fan-out can dwarf the
token volume of the session itself. The raw token counters are kept separate
per bucket; no synthetic quota-percentage estimate is published, since it
can't be reconstructed accurately from those counters alone.

Both series feed a `Budget` view in the frontend, alongside a manual,
admin-only "refresh now" action that performs one real remote quota check on
request (never on a timer) through the same Unix-socket, socket-activated,
one-shot-collector boundary used by host observability, with its own rate
limit separate from the regular polling.

The quota history above is read automatically once the rate-limits timer is
running. Per-session attribution and the forced-refresh action are each
opt-in and require the `compose.budget-history.yaml` overlay, composable with
either `compose.yaml` or `compose.host.yaml`:

```bash
# in .env
COMPOSE_FILE=compose.yaml:compose.budget-history.yaml
MAC_HOST_OBSERVABILITY_SOCKET_DIR=/path/to/a/prepared/socket/dir
```

and the matching user units, beside the others:

```bash
cp deploy/systemd/mobile-agent-console-session-usage.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-session-usage.timer ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-rate-limit-fresh.socket ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-rate-limit-fresh@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-session-usage.timer
systemctl --user enable --now mobile-agent-console-rate-limit-fresh.socket
```

The forced-refresh socket reuses the same runtime directory and ACL-preparing
unit as host observability, so both features stay opt-in and independent
while sharing the same hardened boundary — `MAC_HOST_OBSERVABILITY_SOCKET_DIR`
is required by the overlay even if the Host view itself is not enabled. The
two JSONL files (`provider-rate-limits-history.jsonl`,
`session-usage-history.jsonl`) live `0600` in the workspace's
`.mobile-agent-console` state directory beside the other status files, are
read-only from the backend's point of view, and can be deleted at any time
without breaking the instantaneous snapshot.

Use `deploy/snapshot-env.sh [reason]` after any change to `.env` — it keeps
dated, `0600` copies under `customizations/env-snapshots/` (itself
git-ignored) and diffs against the previous snapshot, so a silently dropped
overlay or variable leaves a trail instead of vanishing unnoticed.

## Scheduled task status

The optional `mobile-agent-console-orchestrator-state.timer` reads the
read-only status of an external orchestrator every 30 seconds. Configure
`MAC_ORCHESTRATOR_STATE_URL`, `MAC_ORCHESTRATOR_STATE_TOKEN` and, if needed,
`MAC_ORCHESTRATOR_STATE_TOKEN_HEADER` in the console's private environment
file. The URL and token stay in the host-side collector and are never
mounted into the backend. Use HTTPS unless the endpoint is strictly loopback.

```bash
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-orchestrator-state.timer
```

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

## Optional Claude history

Claude uses the alternate screen, so tmux cannot provide the scrollback that
stays visible with `tmux attach`. In host mode, the optional collector reads
the transcript on the host, keeps only user/assistant text messages, and
publishes a derived `0600` file under `.mobile-agent-console`. Thinking,
tool input/output, attachments, sidechains and metadata are excluded.

Opting in requires both actions:

```bash
# in .env
MAC_CLAUDE_HISTORY_ENABLED=true

systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-claude-history.timer
docker compose up -d --build --no-deps backend web
```

The `History` view is separate from `Blocks` and `Terminal`; the tmux stream
remains authoritative and is not modified. Rollback:

```bash
# set MAC_CLAUDE_HISTORY_ENABLED=false in .env
systemctl --user disable --now mobile-agent-console-claude-history.timer
docker compose up -d --no-deps backend web
```

The derived file can then be deleted manually. Disabling the feature neither
terminates nor recreates tmux sessions. Limits and rationale are in ADR 007.

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
