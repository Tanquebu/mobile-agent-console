# ADR 007 — Adapter opzionale per la cronologia Claude

## Stato

Accettata.

## Contesto

Claude Code usa il terminale a schermo alternativo. La cronologia interna è
visibile con `tmux attach`, ma `capture-pane` espone soltanto lo schermo
corrente e non lo scrollback del TUI. Aumentare il numero di righe richiesto al
gateway non risolve il problema.

Montare `~/.claude` nel backend amplierebbe inutilmente il confine di fiducia e
renderebbe il flusso live dipendente da un formato provider-specifico. Sostituire
il WebSocket tmux introdurrebbe inoltre regressioni per input, controlli
interattivi e sessioni non-Claude.

## Decisione

La cronologia è un adapter read-only opt-in:

1. un collector user-systemd host-side correla il pane tmux all'UUID Claude
   tramite la cache context già esistente;
2. legge al massimo gli ultimi 16 MiB del JSONL e conserva soltanto record
   testuali `user`/`assistant`;
3. esclude thinking, tool input/output, allegati, meta e sidechain;
4. applica limiti a messaggi, testo e file, poi scrive atomicamente con modo
   `0600` sotto `.mobile-agent-console`;
5. il backend valida nuovamente schema, dimensione e freschezza e serve il dato
   soltanto con `MAC_CLAUDE_HISTORY_ENABLED=true`;
6. il frontend offre `Cronologia` come terza vista. `Blocchi` e `Terminale`
   continuano a usare esclusivamente lo stream tmux.

Il file derivato contiene conversazioni e non è incluso nei backup
amministrativi.

## Non regressione

- Nessuna modifica al contratto o al loop del WebSocket.
- Nessuna modifica a capture, input, tasti o resize tmux.
- Collector assente, lento o malformato produce solo `404` sulla cronologia.
- I test coprono flag spento con file valido, output tmux ancora disponibile,
  autenticazione, sessione/provider, staleness, schema, limiti ed esclusione
  dei record sensibili.

## Rollback

Impostare `MAC_CLAUDE_HISTORY_ENABLED=false`, fermare/disabilitare
`mobile-agent-console-claude-history.timer` e ridistribuire soltanto backend e
web. Le sessioni tmux non vengono ricreate. L'eventuale file
`.mobile-agent-console/claude-history.json` può essere rimosso separatamente.

## Conseguenze

La cronologia diventa finalmente leggibile oltre lo schermo TUI, ma quando
abilitata esiste una copia derivata persistente delle conversazioni nel
workspace. L'opt-in, la minimizzazione e i limiti riducono il rischio senza
eliminarlo; per questo la feature resta separata dal core agent-agnostic.

## Addendum: eccezione mirata per `AskUserQuestion`

Su sessioni reali, la maggior parte dei turni assistant/user non ha alcun
blocco `text` (solo `tool_use`/`tool_result`: Edit, Bash, Read, ...) e quindi
sparisce dalla cronologia per punto 3 sopra. Per `AskUserQuestion` — un menu
di domande/opzioni verso l'utente — questo produce un buco proprio dove la
continuità serve di più: sia la domanda (tool_use, nessun testo) sia la
risposta (tool_result, nessun testo) svaniscono.

A differenza di Bash/Edit/Read, l'input di `AskUserQuestion`
(domanda/opzioni) e il suo `tool_result` (la risposta) sono già testo
conversazionale semplice, non contenuto di file o comandi. Il normalizzatore
(`claude_transcript_normalizer.py`) tratta quindi come testo solo questo
tool, specificamente: la domanda/opzioni lato assistant e il `tool_result`
il cui `tool_use_id` corrisponde a un `AskUserQuestion` visto in precedenza
nello stesso transcript. Tutti gli altri tool restano esclusi esattamente
come al punto 3 — l'eccezione non riapre il confine generico su tool
input/output.

## Addendum: indicatore di attività (solo nome tool, nessun contenuto)

Anche fuori da `AskUserQuestion`, i tratti senza alcun blocco `text` restano
un problema pratico: durante un giro di tool (Bash/Edit/Read/...) o mentre è
a schermo il prompt nativo di conferma ("vuoi procedere?"), la cronologia
resta silenziosa dall'ultimo testo fino al prossimo, dando l'impressione che
si sia fermata proprio dove serve più continuità — tipicamente quando
l'agente sta per chiedere un'autorizzazione.

