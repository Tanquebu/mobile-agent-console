# Gate manuale — Storico consumo budget e attribuzione per sessione

Questo gate valida la fase A (storico della quota provider, `BH-01`) e la
fase B (attribuzione per sessione, `BH-02`) di ADR 010. Decisioni e contratto
sono in `docs/adr/010-storico-consumo-budget.md` e
`docs/contracts/budget-history-v1.md`; questo gate non li riapre.

I passi 3 e 4 (fan-out subagent, task headless) dipendono dal collector
`deploy/session-usage-collector.py` e dall'endpoint `GET /api/v1/session-usage`
di `BH-02`. Finché `IMP-BH-02` non è `DONE`, eseguirli resta bloccato — vedi lo
stato corrente in `docs/backlog.md`.

## Prerequisiti una tantum

La fase A riusa la stessa directory runtime e la stessa unit di preparazione
ACL dell'osservabilità host (ADR 009): installare prima
`docs/gates/host-observability.md` fino ad avere `mobile-agent-console-host-observability-prepare.service`
attiva, poi aggiungere le unit dedicate:

```bash
install -m 0644 deploy/systemd/mobile-agent-console-rate-limits.service ~/.config/systemd/user/
install -m 0644 deploy/systemd/mobile-agent-console-rate-limits.timer ~/.config/systemd/user/
install -m 0644 deploy/systemd/mobile-agent-console-rate-limit-fresh.socket ~/.config/systemd/user/
install -m 0644 deploy/systemd/mobile-agent-console-rate-limit-fresh@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemd-analyze --user verify deploy/systemd/mobile-agent-console-rate-limit-fresh.socket deploy/systemd/mobile-agent-console-rate-limit-fresh@.service
systemctl --user enable --now mobile-agent-console-rate-limits.timer
systemctl --user enable --now mobile-agent-console-rate-limit-fresh.socket
```

Verificare che gli script quote esistano in `~/.claude/rate-limit.sh` e
`~/.codex/rate-limit.sh` e supportino l'invocazione `--json`; il collector
ricade sul parsing testuale storico quando non lo offrono, senza fallire il
ciclo. Il contratto di formato che il collector applica a questi script
(invocazione, forma strutturata, degradazione ammessa) è documentato in
`docs/contracts/quote-script-v1.md`, non qui: questo gate verifica il
comportamento osservabile, non ridefinisce il contratto.

Attivare l'overlay Compose opt-in soltanto dopo aver validato la fase A senza
di esso (lo storico funziona già col solo timer host-side):

```bash
docker compose -f compose.yaml -f compose.budget-history.yaml config --quiet
```

Ricordare il vincolo di deploy: qualunque ricreazione di container in questo
gate tocca **soltanto** `web` e `backend`. Non ricreare né riavviare mai
`tmux-runtime` — farlo termina ogni sessione tmux viva.

## Check 1 — Timer, JSONL storico e deduplica a riposo

1. Osservare la dimensione e il contenuto di
   `.mobile-agent-console/provider-rate-limits-history.jsonl` prima
   dell'attivazione del timer, poi dopo due o tre cicli (il timer gira ogni
   minuto):

   ```bash
   wc -l .mobile-agent-console/provider-rate-limits-history.jsonl
   tail -n 5 .mobile-agent-console/provider-rate-limits-history.jsonl
   ```

2. Con nessuna sessione attiva (la sorgente quote resta ferma), il numero di
   righe non deve crescere a ogni ciclo: la deduplica per `observed_at`/
   percentuali deve tenere bassa la cardinalità a riposo. Confermare che le
   righe scartate non producano errori nel journal:

   ```bash
   systemctl --user status mobile-agent-console-rate-limits.timer mobile-agent-console-rate-limits.service
   ```

3. Verificare permessi e proprietario del file:

   ```bash
   stat -c '%a %U' .mobile-agent-console/provider-rate-limits-history.jsonl
   ```

   Atteso: `600`, proprietario l'utente host. Verificare inoltre che
   `provider-rate-limits.json` (lo snapshot istantaneo) continui a validare e
   che ogni finestra strutturata conservi lo stesso `resets_at` dello storico;
   gli snapshot legacy senza campo devono continuare a validare come `null`.

4. Aprire dashboard e Console sia con densità normale sia compatta. Per una
   finestra con `resets_at` valorizzato, la data locale del prossimo reset deve
   essere visibile accanto alla percentuale senza dipendere da hover o dal testo
   libero `detail`. Con `resets_at: null` la UI non deve inventare una data né
   mostrare una riga vuota.

## Check 2 — Curva 5h coerente con l'osservazione diretta

