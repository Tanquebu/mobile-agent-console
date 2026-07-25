# Architettura

## Decisione

Monolite modulare containerizzato su singolo host: Nginx serve React e inoltra
API/WebSocket same-origin; FastAPI espone il dominio; un container runtime
separato possiede tmux. SQLite conserva i metadati applicativi tramite
SQLAlchemy e migrazioni Alembic (ADR 006).

```text
React PWA ── Nginx same-origin ── FastAPI
                                      │
                              session/stream services
                                      │
                              TmuxService (argv only)
                                      │
                         volume socket condiviso
                                      │
                             tmux-runtime
```

## Moduli

- `config`: ambiente validato e default sicuri.
- `security`: autenticazione e, successivamente, CSRF/rate limit.
- `tmux_service`: elenco, capture, buffer/paste e tasti; nessuna policy HTTP.
- `api`: validazione trasporto e mapping errori.
- `websocket`: snapshot polling, sequence monotona per connessione e heartbeat.
- frontend `api/hooks/pages`: trasporto separato dalla presentazione.

Il browser non conosce comandi shell. Gli endpoint ricevono identificatori e
operazioni tipizzate; directory e profili vengono risolti/validati server-side.
L’endpoint di creazione espone soltanto il profilo `shell` in questo incremento.

## Container e persistenza

`web` e `backend` sono stateless e aggiornabili. `tmux-runtime` è un boundary
separato, non privilegiato, con socket su volume condiviso e workspace montato
da una root esplicita. La sua ricreazione termina i processi: deploy e rollback
devono ricreare soltanto web/backend. Prima di dichiarare l'HA del runtime sarà
necessaria una decisione dedicata tra tmux host-systemd e supervisor container.

Gli snapshot di riavvio non conservano processi o memoria: il backend stateless
scrive metadati JSON atomici in `.agent-snapshots` sotto il workspace
persistente. Il ripristino ricrea shell con nome e directory salvati. I profili
Codex e Claude possono soltanto aprire i rispettivi selettori nativi di resume
tramite comandi costanti server-side; nessun comando client arbitrario viene
persistito o eseguito.

Il database SQLite vive in `.mobile-agent-console/app.db` nella root
persistente del workspace. L'avvio applica le migrazioni prima di esporre il
backend. tmux resta autorevole per le sessioni vive; output, prompt, file e
segreti non sono salvati nel database.

L'autenticazione usa la tabella `users`: il primo avvio crea l'amministratore
dal secret di bootstrap e salva soltanto un hash Argon2id. I successivi login
interrogano il database, non confrontano la password con il secret runtime.

## Streaming

Ogni connessione riceve uno snapshot, poi il backend cattura il pane ogni 500
ms mentre cambia e rallenta fino a 2 s in inattività. Gli aggiornamenti
successivi sono delta per righe con `base_sequence_id`: questa granularità
preserva Unicode e sequenze escape senza condividere indici di carattere tra
Python e JavaScript. Se il client rileva una base inattesa, riconnette e riceve
un nuovo snapshot autorevole; non serve riprodurre eventi persi.

## Evoluzione

Interfacce `TmuxService`/fake consentono test e futuri adapter. Profili,
attenzione e audit consumano eventi generici senza entrare nel runtime tmux.
API e protocollo versionati permettono il futuro client Android.

Il servizio tmux resta indipendente dal runtime: in modalità Docker usa il
volume `/tmux`, in modalità host si collega al socket tmux di default
dell'utente host (ADR 005), eseguendo con lo stesso UID/GID e con la
directory del socket montata via `compose.host.yaml`. Il contratto
API/WebSocket non cambia tra le due modalità. L'identificatore canonico di
una sessione nell'API è il session id tmux (`$N`, esposto come stringa
numerica senza `$`): i nomi — anche quelli arbitrari delle sessioni host
preesistenti — servono solo per il display e per la creazione. Capture e
input hanno come target il pane attivo della sessione, non `0.0`.
