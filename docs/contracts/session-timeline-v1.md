# Contratto drill-down session timeline v1 (BH-04)

Copre `GET /api/v1/session-usage/timeline`, il drill-down "fase C" di ADR 010
approvato in `GATE-BH-04` (addendum del 03/08/2026) con un confine più
stretto della vista di sessione (`BH-02`, `docs/contracts/budget-history-v1.md`):
**solo metadati di turno**, mai testo. Questo contratto non riapre ADR 010 né
il gate: ne è l'attuazione per la fase C.

Non è collegato a `claude-history` (ADR 007): flag indipendente
(`MAC_SESSION_TIMELINE_ENABLED`), nessun codice o UI condivisi, nessun
richiamo incrociato.

## Perché un flag dedicato

`MAC_CLAUDE_HISTORY_ENABLED` copre un dominio diverso (testo minimizzato di
conversazione, sessione live con pane attaccato). Questo drill-down copre
qualunque sessione storica, headless inclusa, e pubblica solo metadati
strutturali, mai testo. Il gate ha chiesto esplicitamente due domini separati:
un utente può avere l'uno senza l'altro.

## Meccanismo di lettura: on-demand, mai un mount di `~/.claude`/`~/.codex` nel backend

La lettura è on-demand alla richiesta, non persistita (nessun terzo JSONL,
nessun demone). Il transcript grezzo non entra però mai nel container
backend: ADR 007 ha già deciso, per lo stesso genere di dato, che «montare
`~/.claude` nel backend amplierebbe inutilmente il confine di fiducia» — la
stessa ragione vale qui, ed è più stringente perché questa funzione può
raggiungere qualunque sessione storica, non solo quella nel pane corrente.

Il backend attiva quindi, a ogni richiesta, lo stesso meccanismo host-side a
socket Unix one-shot già usato per l'osservabilità host e per l'aggiornamento
fresh della quota (ADR 009): un nuovo collector,
`deploy/session-timeline-collector.py`, attivato da
`mobile-agent-console-session-timeline.socket`
(`Accept=yes`, per-connessione, nessun demone persistente). A differenza dei
due boundary precedenti, che non hanno parametri, questo è parametrico: il
backend invia una riga di richiesta JSON (`provider`, `session_uuid`,
`bucket_start`, `bucket_end`) prima di leggere la risposta — estensione
additiva di `UnixSocketJsonClient.fetch()`, che resta invariato per i
collector esistenti quando non le viene passata alcuna richiesta.

Il collector risolve `session_uuid` → percorso file interamente host-side,
riusando l'approccio di `discover_claude_files`/`discover_codex_files`/
`codex_session_uuid` in `deploy/session-usage-collector.py` (qui una ricerca
diretta per `session_uuid`, non per mtime recente, perché il chiamante indica
esattamente quale sessione). Il percorso risolto non attraversa mai il
boundary verso il backend né verso il frontend: il collector risponde solo
con i metadati sotto, mai con il percorso.

## Richiesta

```
GET /api/v1/session-usage/timeline?provider=claude&session_uuid=<uuid>&bucket_start=2026-08-02T09:30:00Z
```

- Admin-only (`require_admin_session`, come `/api/v1/host-observability`):
  nascosto ai ruoli non-admin sia nel flag di `/api/v1/config`
  (`session_timeline_enabled`) sia con `403` diretto sull'endpoint.
- `404` quando `MAC_SESSION_TIMELINE_ENABLED` è spento — nessuna lettura del
  collector, nessuna connessione al socket.
- `provider` è `claude` o `codex`. `session_uuid` è validato con lo stesso
  pattern usato per i nomi di sessione tmux (`^[A-Za-z0-9_-]{1,64}$`) — qui
  però è un identificativo di sessione del provider, non un target tmux.
- `bucket_start` è l'inizio del bucket di 5 minuti già presente in una riga
  di `session-usage-history.jsonl` (BH-02); la finestra interrogata è
  `[bucket_start, bucket_start + 5min)`, calcolata lato backend, mai passata
  dal client.
- Rate limit dedicato (`MAC_SESSION_TIMELINE_RATE_LIMIT`/`_WINDOW_SECONDS`),
  `429` con `Retry-After` oltre soglia, come host-observability.

## Risposta

```json
{
  "provider": "claude",
  "session_uuid": "5b84b3fa-a26f-4642-abf3-851fc35abf3f",
  "bucket_start": "2026-08-02T09:30:00Z",
  "bucket_end": "2026-08-02T09:35:00Z",
  "available": true,
  "unavailable_reason": null,
  "turns": [
    {
      "timestamp": "2026-08-02T09:30:12.500Z",
      "model": "claude-opus-5",
      "input_tokens": 2,
      "cache_creation_input_tokens": 13784,
      "cache_read_input_tokens": 19595,
      "output_tokens": 626
    }
  ],
  "tool_counts": {"file_read": 3, "exec": 2, "subagent_orchestration": 1},
  "compactions": [
    {"timestamp": "2026-08-02T09:31:00.000Z", "pre_tokens": 164812, "post_tokens": 9539}
  ],
  "subagent_spawns": [
    {"timestamp": "2026-08-02T09:30:12.500Z"}
  ],
  "truncated": false
}
```