Con una sessione agente attiva per circa 30 minuti, confrontare la crescita
della finestra `5h` nella serie storica con l'osservazione diretta della
percentuale mostrata dallo statusline/script quote nello stesso intervallo:

```bash
curl --fail-with-body --cookie cookies.txt \
  'https://HOST/api/v1/provider-rate-limits/history?hours=1' | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); print([s["windows"] for s in d["samples"] if s["provider"]=="claude"][-5:])'
```

Atteso: la percentuale `5h` sale in modo monotono e coerente con l'attività
osservata (nessun plateau seguito da un salto improvviso non spiegabile da un
periodo di inattività); campioni marcati `stale` corrispondono a intervalli in
cui la sorgente non è stata aggiornata, non a un errore del collector.

## Check 3 — Fan-out di subagent annidati (fase B, bloccato finché BH-02 non è DONE)

Avviare una sessione che genera subagent (fan-out) e interrogare
`GET /api/v1/session-usage`. Atteso: i subagent compaiono annidati sotto il
`session_uuid` della sessione madre (mai come righe di primo livello
indistinguibili), con token aggregati superiori a quelli della sola sessione
madre — il fan-out è per costruzione il consumo dominante che questa
funzione rende visibile.

## Check 4 — Task headless senza pane tmux (fase B, bloccato finché BH-02 non è DONE)

Avviare un'esecuzione che scrive un transcript senza alcun pane tmux associato
(run headless di uno script/orchestratore esterno che usa lo stesso account
provider). Atteso: la riga corrispondente in `GET /api/v1/session-usage` ha
`origin: "headless"`, nessun `tmux_session_id`, e il campo `project` riporta
comunque l'ultimo segmento del percorso di progetto.

## Check 5 — Aggiornamento forzato e rate limit dedicato

```bash
curl --fail-with-body --cookie admin-cookies.txt -X POST \
  -H "X-CSRF-Token: $CSRF" https://HOST/api/v1/provider-rate-limits/refresh
```

Atteso: risposta con almeno un campione `"source": "fresh"`; il file storico
guadagna una riga fresh coerente con la stessa marcatura. Ripetere la
richiesta oltre `MAC_RATE_LIMIT_FRESH_RATE_LIMIT` volte nella stessa finestra:
deve rispondere `429` con `Retry-After` e senza invocare di nuovo il
collector. Verificare inoltre, separatamente:

- flag `MAC_RATE_LIMIT_FRESH_ENABLED` spento: `404`, nessuna connessione al
  socket;
- ruolo non-admin: `403`;
- socket fresh assente/non attivo: `503`;
- collector fresh oltre il timeout configurato: `504`.

## Check 6 — Assenza di dati sensibili nei due JSONL

```bash
grep -aiE '"prompt"|"response"|"reasoning"|"transcript_path"|"pid"|home/|/root/' \
  .mobile-agent-console/provider-rate-limits-history.jsonl \
  .mobile-agent-console/session-usage-history.jsonl
```

Atteso: nessuna corrispondenza in nessuno dei due file. Verificare anche
l'assenza di header HTTP, credenziali, hostname e username. Se
`session-usage-history.jsonl` non esiste ancora (fase B non completata),
annotarlo esplicitamente nel gate invece di trattarlo come pass silenzioso.

## Check 7 — Segnale di fallback testuale (`parse_mode`, BH-03)

Il collector pubblica quale forma ha prodotto ogni riga storica. Verificare
prima lo stato reale della sorgente:

```bash
tail -n 20 .mobile-agent-console/provider-rate-limits-history.jsonl | \
  python3 -c 'import json,sys; [print(json.loads(l)["provider"], json.loads(l).get("parse_mode")) for l in sys.stdin]'
```

- Se l'ultimo campione di un provider ha `parse_mode: "text"`, la vista
  Budget deve mostrare, sotto il grafico di quel provider, l'avviso "Fallback
  testuale attivo per questo provider…" — un'enunciazione di fatto, non un
  errore né un livello di allarme nell'interfaccia.
- Se l'ultimo campione ha `parse_mode: "structured"`, l'avviso non deve
  comparire.
- Se il file contiene righe scritte prima di questa funzione (`parse_mode`
  assente o `null`), verificare che non producano l'avviso: l'assenza del
  campo è "non noto", non equivalente a `"text"`.
- Per forzare l'osservazione del ramo testuale senza modificare gli script
  quote reali, è sufficiente puntare temporaneamente `--claude-script`/
  `--codex-script` del collector (variabili d'ambiente del timer, non
  argomenti hardcoded) a uno script di prova che rifiuta `--json` e stampa
  soltanto la forma testuale descritta in
  `docs/contracts/quote-script-v1.md`; ripristinare il percorso originale al
  termine della verifica.