Il normalizzatore emette quindi, per i record assistant con solo
`tool_use` e nessun testo, una voce di tipo `"activity"` il cui contenuto è
**esclusivamente il nome del tool** (es. `"Bash"`, `"Edit"`), mai il suo
`input`/`output`: resta quindi dentro il confine del punto 3, non lo
allarga. Se l'ultima voce della cronologia è un'attività senza alcun testo
successivo, viene marcata `pending: true` — segnale di solo stato ("il tool
è ancora in corso o in attesa di conferma"), non contenuto aggiuntivo.
Record senza un nome tool valido restano esclusi come prima.

## Addendum: Blocchi usa la cronologia nativa quando disponibile

Il punto 6 della Decisione ("`Blocchi` e `Terminale` continuano a usare
esclusivamente lo stream tmux") è rivisto per `Blocchi`: Claude Code gira a
schermo alternativo, quindi `capture-pane` espone al massimo l'altezza
corrente del pane — per sessioni che lavorano da sole per minuti/ore la
vista Blocchi mostrava sistematicamente pochissime righe, un limite
strutturale non dell'adapter (vedi Contesto sopra) ma della sorgente dati
scelta per quella vista. `Terminale` non è toccato: resta l'unica vista
sempre garantita, senza dipendenze opzionali, esattamente come nella
Decisione originale.

Quando `MAC_CLAUDE_HISTORY_ENABLED=true` e la cronologia contiene almeno un
messaggio testuale, `Blocchi` la usa come sorgente primaria (stesso
adapter, stessa pipeline di validazione/freschezza già descritta sopra),
con fallback automatico allo stream tmux quando il flag è spento, il
collector è assente/stale, o la cronologia è vuota — stesso comportamento
di errore già previsto in "Non regressione" (collector assente, lento o
malformato non rompe nulla, degrada silenziosamente).

Compromesso accettato consapevolmente: la cronologia nativa esclude tool
input/output per costruzione (punto 3 della Decisione), quindi i Blocchi
alimentati da essa mostrano meno dettaglio operativo (solo il nome del
tool, mai il suo output) rispetto alla vista live da stream tmux che
mostravano prima quando il pane conteneva ancora quel turno. Si scambia
profondità di storico con dettaglio del turno più recente — non è una
regressione della vista live (che resta identica quando la cronologia non
è disponibile), è un cambio deliberato di sorgente dati quando lo storico
vale più del dettaglio tool dell'ultimo turno visibile a schermo.

## Addendum: correlazione pane→conversazione instabile su riavvio del server tmux

Portare la cronologia in primo piano su `Blocchi` (addendum precedente) ha
reso visibile un bug di correlazione preesistente nel collector: la mappa
pane→UUID Claude (`~/.claude/context-window-cache/<uuid>.json`, campo
`tmux_pane`) non viene mai ripulita per i pane chiusi, e `#{pane_id}` di
tmux non è stabile nel tempo — viene riassegnato da zero se il server tmux
riparte (riavvio host, `kill-server`, ecc.). Un pane **nuovo, mai usato**
può quindi ricevere lo stesso `%N` di un pane vecchio il cui file di cache
è rimasto sul disco: osservato in produzione, una sessione appena aperta
mostrava in `Blocchi` la cronologia di una conversazione chiusa 13 giorni
prima, sullo stesso numero di pane riassegnato dopo un riavvio del server.

Fix in `deploy/claude-history-collector.py`: la correlazione ora richiede
anche che il campo `updated_at` del file di cache non sia precedente
all'avvio della sessione tmux del pane corrente (`#{session_created}`);
altrimenti la voce è trattata come assente, mai come dato valido — nessuna
sessione emessa per quel pane invece di contenuto sbagliato. Lo stesso bug
di classe esisteva anche in `deploy/provider-session-state-collector.py`
per il badge `ctx X%` (stessa cache, stesso campo `tmux_pane` senza
controllo di freschezza): corretto in parallelo con lo stesso criterio, lì
basato su `process_started_at(pid)` del processo del pane (già disponibile
e più preciso di `session_created`, immune anche al riuso dello stesso
pane all'interno di una sessione tmux longeva), con fallback sulla ricerca
già esistente per PID (`claude_transcript`) quando la cache è assente o
stantia.
