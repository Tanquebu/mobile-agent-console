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
L’endpoint di creazione espone i profili `shell`, `codex`, `claude` e
`antigravity`, risolti
in argv costanti server-side.

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
tramite comandi costanti server-side. Antigravity viene riavviato con il suo
launcher costante `agy` e conserva la propria cronologia nel CLI; nessun comando
client arbitrario viene persistito o eseguito.

Il database SQLite vive in `.mobile-agent-console/app.db` nella root
persistente del workspace. L'avvio applica le migrazioni prima di esporre il
backend. tmux resta autorevole per le sessioni vive; output, prompt, file e
segreti non sono salvati nel database.

I backup amministrativi sono archivi ZIP locali sotto
`.mobile-agent-console/backups`. Una copia consistente di SQLite viene creata
con la backup API nativa e affiancata agli snapshot JSON. Il manifest contiene
dimensioni e SHA-256 dei singoli file; un checksum dell'intero archivio viene
salvato separatamente e verificato prima del download. La retention predefinita
mantiene gli ultimi dieci backup. Il restore è esclusivamente offline.

L'archivio conserva soltanto nome, directory, profilo, autore e data. Archiviare
è un'azione esplicita che scrive i metadati prima di terminare la sessione
tmux; il rilancio usa esclusivamente un profilo server-side e rimuove la voce
dall'archivio dopo la creazione riuscita.
Per i profili Codex e Claude il rilancio apre il selettore nativo di resume
tramite comandi costanti server-side; Antigravity rilancia `agy` e la shell
viene invece ricreata normalmente.

Nascondere una sessione è distinto dall'archiviazione: conserva la sessione
tmux in esecuzione e memorizza solamente il suo identificatore numerico nella
tabella `hidden_sessions`. L'elenco API continua a riportarla con il flag
`hidden`, così il client la esclude dalla dashboard ma può riaprirla o
renderla di nuovo visibile senza interrompere il processo.

L'audit append-only registra attore, operazione tipizzata, target, esito HTTP e
timestamp delle mutazioni significative. Non registra body, query string, IP,
prompt, output, nomi file o segreti; input, tasti e resize ad alta frequenza
sono esclusi. La lettura è riservata agli amministratori.

L'autenticazione usa la tabella `users`: il primo avvio crea l'amministratore
dal secret di bootstrap e salva soltanto un hash Argon2id. I successivi login
interrogano il database, non confrontano la password con il secret runtime.
Il cookie firmato identifica l'username; autorizzazione e stato attivo sono
ricontrollati nel database a ogni richiesta e durante l'upgrade WebSocket.

## Streaming

Ogni connessione riceve uno snapshot, poi il backend cattura il pane ogni 500
ms mentre cambia e rallenta fino a 2 s in inattività. Gli aggiornamenti
successivi sono delta per righe con `base_sequence_id`: questa granularità
preserva Unicode e sequenze escape senza condividere indici di carattere tra
Python e JavaScript. Se il client rileva una base inattesa, riconnette e riceve
un nuovo snapshot autorevole; non serve riprodurre eventi persi.

`capture-pane` guadagna un flag `-e` opt-in (sequenze ANSI incluse), richiesto
dal client solo per la vista Terminale (`?ansi=true` sul WebSocket) e mai dagli
altri consumatori di `capture_output` (euristiche di attenzione, fetch
iniziale, check di stato) — cambia solo il contenuto catturato, non il
protocollo: stesso modello snapshot/delta, stessa semantica di riconnessione.
La vista Terminale renderizza lo snapshot con xterm.js in sola visualizzazione
(`disableStdin`): a ogni aggiornamento il buffer viene azzerato e riscritto da
zero, coerente con "riconnessione/aggiornamento = stato autorevole", non un
byte-stream incrementale. Questo significa che lo scroll dell'utente nel
buffer xterm viene "azzerato" a ogni nuovo contenuto esattamente come nella
vecchia vista testuale (stesso limite noto, non introdotto da xterm.js — vedi
`docs/backlog.md`). Il modello di input non cambia: il testo libero passa
sempre da `load-buffer`/`paste-buffer`, mai da input diretto verso il widget.

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