## Check 8 — Funzioni opzionali attive (BH-03)

All'avvio del backend, verificare la riga di log che enuncia lo stato delle
funzioni opzionali:

```bash
docker compose logs backend | grep "Funzioni opzionali"
```

Atteso: una singola riga `INFO` con i sei nomi di funzione e il loro stato
`on`/`off`; nessun percorso, token o altro valore di configurazione al suo
interno; nessun livello `WARNING`/`ERROR` per questa riga, indipendentemente
da quali funzioni siano spente — un'installazione con tutte le funzioni
opzionali disattivate è uno stato valido, non un errore da segnalare.
Verificare inoltre, autenticati come admin, che lo stesso elenco compaia
nella vista Audit dell'interfaccia (sezione "Funzioni opzionali"), e che sia
assente per un ruolo non-admin (`GET /api/v1/config` restituisce
`optional_features: null`).

## Check 9 — Drill-down "fase C" (BH-04): flag dedicato, RBAC, transcript mancante, provenienza reale

Copre `IMP-BH-04` (`GET /api/v1/session-usage/timeline`,
`docs/contracts/session-timeline-v1.md`). Prerequisito aggiuntivo rispetto ai
prerequisiti comuni sopra: installare anche le due unit dedicate, che
riusano la stessa directory runtime preparata da
`mobile-agent-console-host-observability-prepare.service`:

```bash
install -m 0644 deploy/systemd/mobile-agent-console-session-timeline.socket ~/.config/systemd/user/
install -m 0644 deploy/systemd/mobile-agent-console-session-timeline@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemd-analyze --user verify deploy/systemd/mobile-agent-console-session-timeline.socket deploy/systemd/mobile-agent-console-session-timeline@.service
systemctl --user enable --now mobile-agent-console-session-timeline.socket
```

Il flag `MAC_SESSION_TIMELINE_ENABLED` è **indipendente** da
`MAC_CLAUDE_HISTORY_ENABLED` (ADR 007) e da `MAC_SESSION_USAGE_ENABLED`
(BH-02): verificare che spegnere/accendere uno dei tre non alteri gli altri
due, né nella risposta di `GET /api/v1/config` né nel comportamento
osservabile.

