# Contratto host observability v3

Il contratto v3 estende v2 con il componente obbligatorio `tmux_orphans`.
Backend e frontend accettano v1, v2 e v3; versioni future e campi extra restano
rifiutati. Tutti i componenti v2 conservano forma e semantica.

`tmux_orphans` contiene `status`, `reasons`, `available`, `items`,
`scanned_scopes`, `truncated` e `state_age_seconds`. Ogni item espone soltanto:

- `pane_pid`, PID originario del pane scomparso;
- `age_seconds`, età dello scope;
- `tasks`, `memory_bytes`, `memory_peak_bytes` e `swap_bytes`, nullable quando
  systemd non fornisce il contatore.

Non attraversano il boundary UUID o nome dello scope, nome della sessione,
command line, cwd o environment. Il file host intermedio è descritto nell'ADR
013 e deve essere recente entro `max_age_seconds`.

La configurazione privata v3 richiede `tmux_orphans.state_file`. Accetta inoltre
`max_age_seconds` (default 120), `grace_seconds` (default 300),
`critical_memory_bytes` (default 1 GiB) e `critical_swap_bytes` (default 512
MiB). I candidati più giovani della grace period non vengono pubblicati.

Nessun item produce `ok`: uno o più orfani producono warning con
`tmux_orphan_detected`; il superamento di una soglia produce critical e il
reason specifico `tmux_orphan_memory_critical` o
`tmux_orphan_swap_critical`. File assente/non valido o helper indisponibile
producono `tmux_orphans_unavailable`; evidenza scaduta produce
`tmux_orphans_state_stale`. Il monitor non termina mai processi.