L'osservabilità host usa un boundary separato descritto in ADR 009. Una user
socket unit systemd `AF_UNIX` attiva un collector one-shot soltanto quando il
backend si collega; non esiste un listener TCP né un demone residente. Il
backend monta in sola lettura esclusivamente la directory del socket e non
riceve `/proc`, `/sys` o il socket Docker. Una unit preparatoria applica ACL
POSIX ristrette all'UID host effettivo del backend: `10001` in Docker rootful o
l'UID mappato esplicitamente in rootless/`userns-remap`; la modalità host usa
invece l'owner. Le ACL predefinite sulla directory vengono ereditate dal socket
ricreato da systemd, senza ricorrere a permessi world-writable. Il collector
HO-02 legge `/proc` e filesystem esclusivamente sull'host e restituisce il
contratto v1 limitato; Docker è opzionale e usa un solo comando ad argv fisso.
Il contratto v2 mantiene la lettura della configurazione v1 legacy ma aggiunge
policy locali per listener e gruppi processo e un campione swap limitato. Il
payload separa `bind_scope` da `external_reachability=not_assessed` e non espone
le soglie private. Backend e frontend accettano entrambe le versioni durante il
rollout e rifiutano versioni future o payload misti; non vengono introdotte
sonde o dipendenze di rete. Path, inventario e soglie restano nella
configurazione host privata. API e UI
sono separate: HO-03 aggiunge un `GET /api/v1/host-observability` opt-in,
riservato agli admin e con rate limit dedicato; HO-04 aggiunge la vista mobile
separata. Il backend valida nuovamente l'intero contratto Pydantic e non persiste,
audita o logga la fotografia. Il client config espone il flag soltanto agli
admin, così i ruoli non autorizzati non preparano la futura vista.

HO-04 consuma l'endpoint in una vista mobile separata, montata soltanto quando
ruolo e flag sono entrambi validi. La fotografia viene richiesta una volta
all'apertura e soltanto con refresh manuale; mentre la vista è aperta vengono
sospesi anche i polling della dashboard. Un contatore di richiesta e un guard
di mount scartano risposte concorrenti obsolete o successive all'unmount. Un
refresh fallito conserva l'ultima fotografia valida e ne segnala esplicitamente
lo stato stale, senza nascondere componenti validi per un errore parziale.
L'export JSON è una vista derivata con `JSON.stringify(snapshot, null, 2)` dallo
stesso ultimo snapshot valido: non richiama nuovamente l'API, non introduce un
wrapper o metadati UI e cambia soltanto dopo un refresh riuscito. Il fallback
clipboard seleziona la `textarea` read-only per una copia manuale, senza
`execCommand` o trasformazioni del contenuto.

Durante il rollout la vista distingue esplicitamente i fatti osservati dalla
valutazione prodotta da soglie e policy. Con il contratto v2 mostra tutti i
listener locali, il relativo esito di policy e
`external_reachability=not_assessed` come dato non accertato: uno scope di bind
non viene mai presentato come prova che una porta sia sicura, chiusa o
raggiungibile dall'esterno. Il fallback v1 continua a mostrare le sole porte
inattese e dichiara che policy e raggiungibilità non sono disponibili.

Le unit systemd sono user unit separate per modalità Docker e host. Entrambe
delegano l'avvio a Compose; allo stop e al reload agiscono soltanto su `backend`
e `web`, preservando il runtime tmux. In modalità host la unit applicativa
ordina il keepalive prima di Compose e non usa `PrivateTmp`.

Un timer systemd host-side esegue ogni minuto gli script locali di controllo
quote Codex e Claude senza modalità `--fresh`, provando prima la forma
strutturata `--json` e ricadendo sul parsing testuale storico quando lo script
non la offre. Il collector scrive soltanto un JSON sanitizzato in
`.mobile-agent-console/provider-rate-limits.json`; il backend legge quel file
e non riceve accesso a credenziali Claude o transcript Codex. L'assenza o
l'errore di un provider non influenza il runtime tmux.

ADR 010 aggiunge a questo stesso collector uno storico append-only,
`.mobile-agent-console/provider-rate-limits-history.jsonl`: ogni campione porta
provider, percentuali per finestra, epoch di reset, l'istante di raccolta e
quello dichiarato dalla sorgente, più una marcatura `stale` quando i due
divergono oltre soglia. Campioni identici consecutivi non vengono appesi, il
file ruota e la ritenzione predefinita è 14 giorni. Il backend continua
soltanto a leggere: `RateLimitHistoryService` valida ogni riga con Pydantic e
scarta quelle non conformi senza fallire, esposte in sola lettura da
`GET /api/v1/provider-rate-limits/history`. L'unica scrittura remota resta
l'aggiornamento forzato: un collector one-shot attivato dallo stesso
meccanismo di ADR 009 (socket Unix, socket activation, nessun demone) invocato
da `POST /api/v1/provider-rate-limits/refresh`, admin-only, dietro rate limit
dedicato e con errori tipizzati `429`/`503`/`504`. La persistenza temporale è
quindi ammessa per le quote provider — il cui valore è nella differenza fra
due istanti — e resta invece esclusa per l'osservabilità host (ADR 009), dove
il valore è quasi interamente nel presente: vedi ADR 010 per la motivazione
completa di questa asimmetria.