1. **Flag spento (default anche con l'overlay attivo).** Da admin loggato,
   `GET /api/v1/config` deve riportare `session_timeline_enabled: false` e
   `GET /api/v1/session-usage/timeline?...` deve rispondere `404`, senza
   alcuna connessione al socket (verificare che il collector non compaia fra
   le unit attive: `systemctl --user list-units 'mobile-agent-console-session-timeline@*'`
   resta vuoto).

2. **RBAC: nascosto ai non-admin, visibile solo all'admin.** Con
   `MAC_SESSION_TIMELINE_ENABLED=true` e autenticazione a più ruoli (richiede
   `MAC_DATABASE_AUTH_ENABLED=true`), verificare che `operator`/`viewer`
   ricevano `session_timeline_enabled: false` da `/api/v1/config` e `403`
   dall'endpoint; l'admin riceve `true` e i dati.

3. **Sessione reale, provider Claude.** Individuare in
   `session-usage-history.jsonl` una riga `provider: "claude"` con `turns > 0`
   (o un bucket noto per contenere una compattazione/uno spawn di subagent) e
   interrogare:

   ```bash
   curl --fail-with-body --cookie admin-cookies.txt \
     'https://HOST/api/v1/session-usage/timeline?provider=claude&session_uuid=<uuid>&bucket_start=<bucket_start>'
   ```

   Atteso: `available: true`, `turns` non vuoto con i quattro contatori di
   token e il modello, `tool_counts` con chiavi solo dalla tassonomia fissa
   (`file_read`, `file_write`, `exec`, `network`, `task_management`,
   `subagent_orchestration`, `other`), mai un nome di strumento grezzo in
   nessun campo della risposta.

4. **Sessione reale, provider Codex.** Ripetere il passo 3 con
   `provider=codex` su una riga Codex reale. Atteso: stessa forma della
   risposta; se il bucket copre una compattazione Codex,
   `compactions[].pre_tokens`/`post_tokens` sono `null` (dichiarato `n/d`,
   non un difetto — Codex non pubblica quel conteggio, verificato su dati
   reali in `docs/contracts/session-timeline-v1.md`).

5. **Compattazione e spawn di subagent su dati reali.** Se si dispone di un
   transcript Claude con un evento `compact_boundary` (cercabile con
   `grep -l compact_boundary` sotto `~/.claude/projects`) o di un transcript
   Codex con `sub_agent_activity`/`kind: "started"` (sotto
   `~/.codex/sessions`), calcolare il bucket di 5 minuti che contiene
   l'istante dell'evento e verificare che compaia rispettivamente in
   `compactions`/`subagent_spawns` della risposta, con solo istante (e
   pre/post token per Claude), mai testo o percorso.

6. **Transcript ruotato/rimosso → stato dichiarato, non un errore.**
   Interrogare un `session_uuid` inesistente (o rinominare temporaneamente un
   transcript reale, ripristinandolo subito dopo). Atteso: risposta `200` con
   `available: false` e `unavailable_reason: "transcript_not_found"` (o
   `"transcript_unreadable"`), mai `404`/`500` del backend.

7. **Errori di trasporto restano errori.** Fermare temporaneamente il socket
   (`systemctl --user stop mobile-agent-console-session-timeline.socket`) e
   ripetere la richiesta del passo 3: atteso `503`
   `session_timeline_unavailable`. Riavviare il socket al termine.

8. **Ispezione avversariale del payload.** Su una risposta reale del passo 3
   o 4:

   ```bash
   curl -s --cookie admin-cookies.txt \
     'https://HOST/api/v1/session-usage/timeline?provider=claude&session_uuid=<uuid>&bucket_start=<bucket_start>' | \
     grep -aiE '"prompt"|"description"|"reasoning"|"input"|"arguments"|"replacement_history"|/home/|/root/|\.jsonl'
   ```

   Atteso: nessuna corrispondenza. Verificare anche che la risposta non
   contenga mai il nome grezzo di uno strumento (es. `"Bash"`, `"Read"`,
   `"exec_command"`) fuori dalle chiavi fisse della tassonomia.

9. **`claude-history` resta indipendente.** Con `MAC_CLAUDE_HISTORY_ENABLED`
   spento e `MAC_SESSION_TIMELINE_ENABLED` acceso (o viceversa), verificare
   che l'una funzioni indipendentemente dall'altra: nessun errore incrociato,
   nessun riferimento nella UI dell'una verso l'altra.

## Comandi automatici

```bash
docker compose run --rm backend-test pytest tests/test_rate_limit.py tests/test_rate_limit_collector.py tests/test_rate_limit_history_api.py tests/test_rate_limit_history_service.py tests/test_rate_limit_status_service.py
docker compose run --rm backend-test ruff check --no-cache app/services/jsonl_tail.py app/services/rate_limit_history_service.py app/services/unix_socket_json_client.py app/services/rate_limit_fresh_client.py app/main.py app/schemas.py tests/test_rate_limit_history_api.py tests/test_rate_limit_history_service.py tests/test_rate_limit_collector.py
python3 -m unittest discover -s deploy/tests
cd frontend && npm run test:budget && npm run test:admin && npm run build
systemd-analyze --user verify deploy/systemd/mobile-agent-console-rate-limit-fresh.socket deploy/systemd/mobile-agent-console-rate-limit-fresh@.service
docker compose config --quiet
docker compose -f compose.yaml -f compose.budget-history.yaml config --quiet
docker compose -f compose.yaml -f compose.host.yaml -f compose.budget-history.yaml config --quiet
git diff --check
```

`test:budget` copre anche il badge di fallback testuale (`parse_mode`) sulla
vista Budget; `test:admin` (nuovo con BH-03) copre l'elenco delle funzioni
opzionali nella vista Audit.

`docker compose run --rm backend-test pytest tests/test_rate_limit_collector.py`
carica `deploy/rate-limit-collector.py` direttamente da file: se eseguito fuori
da `backend-test` (che monta `/deploy`), verificare che il proprio ambiente
esponga comunque quel percorso, altrimenti il test fallisce per un motivo
infrastrutturale già noto e non una regressione. `deploy/tests/` si esegue in
locale con `python3 -m unittest discover -s deploy/tests` (nessun servizio
Compose dedicato oggi definisce questi test).

## Vincolo di deploy

Qualunque pubblicazione di questa funzione ricrea esclusivamente `web` e
`backend`:

```bash
docker compose -f compose.yaml -f compose.budget-history.yaml up -d --no-deps backend web
```

Non fermare, ricreare o includere mai `tmux-runtime` nel comando. Prima e dopo
il deploy, confrontare identificatori e stato delle sessioni tmux esistenti
per confermare la continuità del runtime.

## Rollback

Disabilitare i timer/socket dei nuovi collector, rimuovere l'overlay
`compose.budget-history.yaml` e ricreare soltanto `web`/`backend`. I due file
JSONL possono essere rimossi senza conseguenze: nessun'altra funzione ne
dipende e lo snapshot istantaneo delle quote continua a funzionare con il
contratto invariato (ADR 010, sezione "Rollback").
