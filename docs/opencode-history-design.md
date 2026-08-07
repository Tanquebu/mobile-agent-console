# Progetto — Collector transcript OpenCode (vista Cronologia)

**Stato:** proposta di progetto (design), non implementata e non autorizzata.
Non sostituisce `OC-04`/`OC-05` della roadmap (`docs/opencode-integration.md`):
analizza il supporto per una *cronologia leggibile* delle sessioni OpenCode,
come già fatto per Claude in ADR 007. Data di verifica sul campo: 07/08/2026,
OpenCode `1.18.11`.

## Contesto

Come Claude, la TUI OpenCode usa lo schermo alternativo: `tmux capture-pane`
espone soltanto il viewport corrente, non lo scrollback. La vista Terminale
mostra quindi solo l'ultimo frame TUI e spesso non basta a rileggere
l'output di un turno.

La vista Blocchi (abilitata per OpenCode nel frontend) è una trasformazione
client-side del solo frame visibile: utile per la conversazione corrente, ma
eredita lo stesso limite di viewport. Per la lettura completa serve una
sorgente strutturata: il transcript persistente di OpenCode.

## Sorgente: database SQLite

A differenza di quanto ancora documentato su `opencode.ai/docs/troubleshooting`
(struttura `project/<slug>/storage/` con JSONL), OpenCode `1.18.11` installato
sulla macchina di verifica conserva tutto in:

```
~/.local/share/opencode/opencode.db     (SQLite, WAL attivo)
```

Tabelle rilevanti (schema verificato):

| Tabella | Colonne utili | Uso |
|---|---|---|
| `session` | `id`, `directory`, `title`, `model`, `agent`, `parent_id`, `time_created`, `time_updated`, `time_archived` | correlazione pane→sessione, esclusione subagent/archiviate |
| `message` | `id`, `session_id`, `time_created`, `time_updated`, `data` (JSON) | ruolo (`role`), timestamp |
| `part` | `id`, `message_id`, `session_id`, `time_created`, `data` (JSON) | contenuto per tipo |

Tipi di `part` osservati su dati reali:

