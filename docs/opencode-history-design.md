# Progetto — OpenCode Transcript History (vista Blocchi)

**Stato:** implementato, verificato e rilasciato (15/08/2026, OpenCode `1.18.11`).
Integra lo storico nativo delle conversazioni dal database SQLite locale
di OpenCode (`opencode.db`) nella vista Blocchi, con rendering Markdown e
collassamento dinamico.

## Contesto

Come Claude, la TUI OpenCode usa lo schermo alternativo: `tmux capture-pane`
espone soltanto il viewport corrente, non lo scrollback. La vista Terminale
mostra quindi solo l'ultimo frame TUI e non consente di rileggere l'intero
storico di turni e output precedenti.

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

`model` non è il nome nudo del modello: OpenCode ci serializza un JSON tipo
`{"id":"deepseek-v4-flash-free","providerID":"opencode"}` (a volte anche con
`"variant"`). Chi legge questa colonna deve fare `json.loads` ed estrarre
`id` — vedi `OpencodeService._extract_model_id` in
`backend/app/services/opencode_service.py`, usato da `read_session_model`
per il nome modello mostrato in dashboard (`/api/v1/agent-statuses`).
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
context di Claude). Il backend (modalità host-tmux) apre il DB in sola
lettura e, per la sessione tmux viva richiesta, filtra le conversazioni:

1. `session.directory == pane.cwd` (confronto esatto, path normalizzati);
2. `time_created >= created_at` della sessione tmux (il primo prompt del
   processo OpenCode del pane materializza la conversazione soltanto dopo
   l'avvio del pane, quindi le conversazioni storiche restano fuori);
3. a parità di directory, scegliere la conversazione con `time_created`
   minimo tra quelle nate dopo l'avvio del pane.

La conversazione appartiene al pane tmux che era attivo alla sua nascita:
scegliere la prima nata dopo l'avvio del pane evita che una conversazione di
un'altra sessione tmux — anche già chiusa, ma con `time_updated` più recente
della propria in stato idle — rubi la correlazione e mostri blocchi altrui.
**Limite noto e dichiarato:** se un pane resta idle per molto tempo prima del
primo prompt mentre un'altra sessione della stessa directory viene usata, la
prima conversazione nata in quel lasso può essere attribuita al pane sbagliato.
Il raffinamento (statusline hook, evento/adapter sul server OpenCode) è
materia di `OC-04` e non è necessario per il rilascio corrente.

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