Un secondo collector host-side, indipendente dal precedente, attribuisce il
consumo di token per sessione scoprendo i transcript per tempo di modifica
invece che a partire dai pane tmux — l'unico modo per rendere visibile anche
il consumo headless (run senza pane, es. orchestratori esterni). Legge in
modo incrementale con cursori per percorso/inode/offset, deduplica le risposte
per identificativo di richiesta (le partial di streaming altrimenti
moltiplicherebbero il consumo) e arrotola i subagent sotto il
`session_uuid` della sessione madre. Scrive
`.mobile-agent-console/session-usage-history.jsonl` (righe per intervallo di
cinque minuti, sessione, modello e natura subagent), letto dal backend in
sola lettura e validato riga per riga. L'origine è `mac` quando l'id di
sessione tmux mappa un pane vivo, altrimenti `headless`; la differenza fra la
crescita della quota globale e la somma attribuita è pubblicata come residuo,
non nascosta. Il contratto completo di entrambi i file è in
`docs/contracts/budget-history-v1.md`. Questa fase è in corso: lo stato di
avanzamento di collector ed endpoint è tracciato in `docs/backlog.md`
(`BH-02`).

Un secondo collector host-side correla i PID dei pane con i transcript JSONL
aperti da Codex o aggiornati da Claude. Ogni cinque secondi pubblica soltanto
session id, provider e livello permessi normalizzato in
`.mobile-agent-console/provider-session-states.json`. Il backend non monta
`/proc`, `~/.codex` o `~/.claude`.
Lo stesso file può includere la percentuale della finestra di contesto: Codex
la espone nei propri eventi `token_count`; Claude la consegna allo statusline,
che salva una cache per sessione associata direttamente al pane tmux.

La dashboard interroga ogni tre secondi uno stato agentico aggregato. Il
backend considera soltanto pane con comando corrente `codex` o `claude`,
acquisisce le ultime 80 righe e applica classificatori separati con precedenza
ad autorizzazione, richiesta di feedback, marker attivi, variazione recente
dell'output e prompt inattivo. Gli stati sono euristici e includono sempre un
fallback `unknown`; l'output osservato resta esclusivamente in memoria.
Il livello permessi strutturato del collector viene normalizzato in
`restricted`, `standard`, `elevated`, `bypass`, `plan` o `unknown`; il testo
del TUI resta un fallback quando il collector non dispone di un'associazione.

La vista Chat blocks è una trasformazione esclusivamente client-side dello
snapshot tmux autorevole. Riconosce marker di prompt, risposta e attività per
Codex/Claude, non persiste contenuti e permette sempre il ritorno immediato
alla resa terminale integrale.

La cronologia Claude è invece un adapter opzionale e separato (ADR 007). Un
collector host-side associa pane e sessione Claude tramite la cache context,
normalizza il transcript e scrive atomicamente un file derivato privato. Il
backend lo espone con un endpoint read-only solo quando il feature flag è
attivo. WebSocket, capture tmux e Chat blocks live non dipendono dal collector:
assenza, ritardo, errore o rollback della cronologia lasciano invariato il
flusso terminale.

Lo stato dei task schedulati dell'orchestratore è raccolto da un terzo
collector host-side: interroga un endpoint read-only configurato nel file
environment privato, convalida nuovamente il payload e pubblica un file JSON
derivato. Il backend
riceve solo provider, quote, stato, prossimo tentativo, fallback e metadati di
fase; prompt, path, pane, checkpoint e messaggi d'errore restano fuori dal
container.

Il download degli artefatti prodotti dall'agente (verso opposto di M2A) non
usa un adapter provider-specifico: alla creazione di ogni sessione il backend
crea una cartella di consegna dedicata (stesso pattern di storage/validazione
by-signature di M2A, invertito). Il percorso di consegna non viene mai inviato
automaticamente al CLI: l'operatore lo invia esplicitamente dal menu Funzioni,
via lo stesso meccanismo `load-buffer`/`paste-buffer` usato per l'input libero.
Questo preserva i flussi di onboarding, consenso e login del CLI — nessuna
modifica ai CLAUDE.md di progetto, nessun collector host-side, nessun parsing
di transcript. Qualunque file che l'agente (o l'utente) copia in quella cartella
diventa per definizione un artefatto scaricabile; il backend non si fida di
alcun path stampato nel terminale e non apre altre directory. La pulizia è
legata al ciclo di vita della sessione, come per gli allegati M2A.