- `text`: `{"type":"text","text":"..."}` — testo user/assistant;
- `tool`: `{"type":"tool","tool":"bash","callID":...,"state":{"status","input","output"}}`
  — esecuzione tool (l'output può essere grande);
- `reasoning`: `{"type":"reasoning","text":...}` — pensiero dell'assistente;
- `patch`: `{"type":"patch","hash":...,"files":[...]}` — modifiche ai file;
- `step-start` / `step-finish`: delimitatori di turno (con token/cost);
- `compaction`: compattazione del contesto.

Il DB contiene anche credenziali (`account.access_token`,
`credential.value`): **non devono mai essere lette né copiate**.

## Correlazione pane tmux → sessione OpenCode

OpenCode non espone un riferimento al pane tmux (a differenza della cache
context di Claude). Il collector usa la stessa primitiva di
`provider-session-state-collector.py` (`tmux list-panes -a -F ...` con
`#{pane_current_path}`), filtrando i pane il cui comando contiene
`opencode`, e poi:

1. `session.directory == pane.cwd` (confronto esatto, path normalizzati);
2. `parent_id IS NULL` (solo sessioni top-level: i subagent restano fuori);
3. `time_archived IS NULL` (sessioni attive);
4. a parità di directory, scegliere la sessione con `time_updated` massimo.

La sessione attiva è quella che il processo TUI sta aggiornando, quindi ha il
`time_updated` più recente tra quelle della stessa directory: la scelta resta
stabile anche con più sessioni storiche nello stesso progetto. **Limite noto e
dichiarato:** se due sessioni diverse della stessa directory vengono entrambe
toccate di recente (poco probabile in un solo processo), la correlazione può
attribuire quella sbagliata. Il raffinamento (statusline hook, evento del
server OpenCode) è materia di `OC-04` e non è necessario per il primo rilascio.

## Normalizzazione

Il normalizzatore produce una vista minimale, coerente con il confine di
ADR 007 (nessun contenuto di tool, nessun comando, nessun output):

- **messaggio user**: testo dei `part` `text` del messaggio `role=user`;
- **messaggio assistant**: testo dei `part` `text`;
- **assistant senza testo, con tool**: voce `activity` il cui contenuto è
  **solo il nome del tool** (es. `bash`), mai `input`/`output`;
- **assistant senza testo, con `patch`**: voce `activity` `patch`;
- `reasoning`, `step-start`, `step-finish`, `compaction`: esclusi;
- **`pending: true`**: se l'ultima voce è un'attività senza testo successivo
  (tool ancora in corso o in attesa di conferma), stesso segnale di ADR 007;
- timestamp dal `time_created` del messaggio (epoch ms → ISO UTC).

Limiti applicati come per Claude: `MAX_MESSAGES_PER_SESSION=500`,
`MAX_MESSAGE_CHARS=32*1024`, file derivato ≤ 2 MiB, con flag `truncated`.

## Confini di sicurezza

- Il collector gira **sull'host come user unit**, come
  `mobile-agent-console-claude-history`; apre il DB **solo in lettura**
  (`sqlite3.connect("file:...?mode=ro", uri=True)`), mai in scrittura,
  e con `PRAGMA query_only=1`. Il WAL consente letture concorrenti senza
  interferire con la TUI attiva. Nessuna copia del DB.
- Il backend **non monta** `~/.local/share/opencode`; riceve soltanto il file
  derivato `0600` sotto `.mobile-agent-console/opencode-history.json`,
  come per Claude.
- Il file derivato contiene solo testo user/assistant, nomi tool, timestamp:
  niente comandi, niente output, niente path, niente credenziali. Non è
  incluso nei backup amministrativi (stessa scelta ADR 007).
- Collector assente, lento o con DB in formato diverso → **nessun file** →
  endpoint `404`: mai una regressione del flusso tmux live.

## Contratto di output

Stessa forma di `claude-history.json` (`version: 1`):

```json
{
  "version": 1,
  "collected_at": "...",
  "sessions": [
    {
      "session_id": "12",
      "provider": "opencode",
      "source_updated_at": "...",
      "truncated": false,
      "messages": [
        { "id": "msg_...", "role": "user", "content": "...",
          "timestamp": "...", "kind": "message", "pending": false }
      ]
    }
  ]
}
```

Scrittura atomica con modo `0600` (`atomic_json_write`), cap su
`MAX_OUTPUT_BYTES` come `claude-history-collector.py`.

## Integrazione backend/frontend

- `MAC_OPENCODE_HISTORY_ENABLED` (default `false`) + `MAC_OPENCODE_HISTORY_PATH`
  (default `/workspace/.mobile-agent-console/opencode-history.json`);
  rinnova con la stessa `max_age_seconds` di Claude.
- `OpenCodeHistoryService` speculare a `ClaudeHistoryService`: rifiuta file
  grandi, schema non valido, età fuori soglia, sessione/provider non coerenti.
- Endpoint `GET /api/v1/sessions/{session_id}/opencode-history`, autenticato,
  `404` se flag spento o file assente/stantio.
- Config espone `opencode_history_enabled` (solo admin, come Claude).
- Frontend: terza vista `Cronologia` per le sessioni OpenCode, speculare al
  tab di Claude; il rendering `outputMode === "history"` oggi è legato a
  `claude` e va generalizzato per provider.

## Deployment

```bash
cp deploy/systemd/mobile-agent-console-opencode-history.service ~/.config/systemd/user/
cp deploy/systemd/mobile-agent-console-opencode-history.timer ~/.config/systemd/user/
# .env: MAC_OPENCODE_HISTORY_ENABLED=true
systemctl --user daemon-reload
systemctl --user enable --now mobile-agent-console-opencode-history.timer
docker compose up -d --no-deps backend web
```

Nessun overlay compose: il collector scrive nel workspace già montato. Unità
`Type=oneshot`, `UMask=0077`, `NoNewPrivileges=yes`, timer `OnUnitActiveSec=5s`.

## Test previsti

- `deploy/tests/`: normalizzatore su un DB SQLite di fixture (schema minimo
  con sessioni/messaggi/part di esempio) — correlazione per directory,
  esclusione subagent/archiviate, esclusione tool I/O/reasoning, `pending`;
  lettura `mode=ro` con DB in WAL attivo.
- `backend/tests/`: flag spento con file valido, output tmux invariato,
  autenticazione, sessione/provider, staleness, schema, limiti, esclusione dei
  dati sensibili.
- `frontend`: tab Cronologia per OpenCode visibile solo con flag attivo.
- Round completo secondo `AGENTS.md`: build, test, deploy mirato, verifica
  sull'istanza pubblicata, `LATEST_RELEASE`, commit.

## Rollback

```bash
# .env: MAC_OPENCODE_HISTORY_ENABLED=false
systemctl --user disable --now mobile-agent-console-opencode-history.timer
docker compose up -d --no-deps backend web
```

Le sessioni tmux non vengono toccate; il file derivato può essere rimosso a
mano. Un upgrade di OpenCode che cambia schema del DB fa fallire il collector
con `404`, senza toccare il flusso live.

## Non obiettivi

- Adapter sul server OpenCode (`OC-04`): correlazione più precisa e stato
  strutturato, richiede ADR e gate propri.
- Supporto Docker (`OC-05`): richiede ricreare `tmux-runtime`, non autorizzato.
- Attribuzione quote/consumo a una sessione OpenCode: richiede la distinzione
  agente/provider della roadmap; qui si legge solo la conversazione.