- `turns` è una riga per risposta del modello deduplicata (stessa regola di
  BH-02: le partial di streaming ripetono lo stesso blocco su timestamp
  diversi, l'ultima occorrenza vince), con i quattro contatori di token
  grezzi come delta di quel turno — **mai** testo, nomi o argomenti di
  strumenti, percorsi.
- `tool_counts` è aggregato sull'intera finestra, non per turno — il confine
  approvato qualifica "per turno" solo il delta dei quattro contatori di
  token, non i conteggi di strumenti. Le chiavi sono **esclusivamente** una
  tassonomia fissa interna (mai il nome grezzo dello strumento):
  `file_read`, `file_write`, `exec`, `network`, `task_management`,
  `subagent_orchestration`, `other`. Il backend scarta silenziosamente
  qualunque chiave fuori da questo insieme come difesa in profondità, nel
  caso il collector venga modificato in futuro senza aggiornare questo
  contratto.
- `compactions` è un evento per compattazione del contesto osservata nella
  finestra: istante e, quando disponibili, i token pre/post compattazione.
- `subagent_spawns` è un evento per spawn di subagent osservato: **solo** il
  fatto e l'istante, mai una descrizione, un prompt o l'identificativo del
  thread figlio. Il drill-down non segue mai il subagent nel proprio
  transcript (GATE-BH-04, punto 5): resta un roll-up esplicitamente non
  ricorsivo.
- `available: false` con `unavailable_reason` popolato è uno **stato
  dichiarato**, non un errore: il transcript sorgente è stato ruotato,
  rimosso o non è mai stato trovato per quel `session_uuid`. Valori
  osservati: `"transcript_not_found"` (nessun file corrispondente),
  `"transcript_unreadable"` (il file esiste ma non è leggibile, es. permessi
  o rotazione concorrente). La UI mostra questo stato esplicitamente
  ("non più disponibile"), mai un errore, mai una ricostruzione.
- `truncated: true` indica che la scansione del transcript ha raggiunto il
  tetto di byte configurato (`MAX_SCAN_BYTES`, 64 MiB lato collector) prima
  di completare la finestra: i segnali restituiti sono parziali, non un
  errore.

## Segnali dichiarati `n/d` per provider (motivati su dati reali)

- **Delta token della compattazione, solo Codex.** Claude pubblica
  `preTokens`/`postTokens` in `compactMetadata` del record
  `system`/`compact_boundary` (verificato su
  `~/.claude/projects/.../*.jsonl`, evento `compact_boundary`). Codex separa
  la compattazione in due record (`type: "compacted"` con
  `payload.replacement_history` — mai attraversato, contiene testo completo
  dei turni precedenti — e `type: "event_msg"` con
  `payload.type == "context_compacted"`, verificato su
  `~/.codex/sessions/2026/07/29/rollout-...-019fac8a-....jsonl`): nessuno dei
  due porta un conteggio di token. `pre_tokens`/`post_tokens` restano quindi
  sempre `null` per `provider: "codex"`, mai un valore calcolato o stimato.
- **Conteggio di strumenti per categoria, alcuni tipi di record Codex.**
  `function_call` e `custom_tool_call` pubblicano un campo `name`
  categorizzabile (verificato: `exec_command`, `write_stdin`, `update_plan`,
  `view_image`, `exec`, ...). `web_search_call` e `tool_search_call` non
  pubblicano alcun campo `name` (verificato: solo `action`/`arguments`, mai
  attraversati): per questi due tipi la categoria è dedotta dal tipo di
  record stesso (`network` e `other` rispettivamente), che è già sufficiente
  e non richiede il nome — non è quindi un `n/d`, ma una categorizzazione
  senza bisogno del nome.
- **Modello, talvolta assente per Codex.** `payload.info.model` non è sempre
  presente in `token_count` (verificato su transcript reali): quando manca,
  `model` è stringa vuota `""`, coerente con lo stesso trattamento già usato
  da `extract_codex_usage()` in `deploy/session-usage-collector.py`, non un
  errore.

## Privacy e failure mode

Non attraversano il boundary, in nessun campo: testo di prompt, testo di
risposte, ragionamento, nomi o argomenti di strumenti, percorsi del
transcript o della working directory, identificativi di thread/processo
figlio, hostname, username, credenziali, header HTTP. Il boundary è più
stretto di `docs/contracts/budget-history-v1.md` (che pubblica `project` e
`session_uuid`): qui `project` non è nemmeno incluso, perché il client ha già
quell'informazione dalla riga di `session-usage-history.jsonl` che ha
originato il drill-down.

Un provider/`session_uuid` senza transcript trovabile produce
`available: false`, mai un `404`/`500` del backend: l'assenza del transcript
è un fatto del dominio (rotazione, retention, sessione mai esistita con
quell'id), non un errore dell'API. Un errore genuino di trasporto (collector
assente, timeout, risposta malformata) resta invece un errore HTTP esplicito
(`503`/`504`), distinto dallo stato dichiarato "non disponibile" — stessa
distinzione già stabilita da `docs/contracts/budget-history-v1.md` e da
`GATE-BH-04` ("riferisce, non giudica").
