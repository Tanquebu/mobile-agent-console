# Backlog delle feature

Elementi valutati ma non ancora pianificati in una milestone. Ogni voce
documenta il problema e i vincoli noti, senza implicare un impegno di
implementazione immediato.

## Vista con più pane tmux visibili contemporaneamente

**Stato:** scartata deliberatamente, non da riprendere senza un motivo nuovo.

Valutata come possibile completamento di "Supporto multi-pane esteso" (M4):
invece del selettore a tendina attuale (un pane alla volta), mostrare 2+
output di pane contemporaneamente. Scartata perché l'app è mobile-first e
uno split reale sarebbe scomodo su schermi stretti — motivo per cui anche lo
split orizzontale/verticale scelto in MAC ha effetto visibile solo
collegandosi direttamente con `tmux attach`, non nella vista MAC stessa.
Richiederebbe comunque catturare anche la posizione dei pane da tmux
(`pane_left`/`pane_top`), non fatto oggi. Riconsiderare solo se emerge un
uso desktop-first per cui valga la pena la complessità.

## Toolbar terminali complete su viewport mobile

**Stato:** differita; impatto attuale basso.

Codex, Claude e altri programmi TUI possono abbreviare con un'ellissi le
toolbar o status line quando il pane tmux ha poche colonne. L'abbreviazione
avviene nel processo terminale prima di `capture-pane`: il frontend riceve
quindi già testo come `A…` e non può recuperare tramite CSS la parte omessa.

La sessione osservata durante la diagnosi misurava 80×24 celle. Allargare
automaticamente la finestra tmux è considerato fragile perché:

- altera anche la visualizzazione di eventuali client tmux desktop collegati;
- può cambiare il layout di finestre con più pane;
- applicazioni fullscreen e TUI reagiscono diversamente al resize;
- una larghezza adatta a una toolbar non coincide necessariamente con quella
  migliore per il resto dell'output.

Possibili direzioni future:

- controllo esplicito per sessione tra larghezza normale ed estesa;
- resize basato sulla viewport, con ripristino e gestione dei client collegati;
- terminal mode xterm.js con protocollo di resize completo;
- adapter opzionali specifici dell'agente per mostrare lo stato fuori dal
  terminale, mantenendo agent-agnostic il core.

Prima dell'implementazione vanno definiti comportamento multi-pane,
interazione con client tmux già collegati e semantica di ripristino. La
soluzione dovrebbe confluire nel lavoro M1 su pane selection/resize o nel
terminal mode previsto in M3.

## INC-AS-01 — falso stato “in elaborazione” su sessione inattiva

**Stato:** risolto il 05/08/2026 alle 01:05 Europe/Rome, quarto round dopo tre
checkpoint di concorrenza consecutivi — vedi "Checkpoint 05/08/2026 01:05" e
"Remediation" sotto.

### Checkpoint 04/08/2026 17:06 Europe/Rome — round non eseguito, gate di concorrenza

Il round del wakeup `cdf9abd2` (dovuto 17:05) si è fermato subito dopo la
verifica di concorrenza, senza toccare codice, senza deploy e senza commit,
come prescrive il "Confine del prossimo round" sopra. Evidenza raccolta:

- `git status`/`git diff` nel working tree mostravano modifiche non
  committate a `frontend/src/App.tsx` e `frontend/src/api.ts`, più
  `frontend/src/i18n.ts` non tracciato (layer i18n it/en + logout, non
  correlato a OpenCode). `App.tsx` contiene però `AGENT_STATE_LEGEND`
  (rinominata in `getAgentStateLegend()` nel diff in corso), cioè la
  legenda UI degli stessi stati che il classificatore backend produce —
  area adiacente a quella che la remediation di INC-AS-01 deve toccare sul
  lato frontend.
- `ps aux` mostra un processo `claude` interattivo (pid 443964, pts/5,
  avviato Sun Aug 2 11:24:27 2026, elapsed 2-05:41+) con `cwd` risolto su
  `<repo>` (`/proc/443964/cwd`), quindi
  una sessione live nello stesso repository, non un round wakeup di questo
  meccanismo.
- `stat` sui tre file mostra mtime alle 16:30:59 (`App.tsx`), 15:30:02
  (`api.ts`) e 15:56:26 (`i18n.ts`) del 04/08/2026 — cioè scritture avvenute
  30-40 minuti prima dell'avvio di questo round (17:05), coerenti con quel
  processo ancora attivo.
- In `<home>/projects/<orchestratore>/wakeups.jsonl`, il wakeup `c7b74d4d`
  (dovuto 03/08 17:05) aveva già segnalato working tree condiviso proprio
  su `api.ts`/`App.tsx` (allora per la promozione di Antigravity); il
  contenuto attuale del diff è diverso (i18n/logout) ma il pattern —
  un'altra sessione viva che scrive sugli stessi file di frontend — si
  ripete. Nessun wakeup con provider `opencode` risulta in `wakeups.jsonl`;
  il riferimento del prompt a "wakeup OpenCode del 03/08" corrisponde ai
  round con provider `claude`/`codex` della notte 02→03/08 (`66557dc2`,
  `4a9797f3`, `a42366b9`) più la sessione interattiva su OpenCode
  documentata in `docs/roadmap.md`/IMP-OC-01 — nessuno di questi risultava
  attivo; il blocco è dovuto esclusivamente al processo interattivo
  443964.

Decisione: non implementare, non deployare, non committare in questo round.
La sola modifica di questo round è questo checkpoint in `docs/backlog.md`.

Riproduzione del gate (da rieseguire al prossimo wakeup prima di qualunque
altra azione):

```bash
ps -o pid,lstart,etime,cmd -p 443964   # se ancora vivo, richiedere all'utente se il pid è cambiato
ls -la /proc/<pid>/cwd                  # deve NON risolvere su questo repo
git -C <repo> status
git -C <repo> diff -- frontend/src/App.tsx frontend/src/api.ts
```

Se il processo interattivo non è più attivo e `git status` è pulito (o le
modifiche residue non toccano `AGENT_STATE_LEGEND`/`AgentStatusService`/file
del classificatore), procedere con l'analisi strutturata e la remediation
come da "Confine del prossimo round". Prossimo wakeup programmato con:

```bash
cd <home>/projects/<orchestratore> && python3 add-wakeup.py \
  --at 2026-08-04T21:05 \
  --workdir <repo> \
  --provider claude --permission-mode bypassPermissions \
  --note "INC-AS-01: terza ripresa dopo due checkpoint di concorrenza" \
  --prompt "Riprendi INC-AS-01 in docs/backlog.md, sezione 'Checkpoint 04/08/2026 17:06'. Riesegui il gate di concorrenza descritto lì (processo pid 443964 potrebbe essere terminato: verifica se esiste ancora e se il suo cwd risolve su questo repo) prima di qualunque altra azione. Se libero, procedi con l'analisi strutturata e la remediation completa di INC-AS-01 come da 'Confine del prossimo round'."
```

### Checkpoint 04/08/2026 21:05 Europe/Rome — round non eseguito, gate ancora bloccato

Wakeup `a4c9d8a7` (dovuto 21:05). Rieseguito il gate riprodotto sopra prima di
qualunque altra azione — risultato ancora bloccato, terza volta consecutiva
sullo stesso processo:

- `ps -o pid,lstart,etime,cmd -p 443964` → il processo esiste ancora:
  `claude`, avviato Sun Aug 2 11:24:27 2026, elapsed `2-09:40:51`.
- `/proc/443964/cwd` risolve ancora su
  `<repo>` — sessione interattiva live
  nello stesso repo, non terminata come ipotizzato dal prompt di ripresa.
- `git status`: modifiche non committate a `frontend/src/App.tsx` e
  `frontend/src/styles.css` (niente più `api.ts`/`i18n.ts` non tracciato:
  quel lavoro i18n è stato committato nel frattempo in `80af35f`/`5728e78`).
  Il diff residuo riguarda ancora l'area `agent-info-bar`/
  `getAgentStateLegend()`/`AGENT_STATE_ICON` (redesign del badge CTX e delle
  card dei rate limit) — stessa zona adiacente al classificatore segnalata
  nel checkpoint delle 17:06.
- `stat` sui due file mostra mtime **21:02:53** (`App.tsx`) e **21:02:55**
  (`styles.css`) del 04/08/2026, cioè circa 3 minuti prima dell'avvio di
  questo round (21:05): non è uno scarto residuo di ore prima, il processo
  443964 sta scrivendo attivamente proprio ora.

Decisione: non implementare, non deployare, non committare in questo round.
La sola modifica è questo checkpoint.

Nota per il prossimo round: il pid non è cambiato per tre checkpoint di
fila (17:06 e 21:05 di oggi, più il precedente del 03/08 sullo stesso
pattern con `c7b74d4d`) e resta attivo con mtime freschi ad ogni verifica —
non sembra uno scarto morto da ripulire, ma una sessione interattiva
dell'utente tuttora in corso sugli stessi file. Continuare a riprogrammare
meccanicamente ogni 4h rischia di ripetere lo stesso esito senza avvicinare
la remediation; se al prossimo giro il pid è ancora vivo con mtime altrettanto
recenti, vale la pena segnalarlo esplicitamente all'utente invece di limitarsi
a un quarto checkpoint silenzioso.

Riproduzione del gate (invariata, da rieseguire al prossimo wakeup prima di
qualunque altra azione):

```bash
ps -o pid,lstart,etime,cmd -p 443964   # se ancora vivo, richiedere all'utente se il pid è cambiato
ls -la /proc/<pid>/cwd                  # deve NON risolvere su questo repo
git -C <repo> status
git -C <repo> diff -- frontend/src/App.tsx frontend/src/styles.css
```

Se il processo interattivo non è più attivo e `git status` è pulito (o le
modifiche residue non toccano `AGENT_STATE_LEGEND`/`getAgentStateLegend`/
`AgentStatusService`/file del classificatore), procedere con l'analisi
strutturata e la remediation come da "Confine del prossimo round". Prossimo
wakeup programmato con:

```bash
cd <home>/projects/<orchestratore> && python3 add-wakeup.py \
  --at 2026-08-05T01:05 \
  --workdir <repo> \
  --provider claude --permission-mode bypassPermissions \
  --note "INC-AS-01: quarta ripresa dopo tre checkpoint di concorrenza sullo stesso pid 443964" \
  --prompt "Riprendi INC-AS-01 in docs/backlog.md, sezione 'Checkpoint 04/08/2026 21:05'. Riesegui il gate di concorrenza descritto lì (pid 443964, attivo per tre checkpoint di fila con mtime freschi ad ogni verifica: se ancora vivo con lo stesso pattern, segnalalo esplicitamente all'utente invece di riprogrammare in silenzio) prima di qualunque altra azione. Se libero, procedi con l'analisi strutturata e la remediation completa di INC-AS-01 come da 'Confine del prossimo round'."
```

### Checkpoint 05/08/2026 01:05 Europe/Rome — gate valutato libero, pattern interrotto

Wakeup dovuto 01:05. Rieseguito il gate riprodotto sopra prima di qualunque
altra azione — quarta verifica consecutiva sullo stesso `pid 443964`, ma con
esito diverso dalle tre precedenti:

- `ps -o pid,lstart,etime,cmd -p 443964` → il processo esiste ancora (`claude`,
  avviato Sun Aug 2 11:24:27 2026, elapsed `2-13:40:56`): quarta rilevazione
  di fila con lo stesso pid, quindi lo segnalo esplicitamente all'utente
  invece di riprogrammare in silenzio, come richiesto dal prompt di questo
  round.
- A differenza dei tre checkpoint precedenti, però, **`git status` è
  risultato pulito**: nessun diff residuo su `App.tsx`/`styles.css`/altri
  file. I commit più recenti fatti da quel processo (`70206e2`, `30efabf`,
  `39e14cc`) riguardano il redesign della vista Host
  (`container_policies`) — area disgiunta dal classificatore
  (`agent_status_service.py` non toccato) e da `getAgentStateLegend`
  (un solo hunk in `App.tsx` la tocca, ma per un re-indent, non per
  contenuto).
- `stat` sui file coinvolti in quei commit mostra l'ultima scrittura alle
  00:16 del 04/08/2026, cioè circa 49 minuti prima di questo round (01:05):
  a differenza del checkpoint delle 21:05 (mtime a 3 minuti dall'avvio del
  round), qui non c'è scrittura "a caldo" in corso. `/proc/443964/fd` non
  mostra alcun file aperto nel repo e lo stato del processo è `S`
  (sleeping), coerente con una sessione interattiva ferma su un prompt.

Valutazione: il pattern dei tre checkpoint precedenti (vivo + mtime
freschissimi ad ogni verifica + diff sovrapposto non committato) richiedeva
di non procedere; qui manca la condizione che contava davvero — nessuna
modifica sovrapposta pendente sui file del classificatore o dell'area
`AGENT_STATE_LEGEND`/`getAgentStateLegend`/`AgentStatusService`. Gate
valutato **libero**: procedo con l'analisi strutturata e la remediation
completa di "Confine del prossimo round". Verificato a fine round che il
processo 443964 e tutte le sessioni tmux (`Mac`, `Deploy`, `MacHost`,
`basole`, `wakeups`) fossero ancora vive dopo il deploy di `backend`/`web`.

### Remediation (05/08/2026)

Analisi strutturata di `AgentStatusService.classify()`
(`backend/app/services/agent_status_service.py`): la causa non era il
pattern `\bworking\b` in sé, ma il fatto che `ACTIVE_PATTERNS` venisse
verificato sulle ultime 20 righe non vuote (`tail`) **senza alcun rapporto
con la posizione del prompt**. Un prompt inattivo (`❯`/`>`/`›`) è il segnale
più recente disponibile in un frame `capture-pane`: se compare, qualunque
marker attivo trovato solo *prima* di esso (prosa narrativa reale o chrome
di un turno già concluso rimasto nello scroll) è per definizione superato,
non attuale.

Fix: quando `prompt_index` è definito, `ACTIVE_PATTERNS` è ora verificato
solo sulle righe **successive** al prompt (`recent_lines[prompt_index + 1:]`)
— cioè più recenti di esso — non sull'intero `tail`. Se non c'è alcun
contenuto dopo il prompt, lo stato è `idle` indipendentemente dalle parole
presenti nella prosa precedente. Senza prompt visibile il comportamento è
invariato (matching su tutto il `tail`, poi euristica di cambio digest).
L'ordine di verifica per `waiting_authorization` e `waiting_input` non è
cambiato: entrambi restano gating come prima (autorizzazione su tutto il
`tail`, feedback solo nelle righe immediatamente precedenti al prompt), quindi
nessuna regressione sui due flussi. Per Antigravity (`ACTIVE_PATTERNS` vuoto)
il nuovo ramo non trova mai un match dopo il prompt: la "guardia prompt-first"
già usata per la sua euristica di cambio contenuto è ora applicata a tutti i
provider, non solo ad Antigravity.

Copertura di test aggiunta in `backend/tests/test_agent_status_service.py`
(324 test totali, tutti verdi, più `ruff check .`, eseguiti via
`docker compose run --rm backend-test`):

- regressione sul caso reale riportato in "Evidenza e impatto" (`"lavora
  nello stesso working tree"` seguito da `❯` inattivo → `idle`, non più
  `active`);
- falsi positivi narrativi per ognuna delle parole di `ACTIVE_PATTERNS`
  (`thinking`, `tool use`, `esc to interrupt` per Claude; `reasoning`,
  `working`, `esc to interrupt` per Codex) usate in frasi di prosa ordinaria
  seguite da prompt inattivo;
- controllo di non regressione simmetrico: marker attivo reale (`✻
  Thinking… (esc to interrupt · 12s)`) senza alcun prompt visibile → resta
  `active` per Claude e Codex;
- marker storico (turno precedente) seguito da prompt e nessun contenuto
  successivo → `idle`;
- marker che compare *dopo* un prompt più vecchio (nuovo comando avviato
  subito dopo, chrome più recente del prompt) → resta `active`, a conferma
  che la scoping per posizione non introduce falsi negativi sul caso
  realmente attivo;
- precedenza esplicita: una domanda reale (`waiting_input`) prevale su una
  parola "attiva" comparsa nella stessa frase prima del prompt;
- guardia prompt-first per Antigravity: prompt presente e contenuto che
  cambia → resta `idle`; nessun prompt e contenuto che cambia → `active`
  tramite l'euristica di digest esistente, invariata.

Non sono state trovate né usate nuove fixture di frame reali sull'host per
Claude/Codex: la frase riportata in "Evidenza e impatto" è già un frame reale
minimizzato (l'unico dato variabile, il percorso di progetto, non è
presente), quindi è stata riusata direttamente come regressione invece di
catturarne una nuova.

Nessuna modifica lato frontend alla logica di stato: `AGENT_STATE_LEGEND`/
`AGENT_STATE_ICON` mostrano solo le etichette degli stati esistenti,
prodotti esclusivamente dal backend; nessun nuovo stato introdotto. Aggiornato
solo `LATEST_RELEASE` in `frontend/src/App.tsx` (titolo "Stato agente più
affidabile") per riflettere il fix nel pannello "What's new", come richiesto
da `AGENTS.md` alla chiusura di un round funzionale.

Deploy: `docker compose build backend web` seguito da
`docker compose up -d --no-deps backend web` — solo i due servizi stateless,
`tmux-runtime`/socket tmux host non toccato. Verificato dopo il deploy:
`GET /api/v1/config` risponde `401` (backend su, auth applicata) sia su
`https://<ip-tailscale>:8081` sia su `https://<host>.<tailnet>.ts.net:8081`;
il bundle JS pubblicato contiene la nuova stringa di `LATEST_RELEASE`
(verificato con `grep` dentro il container `web`); tutte le sessioni tmux
preesistenti (incluso `pid 443964`/sessione `Mac`) sono rimaste vive dopo il
riavvio.

Commit: un solo commit focalizzato su
`backend/app/services/agent_status_service.py`,
`backend/tests/test_agent_status_service.py` e `frontend/src/App.tsx`
(`git diff --stat` verificato prima di committare: nessun file OpenCode,
Antigravity o Host incluso).

### Evidenza e impatto

La sessione Claude `Mac` mostrava da oltre venti minuti l'icona animata
“In elaborazione”, pur essendo ferma sul prompt finale `❯` dopo
`Cooked for 16m 47s`. Il pane tmux reale non aveva attività in corso. Il
frontend non conservava uno stato client obsoleto: il polling di
`GET /api/v1/agent-statuses` avviene ogni tre secondi e il backend
riclassificava deterministicamente il frame come `active`.

La risposta conclusiva visibile nel pane conteneva la frase ordinaria
“working tree”. `AgentStatusService` cerca invece `\bworking\b` nelle ultime
venti righe sia per Claude sia per Codex e valuta i pattern attivi prima del
prompt inattivo. Una riproduzione minima contro il codice effettivamente
deployato ha restituito `state='active'`, `detail='Elaborazione in corso'` per:

```text
Una cosa da sapere: lavora nello stesso working tree.
❯
```

La causa immediata è quindi un falso positivo lessicale, non tmux, il polling
frontend o la finestra temporale di attività. Lo stesso difetto può emergere
con parole comuni come `thinking`, `reasoning` e `tool use`, oppure con chrome
TUI storico rimasto nel frame. I test correnti coprono un prompt inattivo
semplice e un marker attivo sintetico, ma non testo narrativo contenente le
parole chiave né la precedenza temporale fra marker e prompt.

### Confine del prossimo round

Non applicare una sostituzione puntuale di `working`: analizzare prima in modo
strutturato tutte le sorgenti del segnale (`ACTIVE_PATTERNS`, prompt,
autorizzazioni, richieste di feedback, digest/cambio contenuto, alternate
screen) per Claude, Codex e gli agenti aggiunti nel frattempo. Usare fixture
realistiche e catture minimizzate, senza inserire output privato nei file
versionati. Definire esplicitamente precedenza e recenza dei segnali; i marker
UI devono essere riconosciuti per struttura/posizione, non come parole libere
nella prosa.

La remediation deve includere almeno:

- regressione per il caso reale `working tree` seguito da prompt inattivo;
- falsi positivi narrativi per tutti i marker generici e per entrambi i
  provider storici;
- marker attivo reale, marker storico seguito da prompt e output che cambia
  senza prompt;
- verifica dei flussi `waiting_input` e `waiting_authorization`, che non devono
  regredire;
- prova contro frame reali minimizzati disponibili sull'host e suite completa;
- deploy dei soli servizi stateless coinvolti, preservando `tmux-runtime`,
  test sull'istanza pubblicata e aggiornamento di `LATEST_RELEASE` nello stesso
  round funzionale;
- commit focalizzato, senza inglobare modifiche OpenCode/Antigravity o altro
  lavoro preesistente.

Gate di concorrenza: all'avvio ricostruire lo stato reale con wakeup attivi,
`git status`, diff e log. Se il round OpenCode è ancora in esecuzione o ci sono
modifiche sovrapposte nei file del classificatore, non implementare e non
deployare; lasciare un checkpoint riproducibile e riprogrammare il lavoro in
una finestra libera.

## Drift dello scroll in pausa e storico delle app a schermo alternato

**Stato:** parzialmente risolta. La cronologia Claude è disponibile tramite
adapter opzionale validato; il limite resta per altre TUI fullscreen e il
drift dello scroll live è differito. Il terminal mode xterm.js (vista
Terminale) non risolve né peggiora questo punto: renderizza meglio i colori
ANSI, ma eredita lo stesso comportamento "reset del buffer a ogni snapshot"
perché il protocollo resta a snapshot autorevole, non byte-stream
incrementale (scelta deliberata, vedi `docs/architecture.md` sezione
Streaming). Lo scrollback delle app a schermo alternato resta comunque un
limite di `tmux capture-pane`, non risolvibile da nessuna libreria di
rendering frontend.

Bug osservato: con "autoscroll intelligente" in pausa (utente risalito
nell'output), il contenuto del pane continua comunque a essere sostituito
nel DOM ad ogni snapshot WebSocket. Poiché `capture-pane` restituisce una
finestra scorrevole delle ultime righe (non un log append-only), a parità di
`scrollTop` il testo mostrato slitta gradualmente verso le righe più recenti
mentre l'agente produce output — un piccolo "glitch" visivo, non un vero
salto in fondo.

Primo tentativo di fix: congelare il contenuto renderizzato mentre non si
segue l'output (bufferizzare gli snapshot in un ref e riapplicarli solo alla
ripresa). Elimina il drift, ma introduce un problema più serio per le
sessioni che eseguono programmi TUI a schermo alternato (vim, htop, Claude
Code CLI stesso): tmux non mantiene scrollback per lo schermo alternato,
quindi `capture-pane` può restituire al massimo l'altezza corrente del pane,
a prescindere da qualunque `lines` richiesto. Verificato empiricamente su
una sessione reale:

```
80x24 alt=1 history=0/2000
```

Prima del fix, il drift dava l'illusione di uno storico più ampio (ogni
snapshot rivelava contenuto leggermente diverso durante lo scroll, facendo
sembrare che ci fosse sempre "un po' di più" da trovare risalendo). Con il
contenuto congelato quel tetto reale (poche decine di righe) diventa
evidente e stabile, rendendo di fatto impossibile leggere output storico più
lungo di una schermata per queste sessioni — un regresso peggiore del
glitch che il fix risolveva. Commit revertito.

Possibili direzioni future, nessuna banale:

- compensazione precisa dello scroll invece del congelamento: diff tra
  contenuto precedente e nuovo per individuare quante righe sono state
  espulse dall'inizio della finestra, misurarne l'altezza renderizzata (il
  wrapping dipende dal font e dalla larghezza del pane) e traslare
  `scrollTop` di conseguenza — corregge il drift senza bloccare
  l'aggiornamento, ma è sensibile a wrapping/robustezza del diff;
- pane più alto per le sessioni TUI, con gli stessi trade-off di resize già
  discussi sopra (client collegati, layout multi-pane, reazione delle app
  fullscreen);
- accettare il drift residuo come limite noto e minore, documentandolo in
  UI (es. tooltip sul pulsante "Segui output").

Per Claude non tentare nuovamente di ricavare la cronologia da
`capture-pane`: ADR 007 definisce il collector normalizzato, il feature flag e
il fallback live. Il terminal mode xterm.js è stato implementato ma, come
previsto, non risolve lo scrollback delle app a schermo alternato (limite
tmux); la soluzione generica resta un adapter separato con le stesse
proprietà di isolamento, sul modello di ADR 007.

---

## Modulo di osservabilità dell'host

**Stato: implementato, deployato e validato in produzione (03/08/2026).** Da
`GATE-HO-00` a `TEST-HO-06` tutti i gate sono chiusi con esito positivo, il
contratto è alla v2 (`docs/contracts/host-observability-v2.md`) e la vista
Host è pubblicata. Restano aperti soltanto i follow-up in "Anomalie e
follow-up da validare" (`HO-FU-01`, `VALIDATED_WITH_CHANGES`).

Il testo che segue è la **discussione originale che ha aperto il modulo**,
conservata come motivazione delle scelte: descrive lo stato di allora, non
quello di oggi. Discusso il 30/07/2026, nato da un
incidente reale: nove dev server Astro lasciati vivi da riavvii ripetuti,
~258 MB l'uno, 2,3 GB su una macchina da 3,7. Nessuno se n'è accorto finché
la RAM non è andata in sofferenza.

L'idea è aggiungere a MAC una vista sullo stato dell'host invece di far
partire l'ennesimo servizio dedicato. Prima di scrivere codice vanno chiuse
tre questioni, e la prima non è quella che sembra.

### 1. Il repo pubblico non è il rischio che sembra

MAC è già un accesso shell remoto: crea sessioni, manda input, termina
processi, dal telefono. Il raggio d'azione pericoloso esiste già, e un modulo
di osservabilità non lo allarga in modo sostanziale.

**Il problema non è il codice pubblico, è la configurazione.** Nel repo non
devono entrare: inventario degli host, nomi dei servizi, mappa delle porte,
soglie legate all'infrastruttura reale, credenziali. Il modulo legge *cosa*
sorvegliare da configurazione e non lo sa per conto suo.

Il codice che dice «leggi la memoria disponibile» è banale e pubblicabile. Il
file che descrive servizi e porte di un host reale è una mappa
per chi volesse provarci. Nel repo va solo l'esempio con valori finti.

### 2. Non costruirlo attorno a Docker

Trappola concreta, perché è la direzione naturale: i comandi già messi nel
bashrc sono su Docker, ma **l'incidente del 30/07 non riguardava Docker**.
Erano processi node nudi, fuori da qualunque container. Una dashboard centrata
sui container non avrebbe mostrato nulla, e mancherebbe il prossimo incidente
allo stesso modo.

Il livello giusto è il processo e la memoria, con i container come una delle
viste e non come l'impianto.

### 3. Istantanea o tendenze: decide la forma, e il costo

MAC è costruito attorno alla sessione terminale con il suo flusso di output.
Il monitoraggio è un'altra forma, dati strutturati campionati nel tempo.

- **Tendenze** → serve un campionatore che gira e una memoria dove scrivere.
  A quel punto il servizio nuovo lo hai fatto partire comunque, che è
  esattamente ciò che si voleva evitare.
- **Stato adesso** → una chiamata su richiesta che restituisce un'istantanea.
  Niente campionamento, niente base dati, niente processo aggiuntivo.

**Raccomandazione: partire dall'istantanea.** Copre la gran parte del bisogno,
e dopo qualche settimana d'uso si sa quali metriche vale la pena conservare
invece di indovinarlo adesso.

### Contenuto minimo della schermata

Deve rispondere a una domanda sola: *c'è qualcosa che non va in questo
momento?*

- memoria disponibile e swap;
- primi dieci processi per RSS, con età del processo (avrebbe fatto vedere i
  nove Astro dev in un colpo d'occhio);
- porte in ascolto, con evidenza di quelle non attese (un dev server che
  slitta di porta in porta è il sintomo);
- container non sani;
- spazio disco;
- carico.

### Vincoli da rispettare

- La postura di sicurezza della VPS è documentata in
  `handbooks/vps-security.md` del workspace di crescita professionale:
  port binding su `BIND_HOST` e mai `0.0.0.0`, firewall solo inbound. Qualsiasi
  endpoint nuovo la rispetta.
- Azioni distruttive (kill, restart) vanno trattate diversamente dalla sola
  lettura: la lettura può stare dietro l'autenticazione esistente, l'azione
  merita una conferma esplicita come già avviene per interrupt e terminazione
  di sessione.

### Prossimo passo

Far passare l'idea dalla skill `valida-progetto` del workspace di crescita
professionale, prima di scrivere codice: verifica fit col posizionamento,
rischio di dispersione e valenza dual-use. Il dual-use qui c'è (MAC è già nel
portfolio, e un modulo di osservabilità è materiale spendibile in colloquio da
IT Manager), ma la validazione va fatta prima e non dopo.

**Rimandato al 2 agosto 2026**, dopo il reset del budget mensile.

### Confini proposti per l'MVP

La prima versione resta deliberatamente più piccola di un sistema di
monitoraggio generico:

- singolo host Linux e sola lettura;
- istantanea esplicitamente richiesta dall'amministratore, senza polling,
  serie temporali, database, grafici, alert o notifiche;
- collector host-side non-root, avviato on demand tramite socket Unix e
  socket activation systemd;
- nessun mount di `/proc`, `/sys` o del socket Docker nel backend;
- memoria, swap, carico, filesystem configurati, top processi per RSS,
  aggregazione dei processi omonimi, listener TCP e container problematici;
- componenti indipendenti con stato `ok`, `warning`, `critical` o `unknown`:
  Docker assente o non accessibile non rende indisponibili le altre metriche;
- niente command line completa, environment, working directory, username,
  hostname, IP grezzi, container ID, image name o errori `stderr` nell'API;
- configurazione reale, inventario, label, porte attese e soglie soltanto
  nell'environment/file privato host-side; nel repo solo un esempio fittizio;
- nessuna azione `kill`/restart: un eventuale modulo mutativo richiederà una
  decisione, un threat model e una roadmap separati.

Il canale raccomandato è:

```text
UI admin -> GET backend -> socket Unix privato -> systemd socket activation
                                                -> collector one-shot
                                                -> JSON minimizzato e validato
```

Montare direttamente le viste host nel backend o il socket Docker è escluso.
Un timer periodico resta un fallback soltanto se lo spike dimostra che il
socket Unix non può funzionare in modo sicuro in entrambe le modalità di
deployment; adottarlo richiede aggiornare esplicitamente questa decisione.

### Protocollo della roadmap per i subagent

Questa sezione è la coda di lavoro autorevole. I nomi logici degli esecutori
sono `ROOT`, `SA-IMP` (implementazione) e `SA-TEST` (verifica indipendente).

- `[ ]` indica una voce ancora aperta; `[x]` un tentativo chiuso. L'esito vero
  è sempre il campo `STATUS`, non il solo checkbox.
- **Verifica su dati reali (vincolante).** Ogni voce di implementazione che
  tocca un collector o un parser deve essere eseguita almeno una volta contro
  dati reali (non solo fixture sintetiche), con ispezione diretta
  dell'aggregato prodotto; l'esito di quella ispezione va riportato per
  esteso nella voce, non solo il fatto di averla eseguita. I test sintetici da
  soli non bastano a fidarsi di un collector: il 02/08/2026 la suite era verde
  mentre il collector Codex sommava `cached_input_tokens` a `input_tokens`
  come se fossero bucket disgiunti (come accade in Claude), mentre in Codex
  `cached_input_tokens` è un sottoinsieme di `input_tokens` — l'errore si
  ripeteva a ogni turno insieme al contesto in cache, arrivando a contare il
  consumo reale circa sessanta volte in eccesso su una sessione lunga. Nessuna
  fixture sintetica rifletteva quella relazione fra i due contatori, quindi
  nessun test l'aveva notata prima dell'ispezione manuale sull'aggregato
  reale.
- `SA-IMP` può prendere soltanto la prima voce con `OWNER: SA-IMP` e
  `STATUS: READY` o `STATUS: REWORK_REQUIRED`, portandola prima a
  `IN_PROGRESS`.
- Ogni voce di implementazione include anche test automatici proporzionati al
  rischio e aggiorna il gate manuale in `docs/gates/host-observability.md`.
  Non è pronta per la consegna con test mancanti o non passanti.
- Quando `SA-IMP` conclude, chiude la propria voce con `STATUS: DONE` e porta
  il corrispondente check `SA-TEST` da `BLOCKED` a `READY_FOR_TEST`, indicando
  commit/working tree, test aggiunti, comandi da eseguire e criteri manuali.
- **`SA-TEST` non è saltabile (vincolante).** Nessuna voce di implementazione
  è considerata chiusa, e nessuna fase successiva passa da `BLOCKED` a
  `READY`, finché il corrispondente tentativo `SA-TEST` non è a sua volta
  chiuso con `STATUS: PASSED`. Un `STATUS: DONE` di `SA-IMP`, da solo, non
  sblocca nulla — indipendentemente da quanto sia stata estesa la batteria di
  test che l'implementatore ha già eseguito. Il 02/08/2026 due test API a
  tempo fisso (commit `ce507d1`) erano verdi il giorno stesso in cui sono
  stati scritti e sarebbero falliti da soli entro breve, perché fissavano
  l'istante del campione dentro una finestra scorrevole che si sposta col
  tempo; nella stessa giornata `SA-TEST`, verificando in modo indipendente
  un'implementazione che l'autore aveva già sottoposto a una batteria
  adversariale propria, ha comunque trovato due difetti veri che
  l'implementatore non aveva visto. La verifica indipendente scopre classi di
  difetto diverse da quella di chi ha scritto il codice: non è un doppione
  saltabile quando "i test passano già".
- **Scansione dei dati personali prima del commit (vincolante).** Ogni voce che
  produce commit destinati a essere pubblicati verifica il proprio diff — righe
  aggiunte, file nuovi compresi — contro: percorsi assoluti di questa macchina,
  username, hostname e indirizzi Tailscale/IP, token e segreti, nomi di
  progetti privati. L'esito va riportato nella voce come qualunque altro
  controllo: "nessuna occorrenza" è un risultato da dichiarare, non da dare per
  scontato. Questo repository è pubblico e `CLAUDE.md` vieta esplicitamente
  quei dettagli nei file versionati. Il 03/08/2026 un round notturno ha scritto
  in `docs/backlog.md` il percorso reale del file storico delle quote,
  rivelando username e struttura delle directory; è stato corretto in avanti,
  ma è rimasto nella storia e ha richiesto una riscrittura con
  `git filter-repo` prima di poter pubblicare. Non era distrazione di
  qualcuno: **nessun round aveva quel compito**. Nei giorni precedenti il
  controllo era avvenuto solo come effetto collaterale del fatto che a premere
  il pulsante fosse una persona. Una verifica che dipende da chi si ricorda di
  farla non è una verifica. Comando di riferimento — da adattare, non da
  fidarsene ciecamente:

  ```bash
  git diff origin/main..HEAD | grep -nEi "^\+.*(/home/|[0-9]{1,3}(\.[0-9]{1,3}){3}|\.ts\.net|sk-[a-z]+-)"
  ```

- `SA-TEST` non corregge l'implementazione. Esegue i test indicati e controlli
  indipendenti, poi chiude il proprio tentativo con `STATUS: PASSED` oppure
  `STATUS: FAILED` e una motivazione riproducibile.
- In caso di `FAILED`, `SA-TEST` conserva il tentativo fallito e aggiunge subito
  sotto di esso una nuova voce aperta `OWNER: SA-IMP`,
  `STATUS: REWORK_REQUIRED`, con suffisso `-R1` (poi `-R2`, ecc.), riferimento
  al test fallito, risultato atteso, risultato ottenuto e comando di
  riproduzione.
- Terminato il rework, `SA-IMP` chiude la voce `-R<n>` con `STATUS: DONE`,
  aggiunge il test automatico di regressione o spiega perché il controllo è
  necessariamente manuale, e crea un **nuovo** check `SA-TEST` con suffisso
  `-T<n+1>` e `STATUS: READY_FOR_TEST`. I tentativi precedenti non vengono
  riaperti né riscritti.
- Una fase successiva passa da `BLOCKED` a `READY` soltanto dopo `PASSED` del
  gate precedente. `ROOT` coordina queste transizioni e interrompe il round se
  emerge una modifica al threat model o allo scope approvato.
- Nessun agent deve modificare o includere nel commit le modifiche preesistenti
  e non pertinenti presenti nel working tree.

Esempio del ciclo di rework:

```text
- [x] TEST-HO-02-T1 | OWNER: SA-TEST | STATUS: FAILED | ...
- [ ] IMP-HO-02-R1  | OWNER: SA-IMP  | STATUS: REWORK_REQUIRED | ...
# dopo la correzione
- [x] IMP-HO-02-R1  | OWNER: SA-IMP  | STATUS: DONE | ...
- [ ] TEST-HO-02-T2 | OWNER: SA-TEST | STATUS: READY_FOR_TEST | ...
```

### Roadmap flaggabile

#### HO-00 — Gate prodotto e decisioni

- [x] GATE-HO-00 | OWNER: ROOT | STATUS: PASSED | Piano e confini MVP
  approvati dall'utente il 01/08/2026. Fit: estensione operativa coerente con
  MAC; rischio di dispersione contenuto dai confini read-only, single-host e
  senza serie storiche; valore dual-use confermato. `IMP-HO-01` attivato.

#### HO-01 — Spike del boundary host

- [x] IMP-HO-01 | OWNER: SA-IMP | STATUS: DONE | ADR 009, collector statico
  one-shot, user socket unit `Accept=yes`, overlay Compose condiviso fra le due
  modalità, client backend con timeout/limite/JSON envelope e configurazioni
  validati. Test automatici in
  `backend/tests/test_host_observability_socket_client.py` (9 passed); lint
  mirato, frontend build, Compose base e overlay Docker/host validi. Gate e
  comandi manuali in `docs/gates/host-observability.md`. La suite backend
  completa ha 149 passed e un fallimento infrastrutturale non pertinente:
  l'immagine `backend-test` non contiene il preesistente
  `/deploy/rate-limit-collector.py` richiesto da un test.
- [x] TEST-HO-01-T1 | OWNER: SA-TEST | STATUS: FAILED | I 9 test mirati,
  frontend build, Compose base, verifica statica delle unit systemd, lint dei
  soli file HO-01 e `git diff --check` passano; configurazioni Docker e host
  preservano isolamento, mount read-only e assenza di listener TCP. Falliscono
  però due criteri vincolanti. Il client usa una singola `reader.read()` e
  accetta `{'status': 'ok'}` se il server invia prima quel JSON e, dopo 100 ms,
  altri 2048 byte oltre il limite di 1024. Inoltre sull'host di test Docker è
  rootless: il backend Docker `10001:10001`, pur mostrando il GID supplementare
  configurato, riceve `PermissionError` attraversando la directory socket
  `0750`; lo stesso handshake in modalità host-tmux (`0:0` mappato all'utente
  host) riesce. Riproduzione: eseguire un server Unix che fa
  `write(b'{"status":"ok"}'); drain(); sleep(.1); write(b'x'*2048)` e poi
  `HostObservabilitySocketClient(path, max_response_bytes=1024).fetch()`;
  restituisce il dizionario invece dell'errore di limite. Per il secondo caso,
  eseguire il check "Modalità Docker tmux" di
  `docs/gates/host-observability.md` su Docker rootless: il connect fallisce
  con `[Errno 13] Permission denied`, come previsto dal negative check del
  gate. La suite completa resta a 149 passed e un failure preesistente per
  `/deploy/rate-limit-collector.py`; il lint globale mostra due ordinamenti
  import preesistenti e il comando documentato necessita `--no-cache` sul
  filesystem read-only. HO-02 resta bloccata.
- [x] IMP-HO-01-R1 | OWNER: SA-IMP | STATUS: DONE | Ripreso
  `TEST-HO-01-T1`: il client legge ora fino a EOF nello stesso timeout e rifiuta
  immediatamente il byte `max+1`, incluso quando arriva dopo un prefisso JSON
  valido; aggiunto test deterministico (10 test client passati). Una nuova unit
  preparatoria applica ACL POSIX nominali, revocando quelle stale, all'UID host
  `10001` rootful e all'eventuale UID mappato rootless/userns; directory `0750`,
  socket `0660`, `group::---`, backend non-root e mount read-only invariati.
  Aggiunti 3 unit test dello script runtime; connect reale riuscito sull'host
  rootless con UID container `10001` mappato, senza `group_add`. Lint mirato con
  `--no-cache`, unit systemd, Compose Docker/host, frontend build e
  `git diff --check` passano. Gate, ADR, architettura, sicurezza ed environment
  example aggiornati.
- [x] TEST-HO-01-T2 | OWNER: SA-TEST | STATUS: FAILED | I due blocker di T1
  sono risolti: un prefisso JSON seguito dopo 50 ms da 2048 byte viene rifiutato
  al byte oltre limite, un prefisso valido senza EOF termina con il timeout
  unico, e i 10 test client passano. Sul Docker rootless reale il probe mappa
  `10001` nell'UID host rilevato dal probe; ACL directory/socket nominali consentono il
  connect al backend non-root `10001:10001`, senza `group_add`, e il percorso
  host-tmux `0:0` riesce. Rimuovere l'ACL mappata produce `PermissionError`;
  rieseguire la preparazione e ricreare il socket ripristina l'accesso. Una ACL
  stale sintetica viene revocata, `group::---` resta effettivo, il mount è `ro`,
  non compaiono mount `/proc`, `/sys`, Docker socket, privilegi, capability,
  porte o route API. Passano inoltre 3 test runtime, lint mirati, frontend build,
  Compose Docker/host e `git diff --check`. Il gate fallisce però prima
  dell'attivazione reale: la nuova dipendenza della socket dalla service di
  preparazione introduce un ciclo tra `sockets.target`, la socket,
  `prepare.service` e `basic.target`; systemd elimina il job e non può avviare
  la socket. Riproduzione:
  `systemd-analyze --user verify deploy/systemd/mobile-agent-console-host-observability-prepare.service deploy/systemd/mobile-agent-console-host-observability.socket deploy/systemd/mobile-agent-console-host-observability@.service`
  termina con exit 1 e `Transaction order is cyclic`. HO-02 resta bloccata.
- [x] IMP-HO-01-R2 | OWNER: SA-IMP | STATUS: DONE | Ripreso
  `TEST-HO-01-T2`: la prepare oneshot usa `DefaultDependencies=no`, quindi
  resta `Requires`/`After` della socket ma non acquisisce più
  `After=basic.target`; eliminato il ciclo con `sockets.target` preservando
  preparazione ACL prima del bind e fail-closed. Aggiunto test che esegue
  realmente `systemd-analyze --user verify` sul grafo e fallisce su diagnostica
  o exit del cycle (4 test deploy passati). Validata un'attivazione nel vero
  user manager: prepare/socket `active`, ACL attese, collector one-shot avviato
  al connect e JSON corretto; link e runtime temporanei rimossi dopo il test.
  La prepare evita soltanto il mount namespace filesystem, incompatibile con
  ACL di UID subordinati, e conserva identità user, `NoNewPrivileges`,
  restrizioni namespace/SUID/AF_UNIX, umask e memory hardening; collector e
  socket non cambiano. Passano inoltre i 10 test client T1, lint mirati,
  Compose base/Docker/host, verify user e `git diff --check`.
- [x] TEST-HO-01-T3 | OWNER: SA-TEST | STATUS: PASSED | Il grafo completo e
  il relativo unittest terminano con exit `0`, senza cicli. Le unit collegate
  temporaneamente al vero user manager confermano prepare `active/exited`
  prima della socket `active/listening`; directory e ACL esistono prima del
  bind. Un handshake e quattro connessioni concorrenti attivano collector
  one-shot distinti, restituiscono il JSON atteso e non lasciano processi o
  istanze attive. Un mapping invalido fa fallire la prepare e lascia socket e
  file inattivi; fermare la prepare ferma anche la socket. Passano nuovamente
  delayed tail oltre limite, timeout fino a EOF, ACL rootless per backend
  non-root `10001:10001`, percorso host-tmux `0:0`, revoca fail-closed, rimozione
  ACL stale e ripristino. Mount observer `ro`, nessun `group_add`, mount vietato,
  privilegio, capability, route API o listener TCP; hash TCP e insieme delle
  sessioni tmux restano invariati. Passano 10 test client, 4 test deploy,
  lint mirati, frontend build, Compose Docker/host e `git diff --check`. La
  prepare rinuncia soltanto al namespace filesystem necessario per operare
  sugli UID subordinati: resta user non privilegiata con `NoNewPrivileges`,
  `RestrictNamespaces`, `RestrictSUIDSGID`, solo `AF_UNIX`, umask `0077`,
  `LockPersonality` e `MemoryDenyWriteExecute`; collector e socket conservano
  l'hardening precedente. Link, variabile manager, runtime e cache temporanei
  rimossi al termine. HO-02 resta bloccata in attesa della transizione di ROOT.

#### HO-02 — Contratto, configurazione e collector

- [x] IMP-HO-02 | OWNER: SA-IMP | STATUS: DONE | Implementati contratto
  Pydantic v1 strict e collector Linux standard-library one-shot per
  memoria/swap, load normalizzato, filesystem label-only, top 10 RSS/età,
  massimo 20 gruppi, listener TCP con scope normalizzati e Docker opzionale.
  Config privata `0600`/owner-only, esempio fittizio, argv Docker fisso,
  `shell=False`, timeout 2 s, unit 5 s, output Docker 64 KiB e risposta 128 KiB;
  nessuna API HO-03. Passano 12 test collector (inclusa l'aggregazione RSS
  calcolata come somma dei valori della fixture, `/proc` parziale, PID sparito/inaccessibile,
  cap listener, Docker assente/permessi/timeout/output e privacy), 7 contratto,
  10 client e 5 runtime/systemd; lint mirati e verify user passano. Boundary
  reale validato da backend rootless non-root su mount read-only: payload v1
  Pydantic valido, liste entro i limiti e privacy rispettata; artefatti temporanei
  rimossi. Suite completa: 157 passed e il solo failure infrastrutturale già
  noto per `/deploy/rate-limit-collector.py` assente dall'immagine test.
- [x] TEST-HO-02-T1 | OWNER: SA-TEST | STATUS: FAILED | Passano i 17 pytest,
  i 17 unittest collector/runtime/systemd, verify, lint, build, Compose e
  `git diff --check`. La fixture indipendente conferma i cap di processi,
  gruppi e listener, l'aggregazione RSS tramite formula, memoria/swap/load,
  soglie, argv Docker fisso con `shell=False`, errori Docker isolati e assenza
  strutturale dei campi vietati. Il collector socket-activated reale produce
  un payload entro cap, valido come v1 sia dal backend rootless non-root
  `10001:10001` sia da host-tmux `0:0`; stato TCP e insieme delle sessioni tmux
  restano invariati e gli
  artefatti temporanei sono rimossi. Falliscono però casi vincolanti. Il
  contratto non è strict: `duration_ms="21"` viene convertito in `21` e
  `collected_at` accetta timestamp naive o non UTC. `load_config()` accetta
  file regolari `0400`/`0700` e un file raggiunto attraverso una directory
  symlink, anziché richiedere esattamente un path reale `0600`. Docker marca
  `ok/available` output malformati come `b"garbage-without-tab\n"`; inoltre
  `subprocess.run(..., stdout=PIPE)` applica il limite 64 KiB solo dopo aver
  bufferizzato tutto. Con il solo `/proc/net/tcp` leggibile e `tcp6` assente i
  listener risultano `ok`, e un indirizzo Tailscale IPv6
  `fd7a:115c:a1e0::/48` è classificato `other`. Infine `statvfs` con
  `available_bytes > total_bytes` risulta `ok` e le ragioni degli item
  filesystem warning/critical/unknown non risalgono al componente né
  all'envelope. Riproduzione tramite chiamate dirette a
  `HostObservabilitySnapshot.model_validate()`, `load_config()`,
  `read_docker()`, `read_listeners()`, `address_scope()` e
  `read_filesystems()` con i valori sopra. La suite completa resta a 157
  passed e un solo failure infrastrutturale preesistente per
  `/deploy/rate-limit-collector.py` assente. HO-03 resta bloccata.
- [x] IMP-HO-02-R1 | OWNER: SA-IMP | STATUS: DONE | Chiuso il rework T1:
  contratto Pydantic realmente non coercitivo e timestamp timezone-aware UTC;
  config aperta componente per componente con `O_NOFOLLOW`, leaf regolare con
  mode esatto `0600`/owner, lettura limitata dallo stesso fd e confronto
  race-aware dei metadati pre/post. Docker rifiuta record malformati e applica
  il limite 64 KiB durante lo streaming del subprocess, preservando argv fisso,
  `shell=False`, timeout e `stderr` scartato. `tcp`/`tcp6` assente o malformato
  produce `listeners_partial`, il prefisso IPv6 Tailscale è normalizzato e
  contatori `statvfs` incoerenti falliscono chiuso; stato e ragioni filesystem
  risalgono a componente ed envelope. Passano 10 test contratto, 20 pytest HO,
  16 collector e 21 unittest deploy complessivi, lint mirati, verify systemd,
  frontend build, Compose base/Docker/host e `git diff --check`. La suite
  completa ha 160 passati e conserva il solo failure infrastrutturale
  preesistente per `/deploy/rate-limit-collector.py` assente dall'immagine.
  Integrazione reale rootless non-root `10001:10001`: payload v1 strict valido,
  entro i cap configurati, con privacy e limite risposta verificati; unit,
  variabili manager, config, link e runtime temporanei rimossi. HO-03 resta
  bloccata.
- [x] TEST-HO-02-T2 | OWNER: SA-TEST | STATUS: FAILED | Tutti i blocker T1
  coperti dal rework risultano risolti: tipi numerici coercitivi e timestamp
  naive/non-UTC sono respinti; config exact `0600`, leaf e parent `O_NOFOLLOW`,
  lettura max+1 e confronto `fstat` pre/post falliscono chiusi anche nella race;
  Docker malformato è `unknown`, l'output eccessivo viene fermato a max+1;
  `tcp6` assente è partial, Tailscale IPv6 è normalizzato; `statvfs` incoerente
  e ragioni filesystem propagano correttamente. L'audit openat conferma
  traversal componente-per-componente con `dir_fd`, nessun reopening per path
  e metadati dello stesso fd, senza race evidente. Passano 20 pytest HO, 21
  unittest deploy, verify, lint, build, Compose, fixture nove `node`, cap e
  privacy. Il collector reale valida strict in Docker rootless `10001:10001` e
  host-tmux `0:0` con payload entro cap; stato TCP e insieme delle sessioni tmux restano invariati
  e il cleanup è completo. Restano però tre failure riproducibili.
  `collected_at=123` solleva un `TypeError` grezzo dal field validator invece di
  una `ValidationError` Pydantic. `run_bounded_process()` con producer
  `os.close(1); sleep(1)` e timeout `0.1` chiama `process.wait()` senza timeout
  all'EOF e ritorna dopo circa 1,025 s. Infine file `tcp` e `tcp6` vuoti
  producono `status=ok`; 1.001 righe identiche attese producono ancora `ok` con
  `truncated=true`, potendo occultare listener successivi. La suite completa
  conserva 160 passed e il solo failure preesistente per
  `/deploy/rate-limit-collector.py`. HO-03 resta bloccata.
- [x] IMP-HO-02-R2 | OWNER: SA-IMP | STATUS: DONE | Corretti i tre blocker T2.
  Il validator timestamp usa un errore Pydantic tipizzato per ogni input non
  datetime/stringa: anche `collected_at=123` restituisce `ValidationError`, mai
  `TypeError` grezzo. La deadline Docker copre ora il `wait()` dopo EOF; il test
  reale `os.close(1); sleep(1)` termina in timeout a 0,1 s, uccide e reapa il
  producer senza zombie. File TCP/TCP6 vuoti, header o righe significative
  invalide e il record 1.001 rendono la copertura `listeners_partial`, con
  `unknown` in assenza di severity maggiore e `truncated=true` oltre cap.
  Passano 11 test contratto, 21 pytest HO, 19 collector e 24 unittest deploy
  complessivi, lint mirati, verify systemd, frontend build, Compose
  base/Docker/host e `git diff --check`. La suite completa ha 161 passati e
  conserva il solo failure infrastrutturale preesistente per
  `/deploy/rate-limit-collector.py` assente. Integrazione reale rootless
  `10001:10001`: payload v1 strict valido e liste entro i cap,
  privacy/limite risposta verificati e one-shot reaped; unit, manager env,
  config, link e runtime temporanei rimossi. HO-03 resta bloccata.
- [x] TEST-HO-02-T3 | OWNER: SA-TEST | STATUS: PASSED | I fix R2 per contratto
  e subprocess sono confermati indipendentemente: interi, float, oggetti,
  liste, `None` e booleani in `collected_at` producono tutti una normale
  `ValidationError`; un producer che chiude stdout e resta vivo rispetta la
  deadline di 0,1 s, viene ucciso e reaped senza zombie. File TCP/TCP6 vuoti,
  header invalido, record invalido e 1.001 record producono
  `listeners_partial`, stato `unknown` e troncamento dove applicabile. Resta un
  rilievo è stato riesaminato da `ROOT`: quando entrambi i file contengono un
  header valido ma nessun record, la vista `/proc/net/tcp{,6}` è valida e
  completa e significa che non esistono socket TCP; `status=ok`, ragioni vuote
  e `truncated=false` sono quindi il risultato corretto. Trattarlo come
  `unknown` introdurrebbe un falso allarme sugli host senza listener e non è
  richiesto dal gate, che copre file vuoti, header/record malformati e
  scansioni troncate.
  Passano 21 pytest HO, 24 unittest deploy, lint mirati, verify systemd,
  frontend build e Compose base/Docker/host. La suite backend completa ha 161
  passati e conserva il solo failure infrastrutturale preesistente per
  `/deploy/rate-limit-collector.py` assente dall'immagine. L'integrazione socket
  reale valida strict e privacy sia rootless `10001:10001` sia host `0:0`, con
  quattro client concorrenti e payload entro cap; hash TCP e sessioni tmux sono
  invariati e il cleanup di unit, manager env, config, runtime e container
  temporaneo è completo. HO-02 è validata.
- [x] IMP-HO-02-R3 | OWNER: SA-IMP | STATUS: CANCELLED | Nessuna modifica al
  codice: `ROOT` ha respinto il presupposto del rework perché una tabella
  `/proc/net/tcp{,6}` con header valido e zero record rappresenta correttamente
  l'assenza di listener, non una raccolta parziale. `SA-IMP` è stato interrotto
  prima di introdurre il falso `unknown`.

#### HO-03 — Backend e autorizzazione

- [x] IMP-HO-03 | OWNER: SA-IMP | STATUS: DONE | Implementato il boundary API
  opt-in: flag default `false`, socket assoluta/normalizzata, timeout validato e
  limite hard 128 KiB. Il nuovo service valida integralmente
  `HostObservabilitySnapshot`; `GET /api/v1/host-observability` è admin-only,
  ha rate limit GET dedicato e restituisce codici stabili 429, 503 per
  unavailable/invalid e 504 per timeout senza dettagli grezzi. Viewer/operator
  ricevono 403 e il client config espone il flag soltanto agli admin, senza
  implementare UI HO-04. Payload escluso da log, audit, database e `/health`.
  Passano 26 test HO mirati e 86 test API/database ampliati, inclusi flag-off
  senza connect, 401/403/admin, partial valido, rate limit, timeout, socket
  assente, response/payload manipolati e assenza da log/audit/health; lint dei
  file HO, frontend build, Compose base/Docker/host e `git diff --check` sono
  verdi. Restano invariati i due import-order preesistenti in `main.py` e
  `schemas.py`. Suite completa: 166 passati e il solo failure infrastrutturale
  già noto per `/deploy/rate-limit-collector.py` assente. Integrazione API reale
  rootless `10001:10001`: anonimo 401, admin 200, payload v1 Pydantic valido
  entro i cap, privacy, one-shot reaped e `/health` invariato;
  ACL ripristinate dichiarativamente dopo una prepare stale del gate precedente
  e cleanup finale completo di unit, manager env, config, link e runtime.
- [x] TEST-HO-03-T1 | OWNER: SA-TEST | STATUS: PASSED | Verifica indipendente
  completata senza modifiche al codice. Con flag default-off l'admin riceve 404
  senza alcuna fetch; anonimo riceve 401, viewer e operator 403 senza fetch e
  vedono il flag client `false`, mentre l'admin vede il flag `true` e riceve 200
  anche per snapshot partial strict valido. Il GET funziona senza header CSRF e
  non produce mutazioni. Il rate limit dedicato restituisce 429 con
  `Retry-After` e non richiama il collector oltre il limite. Socket assente,
  payload non JSON o oltre 128 KiB e timeout reali controllati producono
  rispettivamente 503 unavailable, 503 invalid response e 504 timeout, con
  codici stabili e senza dettagli privati. Marker raw e payload non compaiono
  nei log, nell'audit o nel database; conteggi delle tabelle e `/health` restano
  invariati. Lo schema OpenAPI pubblico documenta route e contratto generici:
  `ROOT` ha confermato che ciò è intenzionale e non costituisce fuga, perché ai
  non-admin restano nascosti flag reale, configurazione, inventario e metriche.
  Passano 26 test HO, 24 unittest deploy, lint mirati, verify systemd, frontend
  build e Compose base/Docker/host. La suite backend completa ha 166 passati e
  conserva il solo failure infrastrutturale noto per
  `/deploy/rate-limit-collector.py` assente dall'immagine. L'integrazione API
  reale passa rootless `10001:10001` e host `0:0` con payload strict entro cap,
  privacy, one-shot reaped e quattro componenti di sicurezza verificati; hash
  Stato TCP e insieme delle sessioni tmux sono invariati. Cleanup completo di unit,
  manager env, config, runtime, container e cache temporanee. HO-04 non è stata
  attivata.

#### HO-04 — Vista mobile

- [x] IMP-HO-04 | OWNER: SA-IMP | STATUS: DONE | Implementata vista Host
  separata mobile-first, montata e visibile soltanto con ruolo admin e flag
  backend attivo. Esegue una fetch all'apertura e una per refresh manuale,
  senza polling; mentre è aperta sospende anche i tre polling dashboard.
  Request version e mounted guard scartano risposte concorrenti obsolete e
  update post-unmount. Loading iniziale/in-place, error, retry, empty e stale
  sono espliciti; un refresh fallito conserva l'ultima fotografia valida e le
  ragioni partial restano accanto ai valori disponibili. Mostrati timestamp e
  durata, summary severity/componenti, memoria/swap, load, filesystem, gruppi
  e top processi, sole porte inattese, listener troncati, container
  problematici e conteggio unmapped. Layout da 320 px, controlli touch 44 px,
  heading, aria-live/status/alert e label non dipendenti dal colore. Aggiunto
  test nativo `node:test` senza dipendenze, eseguito nel Dockerfile: 5 passano
  per gating, no-polling/sospensione dashboard, lifecycle concorrente,
  partial/stale/empty e marker mobile/accessibili. Passano inoltre TypeScript +
  Vite, build immagine frontend, 26 test API HO, Compose base/Docker/host e
  `git diff --check`; bundle verificato con un solo client endpoint, JS 271,33
  kB (81,94 gzip) e CSS 32,56 kB (6,83 gzip). Gate manuale aggiornato per
  viewport, tastiera/screen reader, RBAC, network, concorrenza e failure.
  Nessun deploy come richiesto e nessuna attività HO-05.
- [x] TEST-HO-04-T1 | OWNER: SA-TEST | STATUS: FAILED | Build e comportamento
  funzionale sono validati indipendentemente. Passano 5 test UI nativi,
  TypeScript/Vite, frontend-build, 26 test API/contratto e Compose. Su preview
  production con Chromium reale, viewport 320/390/768 non hanno overflow, i
  controlli topbar misurano almeno 44 px, la vista esegue un solo GET
  all'apertura e uno per click, senza polling Host né dashboard. Loading,
  errore iniziale con retry, refresh fallito con snapshot stale preservato,
  partial/ragioni, timestamp, sezioni, liste vuote e filtro delle sole porte
  inattese risultano corretti; una risposta pendente dopo Back non aggiorna la
  vista e non genera errori. Viewer, operator e admin con flag off non vedono la
  voce e producono zero GET host. Bundle e contratto TS espongono un solo
  endpoint e nessun marker privato. Resta un blocker accessibilità
  riproducibile: dopo il click sulla voce Host il trigger viene smontato e
  `document.activeElement` diventa `BODY`; anche dopo Back il focus resta su
  `BODY`. Manca quindi sia il focus iniziale sulla nuova vista sia il ripristino
  al controllo Host, rendendo disorientante la navigazione da tastiera e screen
  reader. Hash TCP e insieme delle sessioni tmux restano invariati; nessun
  deploy e nessuna attività HO-05.
- [x] IMP-HO-04-R1 | OWNER: SA-IMP | STATUS: DONE | Corretto esclusivamente il
  lifecycle focus. All'ingresso un ref porta il focus sul titolo Host
  `H1[tabindex=-1]` con `preventScroll` in un animation frame cancellabile;
  il target semantico non mostra un outline da falso controllo. Back registra
  l'intento prima del remount e un secondo frame cancellabile ripristina il
  focus sul trigger Host tramite ref persistente, preservando i normali focus
  style dei pulsanti. Guard e cleanup coprono unmount/race senza GET o update
  aggiuntivi. Il test source nativo sale a 6 passati; TypeScript/Vite, immagine
  frontend con test incorporato, 26 test API HO, Compose e `git diff --check`
  passano. Su preview production Chromium reale, a 320 e 390 px l'ingresso
  produce `activeElement=H1` testo Host/tabindex `-1`, outline none e scroll 0;
  dopo Back produce `activeElement=BUTTON` con label Osservabilità host e scroll
  0. Entrambi i cicli mantengono un solo GET Host. Preview terminata e nessun
  container/unit/runtime temporaneo lasciato. HO-05 non avviata.
- [x] TEST-HO-04-T2 | OWNER: SA-TEST | STATUS: PASSED | Rework focus e gate T1
  verificati indipendentemente senza modifiche al codice. Su preview production
  Chromium a 320 e 390 px, l'ingresso porta `activeElement` sul titolo `H1`
  Host con `tabindex=-1`, outline non interattivo nascosto, `scrollY=0` e zero
  overflow. Tab raggiunge Aggiorna e Shift+Tab torna a Back; entrambi i pulsanti
  hanno `:focus-visible=true` e outline browser visibile. Enter su Back
  ripristina il pulsante rimontato Osservabilità host, ancora focus-visible e
  senza scroll; Shift+Tab/Tab ed Enter riaprono correttamente la vista. Click,
  touch target da almeno 44 px, viewport 768, richiesta pendente dopo unmount e
  race non introducono errori. Rimangono un solo GET all'apertura e uno per
  refresh manuale, senza polling Host/dashboard; viewer, operator e flag off
  mantengono voce assente e zero GET. Initial loading/error/retry, empty,
  partial/ragioni, stale con ultima fotografia preservata, timestamp, sezioni e
  filtro anomalie sono nuovamente confermati. Passano 6 test UI nativi,
  TypeScript/Vite, frontend-build e build immagine `web`, 26 test
  API/socket/contratto e Compose base/Docker/host. Bundle con un solo endpoint e
  senza marker privati; hash TCP e insieme delle sessioni tmux invariati.
  Preview e container browser temporanei rimossi. HO-05 non è stata attivata e
  non è stato eseguito alcun deploy.
- [x] IMP-HO-04-R2 | OWNER: SA-IMP | STATUS: DONE | Estensione richiesta
  dall'utente dopo il primo deploy: aggiungere alla vista Host un export JSON
  del solo snapshot API già sanitizzato, senza nuova fetch e senza arricchirlo
  con cmdline, IP, path, inventario o dati UI privati. Mostrare una sezione
  espandibile con `textarea` read-only contenente JSON formattato e un comando
  `Copia JSON`; l'export deve essere disponibile per ogni snapshot e avere
  evidenza maggiore quando lo stato è `critical`. Usare Clipboard API con
  feedback accessibile e fallback che seleziona la textarea per copia manuale.
  Un refresh riuscito aggiorna l'export; un refresh fallito conserva JSON e
  snapshot precedenti. Aggiungere test automatici per serializzazione,
  no-fetch, clipboard success/failure/fallback, stato critico, focus e mobile;
  aggiornare il gate e, a fine lavoro, creare `TEST-HO-04-T3` in
  `READY_FOR_TEST`. Non procedere direttamente al deploy.
  Evidenze SA-IMP: l'export deriva soltanto da
  `JSON.stringify(snapshot, null, 2)` e mostra l'ultimo snapshot valido in una
  `textarea` read-only dentro una sezione espandibile, evidenziata anche
  testualmente in stato critical. Clipboard API copia la stessa stringa e
  annuncia l'esito con `aria-live`; API assente o negata sposta focus e
  selezione sull'intero testo per la copia manuale, senza `execCommand`.
  Refresh riuscito sostituisce snapshot e JSON; refresh fallito conserva
  entrambi. Passano 9 test UI nativi, TypeScript/Vite, build container frontend,
  26 test backend HO, quattro configurazioni Compose, bundle/diff-check e
  controllo dell'unico endpoint. In Chromium reale a viewport mobile il JSON è
  parseabile e deep-equal alla risposta sanitizzata; apertura e copie non
  aggiungono GET, success/failure clipboard e selezione completa passano,
  refresh successivo aggiorna il valore e un errore lo lascia invariato.
  Nessun overflow, campo raw, preview, container browser o artefatto temporaneo
  residuo. Gate aggiornato; nessun deploy, commit o modifica release.
- [x] TEST-HO-04-T3 | OWNER: SA-TEST | STATUS: PASSED | Validazione
  indipendente completata in Chromium reale a viewport 320 e 390 px. Il valore
  della `textarea` è JSON parseabile, byte-per-byte uguale a
  `JSON.stringify(snapshot, null, 2)` e deep-equal all'esatta risposta API,
  inclusi valori testuali avversariali; una verifica ricorsiva delle chiavi
  conferma il solo contratto v1, senza wrapper, stato UI o campi extra. La
  sezione `details` è azionabile da tastiera, segnala lo stato `critical` e non
  produce GET all'espansione. Clipboard API disponibile copia la stringa
  esatta e aggiorna il feedback `aria-live`; API mancante e rifiuto
  `NotAllowedError` portano focus alla textarea, selezionano l'intero valore e
  mostrano l'istruzione di copia manuale, senza invocare `execCommand`. Nessuna
  delle tre copie produce GET. Un refresh riuscito sostituisce snapshot e JSON
  con la nuova risposta; il successivo errore controllato conserva entrambi,
  mostra ultima fotografia/stale e non introduce polling. Focus iniziale,
  navigazione tastiera, selezione e layout non causano overflow alle due
  viewport. Passano 9 test UI nativi, TypeScript/Vite, frontend-build e 26 test
  API/socket/contratto; bundle con un solo endpoint Host, feedback presenti,
  nessuna sourcemap o marker vietato e diff-check pulito. Server, browser,
  fixture e container temporanei rimossi; nessuna correzione, deploy, commit o
  attività HO-05-R2.

#### HO-05 — Hardening, documentazione e candidato al deploy

- [x] IMP-HO-05 | OWNER: SA-IMP | STATUS: DONE | Completare
  hardening delle unit systemd (`NoNewPrivileges`, filesystem protetto,
  permessi socket minimi e nessuna esecuzione root), esempio di configurazione
  con soli valori fittizi, documentazione di architettura, sicurezza, API e
  deploy. Aggiornare `LATEST_RELEASE` nello stesso round e aggiungere il gate
  end-to-end completo. Eseguire `backend-test`, `frontend-build` e
  `docker compose config --quiet`, registrandone gli esiti per `SA-TEST`.
  Evidenze SA-IMP: unità utente con capability vuote, filesystem/kernel/device
  protetti, solo `AF_UNIX`, limiti socket e test statici anti-root; esempio
  limitato a `/srv/example-*`, porta `4242` e label fittizie. Aggiornati README,
  architettura, sicurezza, contratto API, ADR, gate E2E e `LATEST_RELEASE`
  esplicitamente come candidata. Passano 25 test deploy, 6 test Host UI,
  `frontend-build`, build immagine `web`, verifica delle tre unità systemd e
  `docker compose config --quiet` per base, host e i due overlay observer. La
  suite backend ha 166 test passati e un solo errore infrastrutturale già noto
  (fixture `/deploy/rate-limit-collector.py` assente dall'immagine di test);
  lint mirato backend/deploy pulito, lint globale invariato con i due errori di
  ordinamento import preesistenti in `app/main.py` e `app/schemas.py`. Passano
  diff-check, audit del bundle e scansioni segreti/inventario; gli overlay non
  aggiungono privilegi, capability, rete host, mount `/proc`, `/sys` o socket
  Docker, e mantengono il bind pubblicato esplicito. Nessun deploy eseguito.
- [x] TEST-HO-05-T1 | OWNER: SA-TEST | STATUS: FAILED | Il preflight statico è
  quasi interamente verde: passano 26 test HO backend, 25 deploy, 6 UI,
  TypeScript/Vite, frontend-build e immagine web, lint mirati, verify systemd,
  policy Compose risolta per base/host con e senza observer, controllo mount,
  privilegi, capability, bind esplicito, esempio fittizio strict, bundle senza
  sourcemap/marker privati, `LATEST_RELEASE` candidata e diff-check. Security
  offline classifica prepare `4.3 OK` e collector `3.0 OK`; l'eccezione che
  lascia la prepare senza `ProtectSystem`, `ProtectHome` e `PrivateTmp` è
  confermata necessaria per `setfacl` sugli UID subordinati, mentre le altre
  restrizioni richieste sono presenti. Il gate reale fallisce però prima
  dell'`ExecStart`: al restart della user prepare, systemd termina con
  `status=218/CAPABILITIES` e `Failed to drop capabilities: Operation not
  permitted`; la socket resta inattiva. Le direttive vuote di capability
  richieste dai test statici non sono quindi applicabili nel user manager reale.
  Lo stesso manager avverte inoltre che `IPAddressDeny` non viene applicato
  perché non gira come root; il confinamento di rete realmente efficace resta
  `RestrictAddressFamilies=AF_UNIX`. La scansione inventario trova anche output
  host reale già scritto nella roadmap del round (session id tmux, dimensioni
  di payload e conteggi listener), in contrasto con il gate che ne vieta il
  versionamento; l'intestazione del gate dichiara ancora erroneamente la UI Host
  fuori scope fino a HO-04. La suite completa conserva 166 passati e il solo
  failure infrastrutturale noto per `/deploy/rate-limit-collector.py` assente
  dall'immagine: il test isolato passa montando `/deploy` e i file baseline
  coinvolti sono invariati. Il lint globale conserva i due errori di import
  order già presenti nel worktree prima di HO-05. Cleanup completo di unit,
  manager env, config, runtime, container e cache; nessun listener TCP
  dell'observer è rimasto e le sessioni tmux sono invariate. La variazione
  ambientale del set TCP durante il gate appartiene a un altro processo host,
  non alle unit observer. Nessun deploy, commit o attività HO-06.
- [x] IMP-HO-05-R1 | OWNER: SA-IMP | STATUS: DONE | Rendere
  avviabili prepare e collector come vere user unit senza affidarsi a direttive
  capability che richiedono privilegi assenti: preservare `NoNewPrivileges` e
  dimostrare nel processo reale capability effettive/permesse nulle. Valutare
  esplicitamente il warning `IPAddressDeny` del user manager: rimuovere ogni
  promessa ineffettiva o documentarla come ridondante, mantenendo
  `RestrictAddressFamilies=AF_UNIX` come blocco verificabile della rete IP. Non
  aggiungere `ProtectSystem`, `ProtectHome` o `PrivateTmp` alla prepare, perché
  romperebbero le ACL rootless; il collector deve conservarli. Aggiornare i test
  perché includano restart reale, ACL subuid e connect one-shot oltre ai check
  statici. Sanitizzare da `docs/backlog.md` tutti gli identificatori e conteggi
  host-specific del round, sostituendoli con evidenze qualitative, e correggere
  l'intestazione stale del gate per includere la UI HO-04. Preservare tutte le
  suite e le eccezioni preesistenti sopra; dopo il rework aggiungere
  `TEST-HO-05-T2` `READY_FOR_TEST`. HO-06 resta bloccata e non va eseguito alcun
  deploy o commit.
  Evidenze SA-IMP: rimosse dalle due service le direttive esplicite
  `CapabilityBoundingSet`, `AmbientCapabilities` e `IPAddressDeny`; dal
  collector eliminate anche le protezioni device/clock/log/moduli che
  producono implicitamente lo stesso errore nel manager user e
  `ProtectHostname`, lì ignorata. Restano `NoNewPrivileges`, sola `AF_UNIX`,
  filesystem/home protetti sul collector, restrizioni kernel/namespace
  applicabili, limiti runtime/socket e ACL nominali. La prepare conserva
  intenzionalmente la visibilità filesystem/home e `/tmp` dell'utente per
  operare sugli UID subordinati; rischio residuo, path fidato e gate
  fail-closed sono documentati. Nel vero user manager prepare e socket partono
  senza `218/CAPABILITIES`; mode e ACL rootless sono corretti, connessioni
  concorrenti owner e backend non-root validano il contratto one-shot. Un
  processo user con le restrizioni comuni ha capability permesse, effettive e
  ambienti nulle, consente `AF_UNIX` e blocca `AF_INET`. Preflight e postflight
  confermano invariati hash TCP e insieme delle sessioni tmux, senza
  pubblicarne valori. Sanitizzati roadmap, esempio environment e gate da ID,
  UID, dimensioni e conteggi host; intestazione HO-04 corretta. Passano 25 test
  deploy (incluso rerun seriale della flake producer), 26 test backend HO, 6
  test UI, frontend-build, quattro configurazioni Compose, verify systemd,
  lint mirati, diff-check e scansioni inventario/credenziali. Suite backend:
  166 passati e il solo errore infrastrutturale già registrato; lint globale:
  i due soli ordinamenti import preesistenti. Cleanup completo; nessun deploy,
  commit o attività HO-06.
- [x] TEST-HO-05-T2 | OWNER: SA-TEST | STATUS: PASSED | Gate indipendente
  completato sul vero user manager: prepare e socket attive senza
  `218/CAPABILITIES`, warning ignorati o errori di namespace; mode e ACL
  nominali sono corretti anche per l'UID mappato rootless. Il processo con le
  restrizioni comuni ha capability permesse, effettive e ambienti nulle
  (`CapInh` osservata ma non usata come requisito), consente `AF_UNIX` e nega
  `AF_INET`. Quattro client concorrenti producono snapshot v1 validi e le
  istanze one-shot vengono raccolte; connettono sia il backend non-root mappato
  sia l'identità root del daemon rootless. La rimozione dell'ACL mappata nega il
  connect e il restart la ripristina; fermare la socket fallisce chiuso. Un
  primo `CollectorConfigError` era causato esclusivamente da un drop-in
  volatile stale del gate R1, che puntava a un config temporaneo già rimosso:
  eliminato l'artefatto di test, il runtime reale e il journal pulito passano.
  Restano intenzionali e documentati la rimozione delle direttive non
  applicabili nel manager user e il rischio residuo della prepare, che deve
  vedere filesystem/home per applicare `setfacl` agli UID subordinati; il
  collector conserva il confinamento filesystem/home e le protezioni user
  manager compatibili. Passano 26 test backend HO, 25 test deploy, 6 test UI,
  build TypeScript/Vite locale e container, immagine web, quattro risoluzioni
  Compose, verify/systemd e lint HO. La suite backend completa chiude con 166
  passati e il solo errore infrastrutturale noto per `/deploy` non montato
  nell'immagine test; il test isolato passa con il mount. Il lint globale
  conserva soltanto i due import-order preesistenti. Diff-check, bundle e
  scansioni rigorose di roadmap, gate, environment e candidato non trovano ID,
  UID, hostname/IP, misure di payload/listener, porte/servizi reali o
  credenziali versionate; l'intestazione include HO-04. Hash TCP e insieme
  tmux sono invariati senza pubblicarne i valori. Cleanup completo di unit,
  drop-in, manager env, config, runtime, container e cache; nessun deploy,
  commit o attività HO-06.

#### HO-06 — Deploy mirato e validazione pubblicata

- [x] IMP-HO-06 | OWNER: SA-IMP | STATUS: DONE | Installare
  e attivare soltanto le unit socket/service dell'observer, poi ricreare
  esclusivamente `backend` e `web`. Non ricreare o riavviare `tmux-runtime` e
  non interrompere le sessioni host. Verificare lo stato dei servizi e
  consegnare a `SA-TEST` URL/contesto di test senza inserire host, IP o
  inventario nella roadmap versionata.
  Evidenze SA-IMP: baseline di container stateless, sessioni tmux e listener
  registrata e confrontata esclusivamente in memoria. Configurazione host
  privata `0600` e sole unit user prepare/socket/collector installate; prepare
  e socket sono abilitate e attive, ACL rootless e collector one-shot validi.
  Overlay host risolto e deploy eseguito con servizi espliciti e `--no-deps`:
  ricreati soltanto backend e web, senza creare o riavviare il runtime tmux.
  Health, login admin, flag client, route Host, contratto v1, mount read-only,
  assenza di privilegi/mount vietati e bundle UI pubblicato sono verificati.
  Dopo la verifica implementatore `LATEST_RELEASE` è stata promossa da
  candidata a rilasciata e pubblicata ricreando soltanto web; backend, insieme
  delle sessioni tmux e hash TCP sono rimasti invariati in entrambi i
  confronti. Nessun valore d'inventario è stato versionato e nessun commit è
  stato creato.
- [x] TEST-HO-06-T1 | OWNER: SA-TEST | STATUS: SUPERSEDED_BY_SCOPE_CHANGE |
  Gate finale interrotto da `ROOT` quando l'utente ha richiesto l'export JSON
  dopo il deploy. Le verifiche già eseguite restano evidenza parziale, ma non
  chiudono il round modificato; dopo `TEST-HO-04-T3` vanno ripetuti preflight e
  deploy mirato con nuovi check versionati.

- [x] IMP-HO-05-R2 | OWNER: SA-IMP | STATUS: DONE |
  Integrare export JSON in documentazione, gate, scansioni privacy e
  `LATEST_RELEASE`; rieseguire tutti i preflight HO-05 e creare
  `TEST-HO-05-T3`.
  Evidenze SA-IMP: README, architettura, sicurezza, contratto e gate descrivono
  l'export come serializzazione esatta dello snapshot API sanitizzato, senza
  fetch, wrapper, metadati UI o persistenza, e registrano il rischio residuo
  della condivisione volontaria di dati operativi minimizzati.
  `LATEST_RELEASE` include l'export ma resta esplicitamente candidata. Passano
  9 test UI nativi, 26 test backend HO, TypeScript/Vite, frontend-build
  container, immagine web, quattro configurazioni Compose, verify systemd e 25
  test deploy seriali. Il batch parallelo dei test deploy ha riprodotto la race
  preesistente della fixture producer sul file PID; caso isolato e intera suite
  seriale passano. La suite backend completa conserva 166 passati e il solo
  errore infrastrutturale noto per la fixture `/deploy` assente; lint mirati
  puliti e lint globale invariato con i due ordinamenti import preesistenti.
  Bundle con un solo endpoint Host, export/feedback presenti, nessuna sourcemap
  o marker privato; scansioni credenziali, inventario, esempio JSON e sorgente
  del fallback passano. Compose risolto, mount installato e unità mantengono
  read-only, assenza di mount/privilegi vietati e hardening precedente. Diff e
  cleanup sono puliti; container stateless, runtime, sessioni tmux e hash TCP
  sono invariati rispetto alla baseline in memoria. Nessun deploy o commit.
- [x] TEST-HO-05-T3 | OWNER: SA-TEST | STATUS: PASSED | Preflight
  indipendente completo dopo l'export. README, architettura, sicurezza,
  contratto e gate concordano: la textarea/copia contiene l'esatto snapshot
  API già validato e sanitizzato, senza wrapper, fetch aggiuntivo, metadati UI
  o persistenza; fallback manuale e rischio residuo della condivisione
  volontaria sono espliciti. `LATEST_RELEASE` include l'export ma resta
  chiaramente **candidata**, con redeploy subordinato al gate finale, e non si
  dichiara falsamente validata. Passano 9 test UI nativi, TypeScript/Vite, 26
  test API/socket/contratto, frontend-build, immagine web, quattro
  configurazioni Compose, verify systemd e 25 test deploy eseguiti realmente
  in isolamento. Il primo batch, concorrente con altri job, ha riprodotto la
  race preesistente del producer PID; la suite isolata passa integralmente. La
  suite backend completa conserva 166 passati e il solo errore infrastrutturale
  noto dell'immagine senza `/deploy`; il caso passa col mount previsto. Lint HO
  pulito e lint globale invariato con i due import-order preesistenti. Bundle
  con un solo endpoint Host, export e feedback presenti, nessuna sourcemap;
  scansioni su credenziali, inventario, example JSON, fixture e sorgenti test
  non trovano valori reali o marker privati, distinguendo i marker sintetici
  dei test negativi. Config privata `0600`, ACL rootless, socket, mount backend
  read-only, filesystem container read-only, assenza di capability/privilegi,
  rete host e mount vietati e hardening delle user unit sono invariati.
  Diff-check pulito; hash TCP, insieme tmux e container pubblicati restano
  invariati senza divulgarne i valori. Cleanup completo; nessun deploy, commit
  o attività HO-06-R1.
- [x] IMP-HO-06-R1 | OWNER: SA-IMP | STATUS: DONE |
  Pubblicare nuovamente soltanto `web` se backend/unit/config non cambiano,
  verificando comunque baseline e continuità tmux; creare `TEST-HO-06-T2`.
  Evidenze SA-IMP: baseline di ID/avvio dei container, insieme tmux e hash TCP
  conservata solo in memoria. La candidata è stata pubblicata ricreando
  esclusivamente web con overlay risolto, servizio esplicito e `--no-deps`.
  Smoke Chromium con login admin conferma details, textarea e Copy JSON;
  textarea byte-per-byte uguale a `JSON.stringify(snapshot, null, 2)` e
  deep-equal alla risposta API reale, con feedback clipboard e nessun overflow
  mobile. Solo dopo questo smoke `LATEST_RELEASE` è stata promossa a
  **Osservabilità host + export JSON**, rilasciata e validata, costruendo e
  ricreando nuovamente soltanto web. Il secondo smoke pubblicato conferma
  export, API Host e release note finale; health e unit observer restano attivi.
  A ogni confronto web cambia come atteso, mentre backend ID/avvio, runtime,
  sessioni tmux e listener TCP restano invariati. Bundle live con un solo
  endpoint Host e senza testo candidato; scansioni, diff-check e cleanup
  passano. Nessun backend/unit/config è stato modificato o ricreato e nessun
  commit è stato creato.
- [x] TEST-HO-06-T2 | OWNER: SA-TEST | STATUS: PASSED | Validazione live
  indipendente completata. Health/tmux backend, login admin, config con feature
  flag e route Host rispondono correttamente; lo snapshot reale supera il
  contratto strict e la scansione ricorsiva privacy. In Chromium mobile fresco
  il percorso `⋯` → Host, focus, details e textarea sono presenti: il testo è
  byte-per-byte `JSON.stringify(snapshot, null, 2)`, parseabile e deep-equal
  alla risposta reale. Clipboard consentita copia la stringa esatta con
  feedback; apertura/copia non aggiungono GET, non compare polling e non c'è
  overflow a 320 px. Viewer e operator non vedono Host e producono zero fetch
  UI; la richiesta esplicita è negata con `403`. Quattro client socket
  concorrenti ricevono snapshot privacy-safe e le one-shot vengono raccolte.
  La socket fermata in modo controllato produce `503` e viene ripristinata
  `active`; conservazione stale, fallback clipboard e selezione completa
  restano coperti dal Chromium deterministico T3 e dai test pubblicati. Bundle
  live e release note riportano **Osservabilità host + export JSON** senza testo
  candidata, con un solo endpoint Host. Il reload della shell live passa; su
  URL IP con certificato ignorato Chromium non concede `serviceWorker.ready`,
  limite infrastrutturale separato: `sw.js` live è verificato network-first,
  usa la cache versionata e l'evidenza IMP conferma il client mantenuto aperto
  attraverso il redeploy. Età/ID confermano che è stato ricreato soltanto web;
  backend, unit e config restano invariati. Hash TCP invariato. Durante la
  finestra estesa l'insieme tmux è stato perturbato da attività utente live
  concorrente; il confronto del deploy IMP era invariato e nessuna azione del
  gate observer ha creato, rinominato o terminato sessioni, quindi non è un
  failure prodotto. Scansioni e diff-check passano; cleanup completo di
  fixture, cookie, browser, control server e file temporanei, socket/prepare
  attive. Nessuna correzione o commit eseguito. Gate finale superato: commit
  finale autorizzato.

Il precedente `TEST-HO-06-T1` è stato interrotto prima del verdetto: i controlli
già eseguiti non sostituiscono `TEST-HO-06-T2`, che deve rivalidare l'intero
flusso admin, stati parziali, refresh manuale, assenza di polling, export JSON e
continuità delle sessioni tmux prima del commit finale.

### Criterio di completamento

Il modulo passa a `rilasciato e validato` soltanto quando tutti i check da
`GATE-HO-00` a `TEST-HO-06` sono chiusi con esito positivo, non esistono voci
`REWORK_REQUIRED` aperte, il deploy pubblicato è stato verificato e
`LATEST_RELEASE` descrive questa funzionalità. Il solo completamento dei test
locali non chiude il round.

## Anomalie e follow-up da validare

### HO-FU-01 — Stato host critico sovrastimato da segnali non contestualizzati

- STATUS: VALIDATED_WITH_CHANGES
- SEGNALATO_DA: Codex
- Contesto: snapshot one-shot del modulo di osservabilità su un host Linux con
  processi applicativi, container rootless, swap già occupata e firewall
  perimetrale indipendente dall'host.
- Comportamento osservato: l'envelope risulta `critical` per la sola percentuale
  di swap occupata, per conteggi assoluti di gruppi processo e per listener TCP
  wildcard non presenti nell'inventario atteso. Il collector non riesce ad
  attribuire i listener ai processi e non accede a Docker, ma combina comunque
  questi segnali incompleti nel verdetto. Una verifica esterna separata mostra
  che i listener wildcard osservati localmente sono filtrati dal firewall
  perimetrale, mentre memoria disponibile, carico e disco non indicano
  saturazione e un breve campione di swap I/O non mostra thrashing.
- Comportamento atteso: distinguere i fatti raccolti dalla valutazione del
  rischio. Un bind wildcard deve restare visibile, ma non essere descritto come
  esposizione Internet accertata senza evidenza di raggiungibilità; raccolte
  parziali o integrazioni indisponibili devono produrre `unknown` nel componente
  interessato senza aggravare da sole l'envelope. Swap e gruppi processo devono
  diventare critici soltanto con indicatori contestuali configurati e
  riproducibili, non per una singola soglia assoluta generica.
- Procedura di riproduzione: configurare un listener TCP non presente
  nell'allowlist su `0.0.0.0:<porta-fittizia>`, lasciandolo filtrato da un
  firewall perimetrale; rendere Docker non accessibile al collector; predisporre
  swap occupata oltre la soglia con memoria disponibile ancora adeguata e senza
  swap I/O sostenuto; includere gruppi multiprocesso leciti oltre la soglia.
  Richiedere un solo snapshot e confrontare stato envelope, stato dei
  componenti, reasons e dati grezzi minimizzati.
- Evidenze/log sanitizzati: snapshot con memoria disponibile circa metà del
  totale, swap occupata oltre quattro quinti, carico normalizzato sotto uno,
  filesystem sotto soglia, listener wildcard attribuibili a servizi noti ma
  `process_name=null`, Docker `available=false` e test TCP esterno in timeout
  sulle porte applicative; una porta di controllo consentita risulta invece
  raggiungibile. Nessun host, IP, porta reale, processo privato o risultato
  esterno identificabile è riportato qui.
- Impatto: falso allarme ad alta severità, perdita di fiducia nel verdetto
  sintetico e rischio di interventi inutili o distruttivi su servizi sani; al
  tempo stesso, abbassare indiscriminatamente la severità dei wildcard listener
  potrebbe occultare una regressione reale del firewall.
- Funzionalità proposta: introdurre una valutazione esplicita per evidenza e
  confidenza. Separare `bind_scope` da `external_reachability`, mantenendo
  quest'ultima `unknown` salvo attestazione affidabile e opt-in; permettere alla
  configurazione privata di dichiarare esposizione attesa e presenza di un
  controllo perimetrale senza inserire dettagli infrastrutturali nel repo.
  Contestualizzare la swap con memoria disponibile e, solo se compatibile col
  budget one-shot, un delta locale breve e limitato di swap-in/swap-out.
  Valutare i gruppi tramite soglie per label o consumo aggregato, non con un
  limite globale. Conservare `unknown` per ownership listener parziale e Docker
  indisponibile. Non effettuare scansioni Internet automatiche dal collector,
  non contattare API cloud e non introdurre credenziali o dipendenze esterne.
- File probabilmente coinvolti: collector e relativi test host-side; schema e
  contratto `host-observability-v1`; esempio di configurazione privata; modelli
  backend; mapping di severità e testi della vista Host; gate, architettura e
  threat model. I path esatti vanno determinati durante la validazione senza
  riaprire o riscrivere la roadmap HO-00–HO-06 conclusa.
- Rischi di sicurezza/architettura: un campo configurabile che dichiara il
  firewall può diventare un'assicurazione falsa se la policy esterna cambia;
  una sonda esterna divulgherebbe destinazione e porte a terzi e introdurrebbe
  rete, latenza e disponibilità nel collector one-shot; l'accesso alle API del
  provider porterebbe credenziali cloud nel boundary. Il fail-safe deve quindi
  conservare il wildcard bind come evidenza locale e non tradurre
  `external_reachability=unknown` in `closed`. Un eventuale cambio di schema
  richiede versionamento compatibile e non deve ampliare i dati esposti.
- Criteri di accettazione suggeriti: fixture deterministiche dimostrano che
  (1) wildcard inatteso con raggiungibilità ignota resta evidente ma non viene
  presentato come esposizione Internet verificata; (2) una dichiarazione
  privata di firewall non può produrre `closed` né sopprimere il dato di bind;
  (3) raccolta listener parziale e Docker indisponibile restano `unknown` e non
  causano da soli `critical`; (4) swap molto occupata con memoria disponibile e
  delta I/O nullo non è critica, mentre pressione di memoria e swap I/O
  sostenuto superano la soglia prevista; (5) gruppi leciti configurati non
  attivano il limite globale, ma una crescita anomala o RSS aggregato oltre
  soglia sì; (6) nessuna sonda Internet, API cloud, credenziale, hostname, IP o
  inventario reale entra in codice, payload, log, fixture o documentazione;
  (7) il contratto mantiene stati e reasons deterministici, compatibilità
  dichiarata e propagazione corretta fino all'envelope e alla UI.

#### Esito della validazione ROOT

La proposta è accettata, ma non integralmente nella forma iniziale. La lettura
del collector conferma tre cause indipendenti di sovrastima:

- `read_memory()` rende critica la memoria quando la sola occupazione swap
  supera la soglia, anche con `MemAvailable` adeguata e senza un indicatore di
  attività swap;
- `read_processes()` applica a ogni nome processo due soglie globali di conteggio,
  senza distinguere gruppi leciti né considerare il loro RSS aggregato;
- `read_listeners()` rende critico ogni bind wildcard inatteso sulla sola
  evidenza locale del bind, che non dimostra la raggiungibilità da Internet.

Due parti della diagnosi non sono invece confermate come cause autonome del
`critical`: Docker indisponibile produce già `unknown`, e `listeners_partial`
porta a `unknown` soltanto in assenza di un altro verdetto concreto. Inoltre la
UI corrente mostra “Porta wildcard inattesa”, non dichiara che la porta sia
raggiungibile da Internet. L'assenza di ownership del listener non è oggi
modellata come incompletezza distinta e va resa esplicita soltanto se può
essere calcolata in modo deterministico.

La correzione adotterà questi vincoli:

- il bind locale rimane sempre visibile; la raggiungibilità esterna resta
  `not_assessed` e non diventa mai `closed` in base a una dichiarazione di
  configurazione;
- la configurazione privata può definire policy locali per porta/scope e per
  nome processo, ma non attestare lo stato del firewall né sopprimere i fatti
  raccolti;
- un wildcard inatteso è `warning` per default; diventa `critical` soltanto se
  viola una policy locale esplicita, non per una presunta esposizione esterna;
- l'occupazione swap resta un fatto mostrato. Il livello critico richiede
  pressione di memoria e attività swap contestuali; l'eventuale campione
  `/proc/vmstat` deve essere breve, limitato, iniettabile nei test e compreso
  nel timeout one-shot. Se il campione non è disponibile, il dato contestuale
  è `unknown`, non `0`;
- i gruppi non configurati vengono elencati ma non diventano critici per un
  limite globale. Le policy per nome possono usare conteggio e RSS aggregato.
  Il rilevamento di una crescita temporale resta fuori scope perché richiederebbe
  storia o persistenza, escluse dall'MVP;
- nessuna rete in uscita, sonda esterna, API cloud, credenziale, hostname, IP
  grezzo o dettaglio infrastrutturale viene aggiunto al boundary;
- l'aggiunta di evidenza/confidenza e dei nuovi indicatori richiede un
  contratto output v2. Durante il rollout backend e frontend devono accettare
  sia v1 sia v2; il collector deve leggere la configurazione privata v1
  esistente con default sicuri oppure una v2 esplicita. La rimozione della
  compatibilità v1 non appartiene a questo round.

#### Criterio di completamento HO-FU-01

Il follow-up è chiuso soltanto dopo contratto e configurazione compatibili,
test automatici deterministici, verifica indipendente di ogni fase, deploy
mirato e collaudo sulla fotografia reale. Il deploy deve preservare
`tmux-runtime`; `LATEST_RELEASE` viene aggiornato soltanto nella fase finale,
dopo il gate live superato. I tentativi falliti restano nella roadmap e seguono
il protocollo di rework già definito per HO-00–HO-06.

#### Roadmap flaggabile HO-FU-01

- [x] GATE-HO-FU-01 | OWNER: ROOT | STATUS: PASSED | Anomalia validata sul
  codice corrente. Accettati scoring contestuale e separazione tra fatto locale
  e valutazione; respinte attestazioni di firewall e sonde esterne. Autorizzata
  la preparazione della roadmap, non l'implementazione.

- [x] IMP-HO-FU-01 | OWNER: SA-IMP | STATUS: DONE | Implementati contratto
  output v2 e configurazione privata v2 con rollout compatibile. Il backend usa
  un'unione Pydantic discriminata e fail-closed per v1/v2; il frontend espone
  tipi discriminati senza cambiare endpoint o serializzazione dell'export. Il
  v2 separa `bind_scope` da `external_reachability=not_assessed`, vincola
  disponibilità e risultato del campione swap, pubblica soltanto l'esito delle
  policy processo/listener e mantiene private soglie e dettagli host. Il parser
  accetta la config v1 legacy oppure la v2 esplicita, mai forme miste; la v2
  supporta policy count/RSS limitate, policy porta/scope e campione swap
  bounded, senza firewall, credenziali o dipendenze di rete.
  File: `backend/app/services/host_observability_contract.py`, service e test
  Host API/contratto; `deploy/host-observability-collector.py`, esempio e test;
  `frontend/src/api.ts` con adattamento compatibile della vista; contratto v1 e
  nuovo `docs/contracts/host-observability-v2.md`, ADR 009, architettura e
  sicurezza. Test di validazione coprono payload v1/v2, reason separati, campi
  extra, campione coerente/incoerente, versione futura, response senza wrapper,
  fallback config v1, esempio v2, campi misti, cardinalità e boundary numerici.
  Evidenze/comandi SA-IMP: suite backend completa sull'albero corrente `179
  passed`; test mirati contratto/API `28 passed`; suite host observability
  deploy `29 passed`; test collector `23 passed`; test UI Host `9 passed`;
  `npm run build`, `docker compose config --quiet`, lint Ruff dei file coinvolti,
  validazione JSON e `git diff --check` passano. Il lint backend globale riporta
  soltanto i due `I001` preesistenti in `app/main.py` e `app/schemas.py`, fuori
  scope e già registrati. Nessun deploy, commit o avvio di HO-FU-02.
- [x] TEST-HO-FU-01-T1 | OWNER: SA-TEST | STATUS: FAILED | Verifica
  indipendente eseguita senza deploy o correzioni. Le suite mirate
  contratto/API/socket passano (`37 passed`), i test UI Host e la build frontend
  passano (`9 passed`), e i 29 test host-side hanno un errore intermittente
  nella fixture del timeout, poi superato in due ripetizioni isolate. Config v1
  e v2, forme miste, limiti dichiarati, output v1 intenzionale del collector,
  assenza di nuove dipendenze di rete e scansione privacy non evidenziano altri
  blocker. Il gate fallisce però la strict validation v2: un campione
  `swap_io_sample` con `available=false`, `duration_ms=100` e delta `null` viene
  accettato dall'adapter. Il contratto richiede invece che, quando il campione è
  indisponibile, tutti e tre i risultati siano `null`; la forma parziale deve
  fallire chiuso.

- [x] IMP-HO-FU-01-R1 | OWNER: SA-IMP | STATUS: DONE | Corretto
  il validatore di `SwapIoSample` affinché accetti esclusivamente le due forme
  coerenti: `available=true` con tutti i risultati presenti, oppure
  `available=false` con tutti i risultati `null`. Aggiunti test parametrizzati
  per ogni combinazione parziale,
  inclusi un solo valore presente e due valori presenti, senza modificare il
  contratto documentato né anticipare HO-FU-02. Rieseguiti test contratto/API e
  suite backend prima di dichiarare pronto il nuovo check. Nessun deploy.
  Evidenze SA-IMP: riprodotto prima della correzione il payload
  `available=false`, `duration_ms=100`, delta `null`, confermandone l'errata
  accettazione. Il validatore ora distingue presenza parziale e completa con
  controlli `any`/`all`; un test parametrizzato esercita tutte le 16
  combinazioni fra flag e presenza dei tre risultati, incluse forme con uno o
  due valori. Test contratto/API `44 passed`, suite backend completa `195
  passed`, lint Ruff mirato e `git diff --check` passano. Nessun cambiamento al
  contratto documentato, deploy, commit o attività HO-FU-02.

- [x] TEST-HO-FU-01-T2 | OWNER: SA-TEST | STATUS: PASSED | Rework verificato
  indipendentemente sui sorgenti correnti. Una matrice esterna ai test del
  SA-IMP esercita tutte le 16 combinazioni tra `available` e presenza dei tre
  risultati: vengono accettate soltanto `true` con tutti valorizzati e `false`
  con tutti `null`; le altre 14 forme falliscono chiuso. Passano contratto,
  API e socket Host (`54 passed`), suite backend completa (`195 passed`), suite
  collector/runtime/systemd (`29 passed`), test UI Host (`9 passed`), build
  frontend, Ruff mirato, configurazione Compose, esempio JSON e diff-check.
  Confermate compatibilità output v1/v2 senza wrapper, config legacy v1 e v2
  non miscelabili, limiti, reason separati, privacy ricorsiva, output collector
  ancora v1 e assenza di nuove sonde o dipendenze di rete. L'immagine
  `backend-test` preesistente era obsoleta; la riesecuzione autorevole ha
  montato i sorgenti correnti e `deploy/`. Nessun deploy, commit o correzione.

- [x] IMP-HO-FU-02 | OWNER: SA-IMP | STATUS: DONE | Implementato lo scoring
  contestuale nel collector con selezione output per config: la v1 continua a
  produrre payload e semantica legacy, la v2 produce il contratto v2. Il
  campione bounded di `pswpin`/`pswpout` usa clock e sleep iniettabili, delta
  non negativi e failure `available=false` con risultati null. Swap occupata,
  pressione memoria o attività isolate sono al massimo warning; critical
  richiede pressione memoria e delta critical contestuali. Policy processo
  count/RSS valutano aggregati alle soglie inclusive, mentre gruppi non
  configurati restano visibili e neutrali. Listener senza policy, incluso
  wildcard, è warning; uno scope non consentito da una policy locale esplicita
  è critical senza modificare `external_reachability=not_assessed`. Ownership,
  scansioni o letture parziali restano partial/unknown e non diventano evidenza
  negativa; Docker unavailable resta unknown.
  File: `deploy/host-observability-collector.py` e relativi test host-side;
  semantica aggiornata in `docs/contracts/host-observability-v2.md`. Fixture
  deterministiche coprono swap alta senza pressione, pressione più I/O al
  boundary, campioni mancanti/parziali/reset/timeout, durata e sleep bounded,
  gruppi neutrali, count/RSS warning e critical, troncamento processi, wildcard
  default, policy listener violata, ownership/lettura TCP partial, Docker
  unavailable, envelope, dimensione e privacy.
  Evidenze/comandi SA-IMP: collector `34 passed`; suite collector/runtime/
  systemd `40 passed`; contratto/API/socket backend `54 passed`; suite backend
  completa `195 passed`; test UI Host `9 passed` e `npm run build` passano. Uno
  snapshot prodotto dal collector v2 è validato dall'adapter backend v2. Ruff
  mirato, `docker compose config --quiet`, esempio JSON, scansione assenza rete,
  verifica unico `Popen` ad argv fisso con `shell=False` e `git diff --check`
  passano. Nessuna soglia/path privato entra nel payload; nessun deploy, commit
  o attività HO-FU-03.
- [x] TEST-HO-FU-02-T1 | OWNER: SA-TEST | STATUS: PASSED | Scoring v2
  verificato indipendentemente. Riprodotti swap alta senza pressione né I/O,
  pressione con attività immediatamente sotto e alla soglia critical,
  campioni mancanti/parziali/reset/timeout, durata fuori budget, gruppi non
  configurati neutrali, policy count/RSS ai boundary inclusivi, precedenza
  critical, wildcard senza policy, policy locale allowed/violated, ownership e
  letture TCP parziali, Docker indisponibile e propagazione all'envelope. Una
  matrice esterna ai test del SA-IMP ha inoltre prodotto snapshot v1 e v2 e li
  ha validati direttamente con l'adapter backend, confermando forma legacy v1,
  `external_reachability=not_assessed`, limiti e response sotto 128 KiB.
  Passano suite host-side completa (`40 passed`), backend corrente (`195
  passed`), test UI Host (`9 passed`), build frontend, Ruff mirato, Compose,
  esempio JSON, scansioni privacy/rete, unico `Popen` ad argv controllato con
  `shell=False` e diff-check. La prima esecuzione host-side ha incontrato la
  race già nota della fixture timeout sul file PID; il test è passato due volte
  isolatamente e l'intera suite è poi passata pulita. Nessun deploy, commit o
  correzione eseguito.

- [x] IMP-HO-FU-03 | OWNER: SA-IMP | STATUS: DONE | Dopo il `PASSED` del
  gate collector, aggiornare la vista Host per presentare separatamente fatti,
  valutazione e dati non accertati. La UI non deve chiamare un endpoint nuovo,
  aggiungere polling o descrivere `not_assessed` come sicuro/chiuso; refresh,
  stato stale, permessi admin-only ed export JSON byte-per-byte devono restare
  invariati. Aggiungere test browser/mobile per v1 legacy, v2, stati misti,
  testi non fuorvianti, copia/fallback e assenza di overflow. Non eseguire
  deploy. Implementata presentazione distinta di fatti locali, valutazione e
  dati non accertati, con fallback v1 e vista v2 di tutti i bind locali senza
  inferenze sulla raggiungibilità esterna. Restano invariati endpoint unico,
  caricamento on-open/refresh manuale, stale, gating admin ed export esatto.
  Aggiunti test nativi e browser Chromium a 320 px per v1/v2, stati misti,
  ruoli, accessibilità/touch target, semantica, copia/fallback, refresh/stale,
  zero polling Host e zero overflow. Evidenze SA-IMP: `npm run test:host` 11/11,
  `npm run test:host:browser` exit 0, `npm run build` e `git diff --check`
  passano. Aggiornati architettura e gate; nessun deploy, commit, FU-04 o
  `LATEST_RELEASE`.
- [x] TEST-HO-FU-03-T1 | OWNER: SA-TEST | STATUS: FAILED | Verifica
  indipendente eseguita senza deploy o correzioni. Passano test UI statici
  (`11 passed`), build frontend, diff-check e una sessione Chromium reale a 320
  px con exit 0 per v1/v2, ruoli, focus, touch target, overflow, export
  deep-equal, clipboard/fallback, refresh e zero polling; un secondo probe
  Chromium indipendente conferma stale, live region/ARIA e zero fetch extra.
  Restano due blocker semantici/test. `HostCard` mostra «Nessuna anomalia
  rilevata dai controlli disponibili» per ogni componente con `reasons=[]`,
  anche quando `status` è `unknown`, `warning` o `critical`: l'assenza di un
  dettaglio viene quindi presentata come esito rassicurante e viola il vincolo
  unknown non equivalente a safe. Inoltre le fixture browser dichiarate v1/v2
  usano i reason non ammessi dal contratto `unexpected_tcp_listener` e
  `listener_policy_violation`, perciò non rappresentano payload che il backend
  potrebbe realmente pubblicare. Il primo avvio Chromium senza preview ha
  prodotto `ERR_CONNECTION_REFUSED`; con preview esplicito la sessione si è
  conclusa correttamente. Nessun commit o modifica applicativa eseguito.

- [x] IMP-HO-FU-03-R1 | OWNER: SA-IMP | STATUS: DONE | Rendere il
  fallback della valutazione coerente con lo stato: il testo rassicurante è
  ammesso soltanto per `ok`; `unknown` deve dichiarare che la valutazione non è
  disponibile/non accertata, mentre warning e critical senza reason non devono
  dire che non esistono anomalie. Aggiungere casi browser reali per tutti e
  quattro gli status con `reasons=[]`. Correggere le fixture usando esclusivamente
  reason v1/v2 ammessi (`wildcard_listener_unexpected` o
  `tcp_listener_unexpected` secondo il caso) e aggiungere un controllo che ne
  impedisca la divergenza dal contratto. Conservare invariati endpoint, export,
  ruoli, fetch e semantica `not_assessed`. Non eseguire deploy. Rework
  completato: `HostCard` usa una matrice esplicita per i quattro status e
  riserva «Nessuna anomalia» al solo `ok`; `warning` e `critical` dichiarano lo
  stato senza inventare un dettaglio, mentre `unknown` dichiara la valutazione
  non disponibile/non accertata. Le fixture browser v1 e v2 sono JSON
  condivisi, usano soltanto reason code ammessi e vengono validate dall'adapter
  Pydantic autorevole. Regressioni: matrice completa in Chromium a 320 px e
  test nativo; validazione fixture nel test contratto. Evidenze SA-IMP:
  contratto `21 passed`; UI `12 passed`; build frontend, Chromium completo exit
  0 e `git diff --check` passano. Nessun deploy, commit, FU-04 o modifica a
  `LATEST_RELEASE`.

- [x] TEST-HO-FU-03-T2 | OWNER: SA-TEST | STATUS: PASSED | Rework verificato
  indipendentemente. La matrice reale Chromium dei componenti `ok`, `warning`,
  `critical` e `unknown` con reason vuoti riserva «Nessuna anomalia» al solo
  `ok`; gli altri stati dichiarano rispettivamente attenzione, criticità o
  valutazione non disponibile/non accertata. Le fixture JSON condivise v1 e v2
  superano l'adapter Pydantic autorevole e non contengono più reason fuori
  schema. Passano contratto Host (`40 passed`), test UI (`12 passed`), build
  frontend, JSON e diff-check. La sessione Chromium completa a 320 px termina
  con exit 0 e conferma v1/v2 e stati misti, fatti/policy/not-assessed, ruoli
  viewer/operator senza CTA o fetch Host, focus/ARIA, touch target, overflow,
  refresh, zero polling, export deep-equal e clipboard/fallback. Un secondo
  probe Chromium indipendente con exit 0 conferma ritorno del focus al trigger,
  stale dopo 503, live region e conteggio fetch invariato. Documentazione e
  gate restano coerenti; nessun deploy, commit o correzione eseguito.

- [x] IMP-HO-FU-04 | OWNER: SA-IMP | STATUS: DONE | Dopo il `PASSED` UI,
  eseguire hardening e preflight completi: test collector/contract/API/UI,
  suite backend e build frontend, lint/diff-check, Compose config, gate privacy,
  systemd security e test socket concorrenti/one-shot. Documentare separatamente
  eventuali failure infrastrutturali preesistenti; aggiornare il gate live con
  matrici v1/v2 e rollback. Nessun deploy e nessun commit. Preflight SA-IMP
  completato: collector/runtime/systemd `40 passed`; contratto/API/socket/tmux
  mirati `75 passed`; suite backend `178 passed` con mount `/deploy:ro`; UI
  `12 passed`; build locale e `frontend-build` Compose passano; Chromium reale
  a 320 px termina con exit 0. Passano lint Host mirato, tre configurazioni
  Compose, JSON/esempi, privacy ricorsiva, unico endpoint nel bundle senza
  sourcemap, `systemd-analyze verify`, test statici delle unit e probe user
  reale con `CapPrm/CapEff/CapAmb=0`, AF_UNIX consentito e AF_INET bloccato.
  Verificati concorrenza socket, one-shot bounded, timeout/128 KiB, assenza di
  client rete, unico `Popen` con argv Docker fisso e `shell=False`, compatibilità
  config/output/API/UI v1-v2 e fallback v1. Gate live aggiornato con matrice e
  ordine atomico di deploy/rollback che preserva `tmux-runtime`.
  Failure infrastrutturali separate: il comando Compose backend standard si
  ferma a `177 passed, 1 failed` perché non monta il collector rate-limit in
  `/deploy`; la stessa suite passa interamente con il mount read-only. Ruff
  senza `--no-cache` non può creare `.ruff_cache` nel container read-only; con
  `--no-cache` il perimetro Host passa. Il lint globale segnala soltanto import
  non ordinati in `app/main.py` non modificato e `app/schemas.py` modificato da
  lavoro utente estraneo al round; non sono regressioni Host e non sono stati
  riscritti. L'analisi security offline assegna livello MEDIUM e interpreta le
  user unit come root; verify, assert unit e probe sul vero user manager
  confermano invece gli invarianti applicabili. `git diff --check` passa.
  Nessun deploy, commit, FU-05 o modifica a `LATEST_RELEASE`.
- [x] TEST-HO-FU-04-T1 | OWNER: SA-TEST | STATUS: FAILED | Preflight
  indipendente eseguito senza deploy o correzioni. Passano backend completo sui
  sorgenti correnti con mount espliciti (`197 passed`), host-side (`40 passed`),
  socket/API/contratto mirati (`56 passed`), UI (`12 passed`), build locale e
  Compose, Chromium reale a 320 px con exit 0, tre config Compose,
  `systemd-analyze --user verify`, security offline, probe transitorio sul vero
  user manager con capability nulle e AF_INET bloccato, JSON, privacy/rete,
  unico `Popen` Docker con `shell=False`, bundle con un solo endpoint, mount
  backend senza `/proc`/`/sys`/socket Docker e diff-check. Confermati matrice
  v1/v2, limiti socket/concorrenza/timeout, ordine atomico deploy/rollback e
  preservazione di `tmux-runtime`. Il comando backend standard riproduce il
  failure infrastrutturale già noto per `/deploy/rate-limit-collector.py`
  assente (`177 passed, 1 failed`).
  Il gate fallisce però tre regressioni di ripetibilità del round: (1) Ruff
  Host mirato segnala `I001` nel file modificato
  `backend/tests/test_host_observability_contract.py`; (2) il comando Ruff
  deploy scritto nel gate usa i path inesistenti
  `/deploy/tests/test_host-observability_runtime.py` e
  `/deploy/tests/test_host-observability_systemd.py`, quindi termina con `E902`; con i nomi
  reali underscore il lint passa; (3) i nuovi test delle fixture cercano
  `/frontend/tests/fixtures`, non disponibile nel servizio `backend-test` e
  non dichiarato dal comando automatico. Su sorgenti correnti senza mount ad
  hoc il contratto termina `38 passed, 2 failed`; il pass completo richiedeva
  un mount frontend extra non documentato. Il lint globale aggiunge al nuovo
  `I001` soltanto i due casi preesistenti in `app/main.py` e `app/schemas.py`.
  Inventario dirty-worktree invariato; nessun commit o mutazione applicativa.

- [x] IMP-HO-FU-04-R1 | OWNER: SA-IMP | STATUS: DONE | Rendere il
  preflight eseguibile da ambiente pulito con i comandi dichiarati: correggere
  l'import formatting del test contratto; correggere nel gate i due nomi file
  deploy con underscore; rendere le fixture v1/v2 accessibili al
  `backend-test` standard senza mount manuali non documentati, tramite una
  collocazione condivisa inclusa nell'immagine/test context oppure un volume
  read-only esplicito nella configurazione Compose. Il test browser e il test
  Pydantic devono continuare a leggere gli stessi file, senza duplicazione che
  possa divergere. Rieseguire comando backend standard e autorevole sui
  sorgenti correnti, Ruff Host/deploy, tre Compose config e diff-check; separare
  ancora il solo failure rate-limit preesistente se non corretto in questo
  round. Non eseguire deploy o commit. Rework completato: import del test
  contratto ordinati; gate Ruff allineato ai file deploy reali con underscore;
  fixture JSON condivise montate in sola lettura esclusivamente nel profilo
  `backend-test`, senza estendere il backend di produzione. Un test statico
  verifica source, target, read-only e isolamento dal servizio runtime.
  Immagine test ricostruita dai sorgenti correnti. I comandi documentati senza
  override passano: Host API/socket/contratto `56 passed`, Ruff Host e Ruff
  deploy verdi, host-side `41 passed`; test contratto fixture `40 passed`. UI
  `12 passed`, build locale e Compose, Chromium 320 px exit 0, tre Compose
  config e verifica del mount risolto passano. La suite backend standard arriva
  a `196 passed, 1 failed`: resta esclusivamente il failure preesistente del
  rate-limit collector per `/deploy` assente; con il relativo mount read-only
  passa `197 passed`. `git diff --check` passa. Nessun deploy, commit, FU-05 o
  modifica a `LATEST_RELEASE`.

- [x] TEST-HO-FU-04-T2 | OWNER: SA-TEST | STATUS: PASSED |
  Dopo il rework, ripetere l'intero preflight T1 da ambiente pulito, verificando
  in particolare che fixture e lint passino con i comandi documentati senza
  mount SA ad hoc. Un nuovo failure crea `IMP-HO-FU-04-R2` e
  `TEST-HO-FU-04-T3`. Solo `PASSED` può sbloccare `IMP-HO-FU-05`.
  Non eseguire deploy. Verifica indipendente completata: il comando standard
  API/socket/contratto passa `56` test senza mount ad hoc; Ruff Host e deploy
  passano con i path documentati; le fixture condivise sono montate read-only
  soltanto in `backend-test` e sono assenti dal backend runtime. La suite
  backend standard conferma `196 passed, 1 failed`, con il solo failure
  preesistente del rate-limit collector dovuto a `/deploy` assente; con il
  relativo mount read-only passa `197 passed`. Passano inoltre i `41` test
  host-side, i `12` test UI, build locale e Compose, test Chromium a 320 px
  (v1/v2, ruoli, copia e refresh), tre configurazioni Compose, verifica unità
  systemd e probe dinamico con capability nulle/solo `AF_UNIX`. Gli audit su
  payload reale v2, rete, argv Docker, limiti socket, rollback e preservazione
  tmux sono conformi; il bundle contiene una sola occorrenza dell'endpoint e
  `git diff --check` passa. Nessun deploy, commit o modifica applicativa
  eseguiti da SA-TEST.

- [x] IMP-HO-FU-05 | OWNER: SA-IMP | STATUS: DONE | Dopo autorizzazione del
  preflight, installare atomicamente collector/config compatibile e ricreare
  soltanto gli stateless necessari secondo il gate aggiornato. Registrare prima
  e dopo unit, container, health, socket e identità/sessioni tmux; preservare
  sempre `tmux-runtime`. Verificare rollback v1, snapshot reale v2, export JSON
  e continuità operativa. Solo dopo la validazione di implementazione aggiornare
  `LATEST_RELEASE` alla funzionalità effettivamente pubblicata e creare il check
  live SA-TEST. Nessun commit. Deploy host-tmux completato secondo gate.
  Baseline e confronto finale privati confermano quattro sessioni tmux con hash
  invariato e container `tmux-runtime` con ID/creazione/stato invariati; sono
  stati ricreati esclusivamente backend/web con overlay e `--no-deps`, poi il
  solo web per la release note. Config v1 mode `0600`, collector dual-stack e
  unit sono stati validati prima del rollout; passano snapshot/socket/API live
  v1 e rollback atomico v2→v1→v2. Snapshot reale v2 strict resta sotto 128 KiB
  e mostra correttamente i casi HO-FU-01: swap alta senza attività è warning,
  gruppi senza policy neutrali, wildcard non configurate warning,
  `listeners_partial` conservato, raggiungibilità sempre `not_assessed` e
  Docker indisponibile unknown. Passano privacy ricorsiva, quattro client
  concorrenti e one-shot reaped, anonimo 401, admin 200, viewer/operator 403 e
  flag nascosto, rate limit `6×200 + 429/Retry-After`, socket assente 503 e
  timeout bounded 504; ogni configurazione temporanea è stata ripristinata.
  Per il gate ruoli live sono stati usati utenti univoci transitori e cookie
  firmati nel backend senza esporre credenziali; cleanup verificato a conteggio
  zero. I casi partial/unknown sono riproducibili sullo snapshot reale corrente
  e le fixture condivise v1/v2 restano disponibili per i casi deterministici.
  Il probe riusabile `frontend/tests/host-observability-live.mjs`, alimentato
  solo via `MAC_LIVE_BASE_URL` e `MAC_LIVE_ADMIN_PASSWORD`, passa a 320 px con
  export deep-equal, clipboard, refresh e zero polling. `LATEST_RELEASE` ora
  descrive la semantica contestuale v2; dopo la ricreazione del solo web il
  bundle live contiene la release note e una sola occorrenza dell'endpoint,
  health è 200 e backend non è stato ricreato. Config finale v2, timeout 3,
  prepare/socket/app host active, nessuna one-shot pendente, nessun file/utente
  temporaneo e backup di rollout rimosso dopo la validazione. `git diff
  --check` passa. Nessun commit.
- [x] TEST-HO-FU-05-T1 | OWNER: SA-TEST | STATUS: FAILED | Collaudo finale
  indipendente sull'istanza pubblicata: contratto/privacy, casi reali che hanno
  originato HO-FU-01, stati partial/unknown, ruoli, rate limit, mobile, export,
  assenza di polling, socket activation, rollback e continuità tmux. Solo un
  `PASSED` autorizza ROOT al commit finale; ogni failure crea rework e un nuovo
  check numerato. Snapshot reale v2 strict e deep-equal sotto 128 KiB, privacy,
  scoring HO-FU-01, stati partial/unknown, facts/policy/not_assessed, health,
  bundle e release note passano. Passano inoltre RBAC live con utenti transitori
  viewer/operator poi rimossi, rate limit `6×200 + 429/Retry-After`, quattro
  client socket concorrenti, `503` a socket assente e `504` bounded a circa 3
  secondi; socket/configurazione finali sono stati ripristinati. Le quattro
  sessioni tmux `$162`, `$147`, `$135`, `$152` e il runtime restano continui;
  soltanto backend/web stateless risultano ricreati.
  Il gate fallisce due aspetti collegati del percorso mobile/refresh. Il test di
  validazione live `frontend/tests/host-observability-live.mjs` termina con exit
  `1`: il listener asincrono della risposta invoca `response.json()` dopo la
  chiusura del context al refresh finale. L'abort della stessa richiesta lascia
  inoltre una unità collector one-shot in stato `failed`, con
  `BrokenPipeError` sull'`os.write(1, payload)`, invece di concludere e sparire
  senza errore. Lo stato failed transitorio è stato pulito esclusivamente con
  `systemctl --user reset-failed`; socket active/listening, health/tmux e
  `git diff --check` sono nuovamente verdi. Nessuna correzione, deploy o commit
  eseguiti da SA-TEST.

- [x] IMP-HO-FU-05-R1 | OWNER: SA-IMP | STATUS: DONE | Rendere deterministico
  il probe live: attendere e consumare la risposta del refresh prima di chiudere
  page/context, e impedire che il listener asincrono produca rejection dopo il
  teardown. Il comando deve terminare ripetutamente con exit `0` e continuare a
  verificare 320 px, v2, export deep-equal, clipboard/fallback, refresh, stale e
  assenza di polling. Rendere inoltre il collector robusto alla disconnessione
  del client durante la scrittura del payload: `BrokenPipeError` non deve
  produrre traceback né lasciare una one-shot systemd failed. Aggiungere test di
  validazione automatici sia per l'errore di scrittura sia per l'abort live,
  rieseguire preflight mirato e collaudo pubblicato, pulire le unità transitorie
  e verificare che socket/config v2, health, container e sessioni tmux restino
  invariati. Non eseguire commit. Rework completato. Il probe live conta le
  request con listener sincrono e attende esplicitamente
  `waitForResponse`, `json()` e `finished()` sia all'apertura sia al refresh
  prima del teardown; verifica inoltre deep-equal dopo refresh e fallback
  clipboard. `MAC_LIVE_ITERATIONS` esegue fino a dieci cicli nello stesso
  processo e `MAC_LIVE_ABORT_REFRESH=1` riproduce la chiusura controllata del
  consumer. Il collector usa una write completa che tratta soltanto
  `BrokenPipeError` come normale disconnect; write parziali sono completate e
  gli altri `OSError` restano fail-closed. Test automatici coprono clean exit e
  propagazione degli errori reali. Evidenze: collector/runtime/systemd `43
  passed`, collector mirato `36 passed`, backend Host `56 passed`, UI `13
  passed`, build, Ruff e diff-check verdi. Il probe live corretto passa tre
  volte separate e poi `3×` nello stesso processo, sempre exit 0. Un abort
  browser live e un disconnect Unix diretto terminano entrambi con
  `one_shot_failed=0`, `one_shot_running=0`, journal senza traceback e senza
  usare `reset-failed`. Il collector è eseguito direttamente dal checkout
  installato, quindi non è stato necessario ricreare stateless o unit; nessun
  container è stato toccato. Config finale v2 mode 0600/campione 100 ms,
  timeout backend 3, app host/prepare/socket active, health 200 e hash delle
  quattro sessioni tmux invariato. Nessun file/utente temporaneo, deploy
  aggiuntivo, modifica a `LATEST_RELEASE` o commit.

- [x] TEST-HO-FU-05-T2 | OWNER: SA-TEST | STATUS: PASSED | Dopo il rework,
  ripetere indipendentemente il probe Chromium live più volte e abortire una
  richiesta Host in corso; verificare exit `0`, nessuna rejection, nessuna unità
  one-shot failed/pending, socket activation ancora operativa e continuità di
  health, config v2, container e tmux. Solo `PASSED` autorizza ROOT al commit e
  alla notifica finale; ogni nuovo failure crea `IMP-HO-FU-05-R2` e
  `TEST-HO-FU-05-T3`. Verifica indipendente completata: il probe live con
  `MAC_LIVE_ITERATIONS=3` termina con exit `0` e attende response, `json()` e
  `finished()` sia all'apertura sia al refresh, mantenendo export deep-equal,
  clipboard/fallback, mobile 320 px e zero polling. L'abort-refresh reale passa
  con exit `0`; senza usare `reset-failed` risultano
  `one_shot_failed=0`, `one_shot_running=0`, socket active e journal del nuovo
  intervallo senza `BrokenPipeError` o traceback. Passano inoltre test
  host-side `43`, backend Host `56`, UI `13`, build e Ruff; snapshot live v2
  strict/deep-equal/privacy sotto 128 KiB con scoring HO-FU-01,
  partial/unknown, facts/policy e reachability `not_assessed`; anonimo/admin,
  viewer/operator con cleanup a zero, rate limit `6×200 + 429/Retry-After`,
  quattro client concorrenti, `503` e `504` bounded con socket ripristinato.
  Il rollback v2→v1→v2 già validato sullo stesso deploy non è stato riaperto,
  poiché il rework non modifica configurazione o unità. Bundle live e
  `LATEST_RELEASE` coincidono e contengono una sola occorrenza dell'endpoint;
  config finale v2 mode `0600`, prepare/socket, health/tmux, container backend
  e web restano invariati. Le sessioni `$162`, `$147`, `$135`, `$152` conservano
  hash `e005776172c24bcd08934c95961ee2dd8f6690ebd783611898b7060c1a74deac`.
  Tre config Compose e `git diff --check` passano; nessun residuo temporaneo,
  correzione, deploy o commit eseguito da SA-TEST. ROOT è autorizzato alla
  notifica e al commit finale.

### HO-UX-01 — Sezioni Host richiudibili

- [x] IMP-HO-UX-01 | OWNER: ROOT | STATUS: DONE | Convertite le sette schede
  di dettaglio Host in `details` chiusi di default: titolo e badge di stato
  restano visibili, mentre valutazione, metriche e liste processi compaiono
  all'apertura. Anche la guida di lettura è richiudibile; riepilogo complessivo
  ed export JSON conservano la propria semantica. Aggiornati test statici,
  browser e live, oltre a `LATEST_RELEASE`.
- [x] TEST-HO-UX-01-T1 | OWNER: ROOT | STATUS: PASSED | Test UI `14/14`, build
  frontend e Chromium fixture a 320 px passano. Il gate live conferma sette
  schede chiuse all'apertura, lista gruppi nascosta fino al tap, apertura del
  dettaglio, export deep-equal, clipboard, refresh e assenza di polling. Deploy
  eseguito ricreando esclusivamente `web`; backend e quattro sessioni tmux sono
  invariati. `git diff --check` passa.

### SESSION-UX-01 — Nomi Unicode e continuità della console

- [x] IMP-SESSION-UX-01 | OWNER: ROOT | STATUS: DONE | I nomi di sessione
  accettano lettere e numeri Unicode con normalizzazione NFC, mantenendo limite
  di 64 caratteri, separatori ammessi e target tmux esclusivamente numerici.
  Le bozze testuali sono conservate separatamente per session id durante i
  cambi console; per Codex e Claude è disponibile `Clear`, inviato come testo
  seguito da `Enter` separato. Aggiornati contratti, documentazione pubblica,
  test UI e `LATEST_RELEASE`.
- [x] TEST-SESSION-UX-01-T1 | OWNER: ROOT | STATUS: PASSED | Backend mirato
  `96 passed`, Ruff, test UI `17/17`, build frontend, fixture Chromium mobile e
  tre configurazioni Compose passano. Il deploy ha ricreato soltanto backend e
  web; health e gate browser Host live passano e le quattro sessioni tmux sono
  rimaste invariate. La scansione delle modifiche non rileva secret, chiavi,
  host/IP, percorsi locali o riferimenti a infrastrutture private.

---

## Storico del consumo di budget e attribuzione per sessione

**Nota di verifica del 03/08/2026.** Esito `FAILED`: la suite backend conta
`267 passed, 15 failed` (il collector BH-04 non è incluso nell'immagine di
test e due asserzioni del config non sono aggiornate), mentre deploy è
`59/59`, frontend `55/55` con build riuscita e Ruff è pulito con cache
disabilitata. Il deployment corrente è sano (`/health` 200 con tmux `ok`,
login e sessione autenticata 200 dall'interno del backend), ma non contiene
BH-04: flag assente ed endpoint timeline `404`. Il collector non committato,
provato su un bucket reale Claude e uno Codex, ha restituito solo i metadati
ammessi, senza campi extra né percorsi; non esiste un payload timeline
persistito. Il working tree resta intenzionalmente sporco con l'implementazione
BH-04 in corso, `main` è avanti di 6 commit e non risultano branch non
mergiati. Scostamento documentale: il riepilogo di sezione qui sotto dichiara
ancora `IMP-BH-04` `READY` e non preso in carico, mentre la voce autorevole è
`IN_PROGRESS`; `TEST-BH-04` resta correttamente `BLOCKED`.

**Stato: fasi A e B verificate (con un rework ciascuna), `PASSED`. Fase
BH-03 (proprietà dello strato quote e segnale sul fallback) chiusa `PASSED`
dopo un rework. Fase C (`BH-04`) chiusa `PASSED` dopo un rework, anch'essa:
implementata, deployata e verificata in esercizio — flag
`MAC_SESSION_TIMELINE_ENABLED` acceso, unit installate, endpoint attivo.
`TEST-BH-04` è chiusa `FAILED` (parametro di query assente → `500` invece di
`422`), il rework `IMP-BH-04-R1` è `DONE` e `TEST-BH-04-T2` è `PASSED`.
Con tutte e cinque le fasi chiuse, questa sezione non ha voci aperte.**
Nota trasversale: le tre fasi che hanno richiesto un rework sono state
scoperte da `SA-TEST`, mai dalle suite dell'implementatore, che erano verdi in
tutti e tre i casi.
Decisioni e contratto in
`docs/adr/010-storico-consumo-budget.md` e
`docs/contracts/budget-history-v1.md`; non riaprire né contraddire quei
documenti da questa coda. Segue lo stesso protocollo dei subagent già in uso
per `HO-*` (vedi sopra, "Protocollo della roadmap per i subagent"): nomi
logici `ROOT`/`SA-IMP`/`SA-TEST`, `STATUS` come esito autorevole, rework con
suffisso `-R<n>` e nuovo check `-T<n+1>` a ogni fallimento.

#### BH-00 — Gate prodotto e decisioni

- [x] GATE-BH-00 | OWNER: ROOT | STATUS: PASSED | Piano approvato
  dall'utente il 02/08/2026. Confini approvati: fase A (storico della quota
  globale) e fase B (attribuzione per sessione) autorizzate ora; il
  drill-down sul contenuto dei turni resta esplicitamente fuori da questo
  round ed è rimandato a una fase C separata, non avviata e non pianificata.
  `IMP-BH-01` attivato.

#### BH-01 — Storico della quota globale (fase A)

- [x] IMP-BH-01 | OWNER: SA-IMP | STATUS: DONE | Implementati collector,
  boundary e API dello storico quota. `deploy/rate-limit-collector.py` prova
  prima la forma strutturata `--json` e ricade sul parsing testuale storico
  quando lo script non la offre; continua a scrivere lo snapshot
  `provider-rate-limits.json` con contratto invariato e in più appende
  `provider-rate-limits-history.jsonl` con `resets_at` epoch, marcatura
  `stale`, deduplica dei campioni identici consecutivi, rotazione e ritenzione
  14 giorni, permessi `0600`. Le unit
  `mobile-agent-console-rate-limit-fresh.socket`/`@.service` aggiungono
  l'aggiornamento forzato on-demand via socket activation, riusando la
  directory runtime e la unit di preparazione ACL dell'osservabilità host;
  l'hardening diverge da quella unit per tre ragioni documentate nel file
  stesso (scrittura sotto `MAC_WORKSPACE_ROOT` non esprimibile in
  `ReadWritePaths` con variabili da `EnvironmentFile`, lettura della home per
  le credenziali dello script quote, famiglie di indirizzi che includono
  `AF_INET`/`AF_INET6` perché il campione fresh deve poter interrogare il
  provider). `compose.budget-history.yaml` è l'overlay opt-in. Backend:
  `jsonl_tail.py` (lettura coda tollerante a righe troncate),
  `rate_limit_history_service.py`, `unix_socket_json_client.py` (base
  generica estratta dal client host-observability), `rate_limit_fresh_client.py`,
  endpoint `GET /api/v1/provider-rate-limits/history` (sessione attiva) e
  `POST /api/v1/provider-rate-limits/refresh` (admin, opt-in con `404` se
  disattivato, rate limit dedicato, errori tipizzati `429`/`503`/`504` senza
  dettagli grezzi del collector). Suite backend: 218 passati, 0 falliti, ruff
  pulito; baseline precedente 196 passati e 1 fallito.
- [x] TEST-BH-01 | OWNER: SA-TEST | STATUS: FAILED | Comandi automatici
  tutti verdi e non peggiorativi rispetto alla baseline: 236 test backend
  (baseline 232; +18 dovuti a `test_budget_history_hardening.py` di
  `ce507d1`), 0 falliti, ruff pulito; 58/58 `python3 -m unittest discover -s
  deploy/tests`; 35/35 test frontend (`test:host` 14 + `test:budget` 18 +
  `test:console` 3), build `tsc -b && vite build` pulita; test mirati del
  gate (44 su `test_rate_limit*`, `test_session_usage*`,
  `test_budget_history_hardening.py`) passati; `systemd-analyze --user
  verify` sulle unit fresh pulito; `docker compose config --quiet` valido in
  modalità docker e host, con e senza overlay `compose.budget-history.yaml`
  (4 combinazioni); `git diff --check` pulito. Grep di privacy su
  `.mobile-agent-console/provider-rate-limits-history.jsonl` reale (80 righe,
  timer già attivo su questo host) senza corrispondenze a prompt/risposte/
  transcript_path/pid/home/root; permessi `600`, proprietario host; lo
  snapshot `provider-rate-limits.json` mantiene lo schema originale, nessun
  campo aggiunto. Fallisce però l'attacco esplicitamente richiesto sui
  "timestamp non UTC": il contratto (`docs/contracts/budget-history-v1.md`,
  "Forma comune") impone che le righe con timestamp non UTC vengano
  scartate, ma `RateLimitSample.sampled_at` con un offset esplicito non-UTC
  (es. `+02:00`, non un caso naive) viene accettato invece che scartato, e
  `observed_at` non è affatto validato come timestamp (campo `str` libero).
  Non è un caso sintetico: sul file reale del timer in esecuzione 7 righe su
  80 hanno `observed_at` in ora locale di Roma (`+02:00`) contro le 73 in
  UTC, prodotte dal ramo di parsing testuale storico di
  `deploy/rate-limit-collector.py` che copia l'output dello script quote
  verbatim. Riproduzione: `docker compose run --rm backend-test python -c
  "from app.services.rate_limit_history_service import RateLimitSample;
  s=RateLimitSample.model_validate({'sampled_at':'2026-08-02T21:07:21+02:00','provider':'codex','windows':[]});
  print(s.sampled_at, s.sampled_at.tzinfo)"` stampa il valore con offset
  `+02:00` invece di sollevare/scartare la riga. Nessun 500 e nessun valore
  inventato in nessun caso provato (righe non-JSON, non-oggetto, troncate,
  percentuali fuori `0..100`, conteggi negativi, file assente/vuoto): il
  difetto è circoscritto al mancato rispetto dell'invariante UTC dichiarato.
- [x] IMP-BH-01-R1 | OWNER: SA-IMP | STATUS: DONE | Riferimento:
  `TEST-BH-01`. Atteso: una riga con timestamp in un fuso diverso da UTC
  viene scartata dal parsing (o il contratto viene corretto esplicitamente
  per ammettere/normalizzare offset non-UTC, se quella è la scelta voluta —
  la tolleranza documentata nel commit `ce507d1` copre solo i timestamp
  naive, non un offset esplicito). Ottenuto: `RateLimitSample.sampled_at`
  con `+02:00` accettato e restituito con l'offset originale invece di UTC;
  `observed_at` non tipizzato/validato come timestamp; il ramo
  `parse_text` di `deploy/rate-limit-collector.py` copia `observed_at`
  dallo script quote senza normalizzarlo, producendo nel file reale del
  timer 7 righe su 80 in ora locale. Stesso pattern di validazione
  (`require_utc`) in `SessionUsageRow.bucket_start`
  (`session_usage_service.py`), quindi la correzione va applicata in modo
  coerente a entrambi i modelli. Comando di riproduzione: vedi `TEST-BH-01`.
  Aggiungere un test di regressione che verifichi lo scarto (o la
  normalizzazione, se il contratto viene corretto in tal senso) di un
  timestamp con offset esplicito non-UTC, non solo del caso naive già
  coperto.

  Fatto: `require_utc` in `rate_limit_history_service.py` e in
  `session_usage_service.py` (stesso pattern in entrambi) ora solleva
  `ValueError` quando il timestamp ha un `tzinfo` con offset esplicito
  diverso da UTC (`value.utcoffset() != timedelta(0)`), lasciando invariata
  la normalizzazione del caso naive. Il chiamante in entrambi i servizi già
  catturava `ValidationError` e scartava la riga (`continue`): non è stato
  necessario toccare la logica di lettura. `observed_at` resta `str | None`
  non tipizzato, fuori scope come annotato sopra (coerente con lo stesso
  pattern già in uso in `rate_limit_status_service.py` e
  `orchestrator_state_service.py`, non specifico di questo rework). Aggiunto
  `test_non_utc_offset_timestamp_is_discarded` in
  `backend/tests/test_rate_limit_history_service.py` e in
  `backend/tests/test_session_usage_service.py`, entrambi con lo stesso
  timestamp d'attacco usato nella riproduzione di `TEST-BH-01`.
- [x] TEST-BH-01-T2 | OWNER: ROOT | STATUS: PASSED | Verifica di chiusura
  eseguita direttamente da ROOT (non da un subagent SA-TEST dedicato):
  riprodotto esattamente il comando di `TEST-BH-01`
  (`RateLimitSample.model_validate({'sampled_at':'2026-08-02T21:07:21+02:00',...})`)
  dentro `docker compose run --rm backend-test`, ora solleva
  `ValidationError` invece di accettare l'offset. `docker compose run --rm
  backend-test` (rebuild dell'immagine incluso): 238 passati, 0 falliti (236
  di baseline + 2 nuovi test di regressione), `ruff check .` pulito
  (`All checks passed!`). `docker compose config --quiet` valido sia in
  modalità docker sia in modalità host (`compose.host.yaml`).

#### BH-02 — Attribuzione per sessione (fase B)

- [x] IMP-BH-02 | OWNER: SA-IMP | STATUS: DONE | Collector
  `deploy/session-usage-collector.py` che scopre i transcript per tempo di
  modifica (non per pane tmux), con lettura incrementale a cursori
  percorso/inode/offset, deduplica delle risposte per identificativo di
  richiesta, roll-up dei subagent sotto il `session_uuid` della sessione madre
  e distinzione `origin` fra `mac` e `headless`; endpoint
  `GET /api/v1/session-usage`. Al momento di questa voce risulta presente sul
  disco soltanto il modello Pydantic backend
  (`backend/app/services/session_usage_service.py`, `SessionUsageRow`); il
  collector host-side, il file storico `session-usage-history.jsonl` e
  l'endpoint API non risultano ancora presenti nell'albero. Il contratto in
  `docs/contracts/budget-history-v1.md` resta autorevole indipendentemente
  dallo stato di avanzamento.

  Nota di SA-TEST: questa voce non è mai stata chiusa `STATUS: DONE`, ma il
  collector, `session-usage-history.jsonl` e l'endpoint risultano già
  presenti e committati (`b55d56a`, precedente a questa stessa voce nella
  cronologia). ROOT ha chiesto esplicitamente in questa sessione di
  verificare e chiudere anche `TEST-BH-02`; si procede in deroga alla
  transizione `BLOCKED` → `READY_FOR_TEST` prevista dal protocollo, ma senza
  correggere questa voce, che resta di competenza di `SA-IMP`.

  Chiusura di `ROOT` (03/08/2026). Il corpo qui sopra descrive lo stato del
  disco **al momento in cui è stato scritto** ed è conservato per questo; non
  descrive lo stato di oggi. La voce era rimasta `IN_PROGRESS` mentre il
  lavoro era già committato in `b55d56a`, verificato da `TEST-BH-02` (fallito),
  corretto da `IMP-BH-02-R1` e chiuso `PASSED` da `TEST-BH-02-T2`: la catena
  autorevole era completa e solo l'intestazione della voce era rimasta
  indietro. Portata a `DONE` senza riscrivere i tentativi precedenti, come
  prevede il protocollo. Lezione registrata: un `STATUS` che nessuno chiude
  quando il lavoro finisce trasforma la coda in un documento da interpretare
  invece che da leggere — è lo stesso principio di `BH-03`, lo stato effettivo
  va dichiarato, non dedotto.
- [x] TEST-BH-02 | OWNER: SA-TEST | STATUS: FAILED | Comandi automatici
  verdi: i 20 test di `deploy/tests/test_session_usage_collector.py` (dentro
  i 58 deploy totali), `test_session_usage_api.py`, `test_session_usage_service.py`
  e i casi avversariali dedicati di `test_budget_history_hardening.py`
  (conteggi negativi scartati, roll-up subagent) tutti passati. Grep di
  privacy su `.mobile-agent-console/session-usage-history.jsonl` reale (58
  righe, collector già attivo su questo host) senza corrispondenze a
  prompt/risposte/transcript_path/pid/home/root; permessi `600`. Fallisce
  però l'attacco esplicitamente richiesto su un "file di cursori corrotto":
  un'entrata di cursore malformata per un singolo percorso (valore
  non-oggetto invece di `{"inode":...,"offset":...,"recent_request_ids":...}`)
  manda in eccezione non gestita `read_new_lines()` in
  `deploy/session-usage-collector.py`
  (`AttributeError: 'str' object has no attribute 'get'`), che risale fino a
  `collect()`/`main()` senza alcun try/except di livello superiore: l'intero
  ciclo del collector fallisce per tutti i file tracciati, non solo per
  quello con l'entrata corrotta, e poiché il crash avviene prima di
  `save_cursors()` la corruzione persiste e ripete il fallimento a ogni
  ciclo successivo del timer finché non si interviene a mano sul file dei
  cursori. Riproduzione:
  ```python
  import importlib.util, tempfile, os
  from pathlib import Path
  spec = importlib.util.spec_from_file_location("cli", "deploy/session-usage-collector.py")
  mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
  d = tempfile.mkdtemp()
  target = os.path.join(d, "transcript.jsonl")
  Path(target).write_text('{"a":1}\n')
  cursors = {target: "CORRUPTED-NOT-A-DICT"}  # simula load_cursors() su un file cursori corrotto
  mod.read_new_lines(Path(target), cursors.get(target))  # AttributeError non gestita
  ```
  Condivide inoltre con `TEST-BH-01` lo stesso difetto di validazione
  timestamp: `SessionUsageRow.bucket_start` usa lo stesso `require_utc` e
  accetta un offset esplicito non-UTC invece di scartare la riga (non
  ripetuto come motivo di fallimento separato per non duplicarlo).
- [x] IMP-BH-02-R1 | OWNER: SA-IMP | STATUS: DONE | Riferimento:
  `TEST-BH-02`. Atteso: un file di cursori con un'entrata malformata non
  deve mai interrompere l'intero ciclo del collector; al più va ignorata
  l'entrata corrotta per quel singolo percorso, ripartendo da cursore vuoto
  per quel percorso soltanto, coerentemente con la tolleranza già applicata
  a inode/dimensione disallineati in `read_new_lines`. Ottenuto:
  `AttributeError` non gestita quando il valore di `cursors.get(key)` non è
  un `dict`, propagata fino a `main()` senza cattura, con fallimento
  dell'intero ciclo per tutti i file. Comando di riproduzione: vedi
  `TEST-BH-02`. Validare che ogni valore restituito da `load_cursors()` sia
  un `dict` (scartando le entrate che non lo sono, invece di propagarle così
  come sono) è lo stesso principio fail-closed già applicato ai due JSONL
  pubblicati e va esteso qui. Aggiungere un test di regressione in
  `deploy/tests/test_session_usage_collector.py` che copra un cursore
  corrotto (valore non-dict) per un percorso, verificando che gli altri
  percorsi continuino a essere processati normalmente.

  Fatto: `load_cursors()` in `deploy/session-usage-collector.py` ora scarta
  (senza propagare) le entrate del dict top-level il cui valore non è a sua
  volta un `dict`, invece di limitarsi a validare solo il contenitore
  esterno. Firma invariata (`dict[str, dict[str, Any]]`, ora un tipo
  realmente garantito); `read_new_lines()` non toccata, non ne aveva
  bisogno. Aggiunto
  `test_corrupted_cursor_entry_is_dropped_for_its_path_only` in
  `deploy/tests/test_session_usage_collector.py`: un file di cursori con
  un'entrata corrotta (stringa) per un percorso e un'entrata valida per un
  secondo percorso, verifica che il ciclo successivo non sollevi eccezioni,
  che il percorso corrotto riparta da cursore vuoto (rilegge tutto il file)
  e che il percorso sano usi il proprio cursore salvato senza essere
  toccato dalla corruzione altrove nel file.
- [x] TEST-BH-02-T2 | OWNER: ROOT | STATUS: PASSED | Verifica di chiusura
  eseguita direttamente da ROOT (non da un subagent SA-TEST dedicato):
  riprodotto lo scenario esatto di `TEST-BH-02` (cursore corrotto per un
  percorso, valore stringa invece di oggetto) chiamando direttamente
  `load_cursors()`/`read_new_lines()` fuori da qualsiasi mock — l'entrata
  corrotta viene scartata da `load_cursors()`, `read_new_lines()` non
  solleva più `AttributeError` e il file viene riletto da zero come
  previsto. `python3 -m unittest discover -s deploy/tests`: 59 passati, 0
  falliti (58 di baseline + 1 nuovo test di regressione).

#### BH-03 — Proprietà dello strato quote e segnale osservabile sul fallback

- [x] GATE-BH-03 | OWNER: ROOT | STATUS: PASSED | Approvato dall'utente il
  02/08/2026 con una correzione di impostazione rispetto alla proposta
  originale, riportata in coda a questa voce sotto "Addendum". Il testo
  seguente resta come è stato scritto al momento della proposta: l'analisi
  del fallback silenzioso e il rifiuto dell'opzione 1 restano validi,
  l'addendum aggiunge la dimensione mancante. `IMP-BH-03` è sbloccato.

  Testo originale della proposta. Nel corso di un lavoro
  collaterale del 02/08/2026 (aggiunta di `--json` a `~/.codex/rate-limit.sh`,
  fuori da questa coda) è stato osservato dal vivo il fenomeno per cui questa
  voce propone un rimedio: prima della modifica, il collector produceva per
  Codex righe storiche con `resets_at: null` su tutte le finestre, perché lo
  script quote di Codex non offriva la forma strutturata e il collector
  ricadeva sul parsing testuale — esattamente il comportamento descritto in
  ADR 010 ("Conseguenze e limiti": «la sorgente strutturata delle
  percentuali vive fuori dal repository, negli script quote dell'utente. Il
  collector deve degradare al parsing testuale esistente quando lo script
  non offre la forma strutturata»). Questo non è in discussione: la voce non
  riapre né contraddice ADR 010, che accetta esplicitamente il fallback come
  comportamento voluto.

  Il problema è un secondo passo mai affrontato: quel fallback è silenzioso.
  `~/.claude/rate-limit.sh` e `~/.codex/rate-limit.sh` vivono fuori dal repo
  per costruzione — sono personalizzazioni di deployment coerenti con la
  regola di CLAUDE.md di non versionare dettagli di infrastruttura personale
  e con `customizations/`/`CLAUDE.local.md` in `.gitignore`; leggono
  credenziali OAuth locali e i transcript dell'utente, legati
  all'installazione personale degli strumenti sull'host, non al prodotto. Se
  uno dei due script viene sovrascritto, reinstallato o perde il supporto a
  `--json` in futuro, `deploy/rate-limit-collector.py:collect()` ricade in
  automatico su `parse_text()` (voluto) ma `resets_at` torna `null` per quel
  provider senza che nulla nel prodotto lo segnali: la serie storica smette
  silenziosamente di segmentare le finestre ai reset e nessuno se ne accorge
  finché non serve un'indagine su quei dati.

  Due opzioni valutate:

  1. **Versionare gli script nel repo** (es. sotto `deploy/`) e farli
     invocare dal collector al posto di quelli personali in `$HOME`.
     Scartata: contraddice sia la regola CLAUDE.md sulle personalizzazioni di
     deployment sia la premessa esplicita di ADR 010 secondo cui la sorgente
     strutturata vive fuori dal repository per scelta. Adottarla
     richiederebbe riaprire ADR 010, esplicitamente vietato da questa coda
     ("non riaprire né contraddire quei documenti").
  2. **Emettere un segnale osservabile quando il fallback si attiva**
     (opzione raccomandata da ROOT, non ancora approvata). `collect()` in
     `deploy/rate-limit-collector.py` già distingue internamente se
     `parse_structured()` ha avuto successo o se si è ricaduti su
     `parse_text()` (righe 138-151): propagare quel fatto come informazione
     pubblicata, ad es. un campo `"parse_mode": "structured"|"text"` sulla
     riga storica, così la vista Budget può mostrare un avviso quando le
     righe più recenti di un provider sono tutte in modalità testuale pur
     avendo `resets_at` valorizzato altrove nella serie — stesso principio
     del badge già esistente per `stale`.

  L'opzione 2 allarga il contratto pubblicato
  (`docs/contracts/budget-history-v1.md`, sezioni "Forma comune" e "Serie
  storica della quota") con un campo che oggi non attraversa il boundary, e
  potenzialmente la superficie della vista Budget. Per lo stesso motivo per
  cui `GATE-BH-00` ha richiesto approvazione esplicita prima di avviare
  `IMP-BH-01`, questa non è una decisione che `ROOT` può prendere da solo:
  nessuna implementazione avviata, `IMP-BH-03` resta bloccato in attesa
  dell'approvazione dell'utente sull'opzione 2 (o di un'opzione
  alternativa).

  **Addendum del 02/08/2026 — proprietà dello strato quote.** La proposta
  originale trattava il fallback silenzioso come un problema di MAC. Lo è
  solo a metà: la metà mancante è che gli script quote **non hanno un
  proprietario**, e le copie stanno già divergendo. Rilevazione diretta
  sull'host di sviluppo: lo script quote di Codex esiste in due esemplari
  di dimensione diversa, uno invocato da questo prodotto e uno versionato
  nel repository dell'orchestratore esterno; dopo il lavoro del 02/08/2026
  solo il primo conosce `--json`, quindi la copia versionata è la più
  vecchia delle due. Lo script quote di Claude non è versionato in nessun
  repository. Esistono inoltre due watchdog distinti, uno per provider, in
  posti diversi.

  Decisione approvata: **il proprietario dello strato quote è il componente
  esterno di orchestrazione**, non questo prodotto. Decidere se un agente
  può partire è compito di chi schedula; qui le quote si mostrano soltanto.
  Le copie in `$HOME` diventano artefatti installati da quel componente,
  non sorgenti.

  Conseguenze per questa coda, che non cambiano il boundary di MAC:

  - il collector continua a invocare **percorsi configurati**, mai una
    posizione assunta: il prodotto resta funzionante e installabile anche
    senza il componente di orchestrazione, e nessuna dipendenza nuova entra
    nel repository;
  - **non si versiona qui alcuna copia degli script**. L'opzione 1 resta
    scartata, e ora per una ragione in più rispetto a quelle già scritte
    sopra: creerebbe un terzo esemplare divergente dello stesso file,
    esattamente il problema che questa voce deve chiudere;
  - ciò che va scritto qui è il **contratto di formato** che il collector si
    aspetta dagli script quote (invocazione, forma strutturata, campi,
    degradazione ammessa), oggi implicito nel codice di
    `deploy/rate-limit-collector.py`. Il contratto è l'unica cosa che questo
    repository possiede legittimamente di quello strato;
  - l'opzione 2 resta valida e diventa la rete di sicurezza di quel
    contratto: se la sorgente smette di rispettarlo, il prodotto deve
    dirlo invece di degradare in silenzio.

  Resta aperta una seconda asimmetria, da chiudere nella stessa passata:
  l'integrazione da questo prodotto verso il componente di orchestrazione
  avviene oggi invocandone direttamente uno script sul filesystem, mentre
  quella in direzione opposta ha un contratto esplicito (endpoint HTTP su
  loopback, token, collector che sanifica). La prima va documentata come
  contratto su entrambi i lati o ricondotta alla seconda forma; oggi non è
  descritta da nessuna delle due parti.

  **Secondo addendum del 03/08/2026 — il principio, e un secondo caso.** Il
  giorno stesso si è manifestato lo stesso schema su un'altra superficie: la
  voce Host è scomparsa dalla dashboard senza alcun errore. Nessun codice
  perso — il pulsante è subordinato a `host_observability_enabled`, e
  l'overlay Compose che accende quel flag non era più nella composizione
  attiva. Diagnosi immediata una volta cercata, invisibile fino ad allora.

  I due casi condividono un principio, ed è quello che questa voce
  implementa: **lo stato effettivo va dichiarato, non dedotto.** Un fallback
  al parsing testuale e una funzione opzionale spenta sono entrambi stati
  legittimi; ciò che non è accettabile è che siano indistinguibili dal
  funzionamento nominale.

  Nota su cosa **non** va costruito: un controllo che confronti le funzioni
  attese con quelle attive è irrealizzabile, perché non esiste una fonte di
  verità su cosa "dovrebbe" essere acceso — una funzione disattivata è una
  configurazione valida, e un check del genere allarmerebbe a ogni
  installazione minima. Il primitivo giusto riferisce, non giudica.

  La causa a monte del secondo caso non è di prodotto: il `.env` non è
  versionato — giustamente, contiene token e percorsi propri
  dell'installazione — quindi non restava traccia del cambiamento. Rimediato
  fuori dal prodotto con `deploy/snapshot-env.sh`, che conserva copie datate
  sotto `customizations/`, ignorata da git; lo script è generico e
  pubblicabile, le copie no.

- [x] IMP-BH-03 | OWNER: SA-IMP | STATUS: DONE | Entrambi i deliverable
  implementati sullo stesso principio ("lo stato effettivo va dichiarato,
  non dedotto").

  **1. Contratto script quote + `parse_mode` pubblicato.** Nuovo
  `docs/contracts/quote-script-v1.md`: invocazione (percorso configurato,
  `--json`/`--fresh`), forma strutturata (`windows[].label/used_percent/
  resets_at/detail`, `updated_at`, `source`, `reached_type`, esattamente i
  campi letti da `parse_structured()`), degradazione ammessa alla forma
  testuale storica (le tre regex `UPDATED`/`WINDOW`/`REACHED` di
  `deploy/rate-limit-collector.py`, descritte come contratto testuale) e la
  conseguenza pubblicata (`parse_mode`). Nessuno script versionato, nessun
  percorso assunto, nessun nome di componente esterno, come vincolato
  dall'addendum di `GATE-BH-03`.

  `deploy/rate-limit-collector.py`: `collect()` ora traccia esplicitamente
  quale forma ha prodotto il risultato (`"structured"` quando
  `parse_structured()` riesce, `"text"` in entrambi i rami di fallback,
  assente/`None` quando lo script non è nemmeno eseguibile — nessun parsing
  è stato tentato in quel caso, non è "testuale"). `history_row()` lo
  propaga come campo `parse_mode` sulla riga storica; `snapshot_provider()`
  resta invariato per costruzione (contratto v1 del solo snapshot
  istantaneo, non toccato). `observation_key()` include ora `parse_mode`
  nella tupla di deduplica: una transizione strutturato→testuale a parità di
  `observed_at`/percentuali è un fatto nuovo da pubblicare, non uno scarto.

  Backend: `RateLimitSample.parse_mode: Literal["structured","text"] | None
  = None` in `rate_limit_history_service.py` — righe scritte prima di questa
  voce restano valide (`None`, "non noto", mai equivalente a `"text"`); un
  valore fuori enum scarta la riga come ogni altro campo fuori contratto.
  L'endpoint `GET /api/v1/provider-rate-limits/history` lo espone senza
  traduzione intermedia (`response_model=RateLimitHistory`, invariato).

  Frontend: `RateLimitHistorySample.parse_mode` in `api.ts`.
  `BudgetProviderChart` (App.tsx) calcola `latestParseMode` sull'ultimo
  campione del provider e mostra, solo quando `"text"`, un avviso
  dichiarativo ("Fallback testuale attivo per questo provider: l'ultimo
  campione non proviene dalla forma strutturata"), stessa classe neutra
  `budget-note` già usata per il residuo — nessun linguaggio di allarme,
  nessuna comparsa per `null`/assente.

  **2. Funzioni opzionali attive: log di avvio + vista admin.**
  `_optional_feature_flags()` in `main.py` centralizza i cinque flag
  (`host_observability_enabled`, `session_usage_enabled`,
  `rate_limit_fresh_enabled`, `claude_history_enabled`,
  `database_auth_enabled`). Il `lifespan` logga una singola riga
  `logger.info("Funzioni opzionali: nome=on/off, ...")` all'avvio — solo
  nomi e stato, mai token o percorsi, mai `logger.warning`. `ConfigView`
  guadagna `optional_features: dict[str, bool] | None`, popolato da
  `client_config()` con lo stesso pattern di gating già in uso per
  `host_observability_enabled`/`rate_limit_fresh_enabled`
  (`user is None or user.role == "admin"`, altrimenti `None`). Lato
  frontend, la vista Audit (`AuditModal`, già admin-only, già nello stile
  "riferisce, non giudica" per gli eventi) carica `optional_features` da
  `fetchConfig()` e la mostra come lista "attiva/disattiva" con etichette
  leggibili (`OPTIONAL_FEATURE_LABEL`); niente vista admin nuova, riuso
  della superficie esistente come richiesto.

  **Test aggiunti (proporzionati al rischio, per ogni parte toccata).**
  Backend +10 rispetto alla baseline 238 (`TEST-BH-01-T2`): 4 in
  `test_rate_limit_collector.py` (parse_mode per structured/text/assente,
  propagazione in `history_row()`, sensibilità di `observation_key()` al
  solo cambio di `parse_mode`, e un test end-to-end su `main()` che
  dimostra l'append di una nuova riga quando la sorgente degrada da
  strutturato a testuale a parità di osservazione — il fallback silenzioso
  che questa voce chiude); 3 in `test_rate_limit_history_service.py`
  (default `None` retrocompatibile, round-trip structured/text, scarto di
  un valore fuori enum); 3 in `test_rate_limit_history_api.py`
  (`optional_features` esposto in modalità legacy e nascosto per ruoli
  non-admin via `database_settings()`, log di avvio verificato con
  `caplog` dentro `with TestClient(app):` per innescare il lifespan,
  incluso il controllo che nessun token/percorso compaia nel messaggio e
  che non sia mai loggato a livello `WARNING`+). Frontend +10 rispetto alla
  baseline 35: 5 in `budget-view.test.mjs` (badge di fallback testuale,
  esclusione del caso `null`, stile) e un nuovo file
  `admin-optional-features.test.mjs` (5 test) con script npm dedicato
  `test:admin`, incluso nella catena `test:ui`.

  **Comandi eseguiti e risultati reali.** `docker compose build
  backend-test` poi `docker compose run --rm backend-test`: **248 passed, 0
  failed** (baseline 238 + 10); `docker compose run --rm backend-test ruff
  check --no-cache app/main.py app/schemas.py
  app/services/rate_limit_history_service.py tests/test_rate_limit_collector.py
  tests/test_rate_limit_history_api.py tests/test_rate_limit_history_service.py`:
  pulito. `python3 -m unittest discover -s deploy/tests`: **59 passed**
  (invariato, questa voce non tocca file sotto `deploy/tests/`, i test del
  collector vivono in `backend/tests/test_rate_limit_collector.py` che
  carica `deploy/rate-limit-collector.py` da file). Frontend:
  `npm run test:host` 14, `npm run test:budget` 23 (18 + 5), `npm run
  test:console` 3, `npm run test:admin` 5 — **45 test totali, 0 falliti**
  (baseline 35 + 10); `npm run build` (`tsc -b && vite build`) pulito.
  `systemd-analyze --user verify` sulle unit fresh: pulito (nessuna unit
  toccata da questa voce). `docker compose config --quiet` e le due
  combinazioni con overlay (`compose.budget-history.yaml`,
  `compose.host.yaml` + `compose.budget-history.yaml`): valide. `git diff
  --check`: pulito.

  **Verifica su dati reali (vincolante, non solo fixture).** Il timer
  systemd di questo host esegue `ExecStart=python3
  ${MAC_INSTALL_DIR}/deploy/rate-limit-collector.py ...` direttamente dal
  checkout git di questo repository (confermato leggendo l'unit installata:
  `MAC_INSTALL_DIR` punta a questo working tree), quindi la modifica al
  collector fatta in questa voce è diventata immediatamente osservabile sul
  file storico reale già in scrittura su questo host,
  `${MAC_WORKSPACE_ROOT}/.mobile-agent-console/provider-rate-limits-history.jsonl`
  (fuori dall'albero del repository, come da contratto), senza bisogno di
  alcun deploy. Ispezione diretta di quel file (167 righe totali al momento
  dell'ispezione, 152 `claude` + 15 `codex`): le prime 163 righe, scritte
  prima di questa modifica, non hanno `parse_mode` (confermando la
  retrocompatibilità sui dati reali pre-esistenti, non solo su fixture
  costruite); le 4 righe scritte dai cicli del timer successivi alla
  modifica portano tutte `parse_mode: "structured"` (3 `claude`, 1 `codex`)
  — sia lo script quote di Claude sia quello di Codex configurati su questo
  host offrono correttamente `--json` in questo momento, coerente con
  quanto riportato nell'addendum di `GATE-BH-03` sul lavoro del 02/08/2026.
  Nessuna anomalia: nessuna riga marcata `"text"` porta un `resets_at`
  valorizzato in nessuna finestra. Le righe storiche precedenti mostrano
  però la traccia reale del problema che questa voce chiude: 14 finestre
  `codex` su 22 hanno `resets_at` nullo su tutta la loro estensione — il
  fallback silenzioso descritto nel testo originale della proposta,
  realmente accaduto su questo host prima che Codex offrisse `--json`, e che
  da questa voce in poi sarebbe stato segnalato da `parse_mode: "text"`
  invece di sparire senza traccia. Caricamento dell'intero file (una copia
  con permessi `644` per aggirare il vincolo `0700` non attraversabile
  dall'utente non privilegiato del container, mai il file originale) dentro
  `backend-test` attraverso il vero `RateLimitHistoryService`: **167/167
  righe validate senza scarti** (149 `claude`/`None` + 3 `claude`/
  `"structured"` + 14 `codex`/`None` + 1 `codex`/`"structured"`), a conferma
  che il modello Pydantic reale — non un doppione nel test — legge sia le
  righe legacy sia quelle nuove senza perderne nessuna. Eseguito inoltre
  `deploy/rate-limit-collector.py --stdout` con gli script quote realmente
  configurati su questo host (`~/.claude/rate-limit.sh`,
  `~/.codex/rate-limit.sh`, percorsi passati da riga di comando, mai
  hardcoded): entrambi i provider hanno risposto con `"parse_mode":
  "structured"` e un `resets_at` epoch valorizzato su ogni finestra,
  coerente con l'ispezione del file storico. Output e file temporanei di
  questa verifica rimossi al termine, nessuna riga aggiuntiva lasciata nel
  file storico di produzione oltre a quelle già scritte dal timer stesso
  durante la finestra di modifica.

  Working tree: nessun commit creato da questa voce (per scelta, non
  richiesto); modifiche in `deploy/rate-limit-collector.py`,
  `backend/app/services/rate_limit_history_service.py`,
  `backend/app/schemas.py`, `backend/app/main.py`, `frontend/src/api.ts`,
  `frontend/src/App.tsx`, `frontend/src/styles.css`,
  `frontend/package.json`, `docs/contracts/quote-script-v1.md` (nuovo),
  `docs/contracts/budget-history-v1.md`, `docs/gates/budget-history.md`, e i
  file di test elencati sopra. `BH-04`/`GATE-BH-04` e la sezione "Protocollo
  della roadmap per i subagent" non toccati.

- [x] TEST-BH-03 | OWNER: SA-TEST | STATUS: FAILED | Comandi automatici tutti
  verdi e coerenti con l'atteso: `docker compose build backend-test` +
  `docker compose run --rm backend-test` → **248 passed, 0 failed** (baseline
  238 + 10); `ruff check --no-cache` sui sei file elencati → pulito;
  `python3 -m unittest discover -s deploy/tests` → **59 passed** (invariato);
  frontend `npm run test:ui` → **45 test, 0 falliti** (`test:host` 14 +
  `test:budget` 23 + `test:console` 3 + `test:admin` 5); `npm run build`
  (`tsc -b && vite build`) pulita; `git diff --check` pulito.

  **Criteri manuali verificati positivamente.** Script fittizio end-to-end
  (mai versionato, rimosso a fine verifica) che rifiuta `--json` con exit
  code ≠ 0 su un provider e ne accetta la forma strutturata sull'altro →
  `deploy/rate-limit-collector.py --stdout` produce correttamente
  `parse_mode: "structured"` per il primo e `"text"` per il secondo (Check 7
  del gate, riprodotto dal vivo). Percorso configurato inesistente →
  `collect()` restituisce `available: false`, `error` troncato, **nessuna**
  chiave `parse_mode` nel dict, nessuna eccezione propagata (riprodotto
  direttamente su `deploy/rate-limit-collector.py`). A livello di modello:
  campo assente e valore `null` esplicito → `parse_mode is None` in entrambi
  i casi; stringa vuota, valore fuori enum (`"binary"`), intero e lista →
  riga scartata da `RateLimitHistoryService.read()` senza eccezione non
  gestita (testato con 7 varianti in un file temporaneo dentro
  `backend-test`, 3/7 accettate come atteso). `observation_key()`: un cambio
  di solo `parse_mode` a parità di `observed_at`/percentuali produce
  correttamente una nuova riga storica (non deduplicata) — confermato sia dal
  test aggiunto sia da esecuzione end-to-end di `main()` con due script stub
  successivi. Vista Budget: la logica (`latestParseMode` sull'ultimo
  campione, non un "mai stato strutturato nella serie") guarda solo l'ultimo
  campione per costruzione, righe pre-BH-03 (`parse_mode` assente) non
  generano l'avviso. `GET /api/v1/config`: `optional_features` popolato per
  admin/legacy, `null` per ruoli non-admin (verificato dai test API).
  **Verifica sui dati reali** (file di questo host, cresciuto da 167 a 170
  righe fra l'ispezione di `IMP-BH-03` e questa, il timer resta attivo — atteso,
  non un'anomalia): 163 righe pre-BH-03 senza `parse_mode` (149 `claude` + 14
  `codex`, invariato), ora 6 `claude`/`"structured"` + 1 `codex`/`"structured"`
  (+2 `claude` rispetto alle 4 nuove viste da `IMP-BH-03`, coerente con i cicli
  del timer nel frattempo); 14/22 finestre `codex` storiche con `resets_at`
  nullo confermato; caricamento dell'intero file (copia `644`, mai
  l'originale, rimossa a fine verifica) dentro `backend-test` col vero
  `RateLimitHistoryService`: **170/170 righe validate senza scarti**.

  **Difetto bloccante trovato con verifica dal vivo (non dai soli test).**
  Il criterio manuale esplicito di questa voce e il Check 8 del gate
  richiedono `docker compose logs backend | grep "Funzioni opzionali"` con
  corrispondenza a livello `INFO`. Ricreato `backend` con l'immagine
  ricostruita da questo working tree (`docker compose build backend &&
  docker compose up -d backend`, operazione stateless prevista da
  CLAUDE.md, nessun tocco a `tmux-runtime`): **`docker compose logs backend |
  grep -i "funzioni opzionali"` non produce alcuna corrispondenza.** Causa:
  `app/start.py` chiama `uvicorn.run(...)` senza `log_config`/`log_level`;
  uvicorn configura solo i propri logger (`uvicorn`, `uvicorn.error`,
  `uvicorn.access`), mai il logger applicativo `mobile_agent_console` usato
  da `main.py`. Verificato dentro il container reale:
  `logging.getLogger("mobile_agent_console").getEffectiveLevel()` → `30`
  (`WARNING`), `.handlers` → `[]`, `logging.getLogger().handlers` → `[]`. Con
  livello effettivo `WARNING` e nessun handler in tutta la gerarchia, ogni
  `logger.info(...)` in `main.py` (non solo la riga nuova di questa voce, la
  stessa cosa vale già per il log di rotazione allegati) viene scartato in
  modo silenzioso: non raggiunge stdout/stderr né `docker compose logs`, in
  nessuna configurazione. Il test automatico
  `test_startup_logs_optional_feature_states_without_secrets` in
  `backend/tests/test_rate_limit_history_api.py` resta verde nonostante
  questo perché usa `caplog.at_level(logging.INFO,
  logger="mobile_agent_console")`, che forza artificialmente il livello
  effettivo del logger per la durata del test e intercetta il record a
  monte di qualunque handler reale — esattamente il tipo di scarto fra "il
  test passa" e "il criterio manuale osservabile regge" che questo
  protocollo chiede di cercare attivamente. Riproduzione:
  ```bash
  docker compose build backend
  docker compose up -d backend      # ricrea solo backend, stateless
  docker compose logs backend | grep -i "funzioni opzionali"   # nessun output
  docker compose exec -T backend python3 -c \
    "import logging; l = logging.getLogger('mobile_agent_console'); \
     print(l.getEffectiveLevel(), l.handlers, logging.getLogger().handlers)"
  # -> 30 [] []
  ```

  **Difetto secondario trovato (da correggere nello stesso rework).** In
  `deploy/rate-limit-collector.py:collect()`, il ramo finale di fallback
  (script che rifiuta `--json` con exit code ≠ 0) imposta
  incondizionatamente `parse_mode = "text"` anche quando la seconda
  invocazione non produce alcuna finestra utilizzabile
  (`parse_text(...)["windows"]` vuoto, es. script eseguibile ma sempre
  fallito) — a differenza del ramo precedente (script che ignora `--json` e
  stampa comunque testo), che correttamente lascia `parse_mode` non
  impostato quando il testo non produce finestre. Risultato: una riga con
  `available: false`, `windows: []`, `error: "Nessun dato riconosciuto"` può
  comunque portare `parse_mode: "text"`; se questa è l'ultima riga di un
  provider, la vista Budget mostrerebbe "Fallback testuale attivo" come se
  il parsing testuale stesse davvero producendo dati, invece di riflettere
  che nessun dato è mai stato estratto. Riproduzione (script temporaneo, mai
  versionato, rimosso a fine verifica):
  ```bash
  cat > /tmp/broken-quote.sh <<'EOF'
  #!/bin/sh
  exit 1
  EOF
  chmod +x /tmp/broken-quote.sh
  python3 -c "
  import importlib.util
  spec = importlib.util.spec_from_file_location('collector', 'deploy/rate-limit-collector.py')
  collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
  print(collector.collect('codex', '/tmp/broken-quote.sh'))
  "
  # -> {'available': False, 'error': 'Nessun dato riconosciuto',
  #     'parse_mode': 'text', 'windows': [], ...}
  ```

  Nessun file toccato per questa verifica oltre a quelli temporanei (rimossi):
  nessuna modifica a `deploy/rate-limit-collector.py`, ai file backend/
  frontend, ai contratti o ai test. `backend` è stato ricreato con l'immagine
  corrente (operazione stateless prevista dal deploy normale) per osservare
  il log dal vivo; resta in esecuzione con il codice di questa voce, che non
  introduce regressioni funzionali — solo l'assenza del log osservabile e
  l'imprecisione secondaria sopra descritte restano da correggere.

- [x] IMP-BH-03-R1 | OWNER: SA-IMP | STATUS: DONE | Riferimento: `TEST-BH-03`.
  Corretti entrambi i difetti trovati dalla verifica dal vivo di SA-TEST,
  nello stesso giro.

  **Difetto bloccante (log di avvio non osservabile).** Causa confermata:
  `app/start.py` chiamava `uvicorn.run(...)` senza `log_config`/`log_level`,
  quindi uvicorn configurava solo i propri logger (`uvicorn`,
  `uvicorn.error`, `uvicorn.access`), mai `mobile_agent_console` (livello
  effettivo `WARNING`, nessun handler in tutta la gerarchia). Fix: nuovo
  modulo `backend/app/logging_config.py` con `build_log_config()` — copia
  profonda di `uvicorn.config.LOGGING_CONFIG` (stessi formatter/handler di
  uvicorn, `disable_existing_loggers: False`) più una voce aggiuntiva per
  `mobile_agent_console` (`handlers: ["default"]` — l'handler stderr già
  definito da uvicorn, nessun handler nuovo —, `level: "INFO"`,
  `propagate: False`) — e `configure_logging()`, che applica quel dict con
  `logging.config.dictConfig`. `app/start.py` passa ora
  `log_config=build_log_config()` a `uvicorn.run(...)`; nessuna chiave
  `root` nel dict, quindi nessuna modifica alla soglia globale né ai logger
  di librerie terze (`urllib3`, `asyncio`, ...), che restano al loro default
  — vincolo esplicito del rework rispettato. Verificato che
  `uvicorn.run(log_config=dict)` chiama internamente esattamente
  `logging.config.dictConfig(quel_dict)` (ispezionato il sorgente di
  `uvicorn.config.Config.configure_logging` dentro l'immagine
  `backend-test`, uvicorn 0.51.0), quindi `configure_logging()` chiamata
  direttamente in un test riproduce fedelmente l'inizializzazione di
  produzione senza aprire un vero socket.

  Test: aggiunto `test_configure_logging_makes_app_logger_effectively_observable`
  in `backend/tests/test_rate_limit_history_api.py`, accanto al test
  preesistente (lasciato invariato, verifica solo il contenuto del
  messaggio). Il nuovo test chiama `configure_logging()` — la stessa
  funzione di produzione, non un `caplog.at_level` che forzerebbe il
  livello — e verifica: livello effettivo del logger applicativo `<= INFO`,
  `hasHandlers()` vero, un `logger.info(...)` reale che raggiunge
  effettivamente lo stream dell'handler (catturato reindirizzando lo stream
  a un `io.StringIO`, non tramite `caplog`), e che i livelli effettivi di
  `urllib3` e del root logger restino invariati rispetto a prima della
  chiamata (guardia esplicita contro l'abbassamento indiscriminato). Stato
  del logger ripristinato in un blocco `finally` per non inquinare altri
  test nella stessa sessione pytest.

  **Difetto secondario (`parse_mode` marcato "text" senza dati estratti).**
  In `deploy/rate-limit-collector.py:collect()`, il ramo finale di fallback
  (script che rifiuta `--json`) impostava incondizionatamente
  `parse_mode = "text"` anche quando `parse_text(result.stdout)["windows"]`
  era vuoto. Corretto in
  `parse_mode = "text" if parsed["windows"] else None`, coerente col ramo
  gemello (script che ignora `--json` e stampa comunque testo) che già
  faceva questo controllo. Nota per il prossimo rilettore: la prima stesura
  di questa modifica aveva erroneamente rimosso la riga
  `available = result.returncode == 0 and bool(parsed["windows"])`
  subito sotto (persa nel replace), causando `NameError: name 'available'
  is not defined` — individuato subito dalla suite (`7 failed`) e
  ripristinato prima di procedere; menzionato qui solo perché la riga in
  questione è a un solo rigo di distanza dal punto toccato e un futuro
  refactor dello stesso blocco dovrebbe fare attenzione a non riperdere quella
  riga.

  Test: nuovo `test_collector_final_fallback_does_not_claim_text_mode_without_windows`
  in `backend/tests/test_rate_limit_collector.py` (accanto agli altri test
  di `collect()` sullo stesso file) — script stub che fallisce sempre su
  entrambe le invocazioni (`--json` e senza), verifica
  `available is False`, `windows == []`, `parse_mode is None` (la chiave è
  comunque presente nel dict, a differenza del caso "script non
  eseguibile", che non la include affatto — verificato non regredire il
  test preesistente `test_collector_reports_no_parse_mode_when_the_script_cannot_run_at_all`).

  **Comandi eseguiti (conteggi reali).** `docker compose build backend-test`
  + `docker compose run --rm backend-test` → **250 passed, 0 failed**
  (baseline 248 + 2 nuovi test), poi `ruff check --no-cache` (eseguito sia
  come parte del comando sopra sia mirato) su
  `app/start.py app/logging_config.py tests/test_rate_limit_history_api.py
  tests/test_rate_limit_collector.py` → **All checks passed!**;
  `python3 -m unittest discover -s deploy/tests` → **59 passed** (invariato);
  frontend `npm run test:ui` → **45 test, 0 falliti** (14 + 23 + 3 + 5,
  invariato); `npm run build` (`tsc -b && vite build`) pulita; `git diff
  --check` pulito.

  **Verifica dal vivo ripetuta (backend realmente avviato, non solo
  pytest).** `docker compose build backend && docker compose up -d backend`
  (stateless, `tmux-runtime` non toccato), poi:
  ```
  $ docker compose logs backend | grep -i "funzioni opzionali"
  backend-1  | INFO:     Funzioni opzionali: host_observability_enabled=on, session_usage_enabled=on, rate_limit_fresh_enabled=on, claude_history_enabled=on, database_auth_enabled=on
  ```
  Corrispondenza reale a livello `INFO` con i cinque flag, come richiesto
  dal criterio manuale e dal Check 8 del gate. Nota: `docker compose exec -T
  backend python3 -c "..."` (lo stesso comando diagnostico usato in
  `TEST-BH-03` per isolare la causa) continua a stampare `30 [] []` anche
  dopo il fix — atteso e non un residuo del bug: `exec` avvia un
  interprete Python nuovo e indipendente dal processo worker di uvicorn, che
  non condivide lo stato di logging in memoria configurato da
  `configure_logging()` dentro quel processo. Il criterio che conta (il
  grep sui log reali del processo in esecuzione) è quello sopra, e passa.

  Riproduzione del difetto secondario ripetuta dopo il fix:
  ```
  $ python3 -c "... collector.collect('codex', '/tmp/broken-quote.sh') ..."
  {'provider': 'codex', 'available': False, 'error': 'Nessun dato riconosciuto',
   'parse_mode': None, 'observed_at': None, 'source': 'cache', 'windows': [],
   'reached_type': None}
  ```
  `parse_mode` è ora `None` (nessun parsing riuscito) invece di `"text"`.

  File toccati: `backend/app/start.py`, `backend/app/logging_config.py`
  (nuovo), `backend/tests/test_rate_limit_history_api.py`,
  `deploy/rate-limit-collector.py`,
  `backend/tests/test_rate_limit_collector.py`. Nessun commit creato da
  questa voce (a discrezione, non richiesto esplicitamente prima della
  revisione di SA-TEST). `BH-04`/`GATE-BH-04` e la sezione "Protocollo della
  roadmap per i subagent" non toccati.

- [x] TEST-BH-03-T2 | OWNER: SA-TEST | STATUS: PASSED | Riferimento:
  `IMP-BH-03-R1`. Verificato in modo indipendente il rework dei due difetti
  trovati dalla verifica dal vivo di `TEST-BH-03`. Nessuna correzione
  applicata da questa voce: solo verifica.

  **Comandi automatici (conteggi reali, tutti coerenti con l'atteso).**
  `docker compose build backend-test` (ricostruita, non riutilizzata dalla
  cache) + `docker compose run --rm backend-test` → **250 passed, 0
  failed** (esatto atteso: baseline 248 + 2 nuovi test); `ruff check
  --no-cache` su `app/start.py app/logging_config.py
  tests/test_rate_limit_history_api.py tests/test_rate_limit_collector.py`
  dentro `backend-test` → **All checks passed!**; `python3 -m unittest
  discover -s deploy/tests` → **59 passed** (invariato); frontend `npm run
  test:ui` → **45 test, 0 falliti** (14 `test:host` + 23 `test:budget` + 3
  `test:console` + 5 `test:admin`, invariato); `npm run build` (`tsc -b &&
  vite build`) → pulita, nessun errore; `git diff --check` → pulito
  (nessun output).

  **Verifica dal vivo obbligatoria (backend realmente avviato, non la sola
  suite pytest — lo stesso tipo di controllo che aveva trovato il difetto
  bloccante originale).** `docker compose build backend && docker compose
  up -d backend` (operazione stateless prevista da CLAUDE.md; confermato
  che `tmux-runtime` non è stato toccato: container invariato, già fermo da
  giorni prima di questa verifica, non ricreato). Primo `grep` lanciato a
  ridosso dell'`up -d` non ha prodotto corrispondenza (probabile race
  fra scrittura del log e comando); ripetuto subito dopo:
  ```
  $ docker compose logs backend | grep -i "funzioni opzionali"
  backend-1  | INFO:     Funzioni opzionali: host_observability_enabled=on, session_usage_enabled=on, rate_limit_fresh_enabled=on, claude_history_enabled=on, database_auth_enabled=on
  ```
  Corrispondenza reale a livello `INFO`, tutti e cinque i flag presenti,
  esattamente come dichiarato da `IMP-BH-03-R1`. `docker compose logs
  backend | grep -iE "urllib3|asyncio"` → **nessun output**: nessun log
  DEBUG/verboso nuovo da librerie terze.

  Controllo addizionale non richiesto esplicitamente dalla voce ma
  motivato dal timore di un abbassamento indiscriminato: dentro il
  container reale, chiamando `configure_logging()` due volte di seguito in
  uno stesso processo, il logger applicativo resta con **un solo
  handler** e produce **una sola riga** per un `logger.info(...)` di prova
  (nessuna duplicazione da chiamate ripetute). Confrontando lo stato
  "prima"/"dopo" una singola chiamata: `root`, `urllib3`, `asyncio` restano
  a `WARNING` (30, invariati); `mobile_agent_console` passa a `INFO` (20,
  atteso); `uvicorn` risulta anch'esso `INFO` (20), ma questo viene dal
  `deepcopy` del `LOGGING_CONFIG` di default di uvicorn stesso (comportamento
  preesistente di uvicorn, non introdotto da questo fix) — confermato
  ispezionando `build_log_config()`: nessuna chiave `root` nel dict,
  `loggers` contiene solo `uvicorn`, `uvicorn.error`, `uvicorn.access`,
  `mobile_agent_console`. Letto `backend/app/start.py`: `uvicorn.run(...,
  log_config=build_log_config())` è davvero cablato nel percorso di avvio
  reale (non solo definito/testato in isolamento) — confermato anche dal
  fatto che il log dal vivo sopra lo dimostra empiricamente.

  **Difetto secondario — riproduzione manuale ripetuta, più i due casi
  gemelli richiesti dal criterio di verifica.** Script che fallisce sempre
  (`exit 1` su entrambe le invocazioni, nessun output):
  ```
  $ python3 -c "... collector.collect('codex', '/tmp/broken-quote.sh') ..."
  {'provider': 'codex', 'available': False, 'error': 'Nessun dato riconosciuto',
   'parse_mode': None, 'observed_at': None, 'source': 'cache', 'windows': [],
   'reached_type': None}
  ```
  `parse_mode` è `None`, non più `"text"` — confermato. Ramo gemello già
  corretto in precedenza (script che ignora `--json`, accetta qualunque
  argomento ed exit 0 stampando testo valido con una finestra reale):
  `parse_mode: "text"`, `windows` con un elemento — non regredito dal fix.
  Caso positivo (script che rifiuta `--json` con exit code ≠ 0 ma riesce
  alla riesecuzione senza `--json`, stampando testo valido con una
  finestra reale): anche qui `parse_mode: "text"`, `windows` con un
  elemento — il fix non impedisce di marcare `"text"` quando il parsing
  testuale produce davvero dati. I tre script erano temporanei
  (`/tmp/broken-quote.sh`, `/tmp/twin-ignores-json.sh`,
  `/tmp/positive-fallback.sh`), mai versionati, rimossi a fine verifica
  (confermato con `ls` → nessuno dei tre esiste più).

  **Criteri di verifica addizionali.** Letto
  `test_configure_logging_makes_app_logger_effectively_observable`: non usa
  `caplog.at_level(...)` in nessun punto, chiama `configure_logging()`
  direttamente e ispeziona `getEffectiveLevel()`/`hasHandlers()` reali più
  un `logger.info(...)` catturato reindirizzando lo stream dell'handler a
  un `io.StringIO` — non un artefatto di test isolato, dato che
  `configure_logging()` è la stessa funzione invocata da `app/start.py`
  prima di `uvicorn.run`. Il test verifica anche esplicitamente che
  `urllib3` e il root logger non cambino livello — guardia coerente con
  quanto controllato sopra dal vivo. Confermato che
  `test_startup_logs_optional_feature_states_without_secrets` è rimasto
  invariato rispetto a `TEST-BH-03` (stesso uso di `caplog.at_level`, stessa
  asserzione sul contenuto del messaggio, nessuna asserzione sulla
  configurazione reale del logger — il test nuovo copre esattamente il
  gap che questo lasciava aperto). Confermato che
  `test_collector_final_fallback_does_not_claim_text_mode_without_windows`
  in `backend/tests/test_rate_limit_collector.py` copre lo scenario "script
  che fallisce sempre" (`_script_stub` con dict vuoto → entrambe le
  invocazioni rifiutate, `parse_mode is None`) e non regredisce
  `test_collector_reports_no_parse_mode_when_the_script_cannot_run_at_all`
  (caso diverso: `OSError` a monte di qualunque `run_script`, `"parse_mode"
  not in status` — chiave assente dal dict, non `None` — i due test restano
  entrambi verdi nella corsa completa da 250 passed).

  Nessun file applicativo, di contratto o di test modificato da questa
  voce: solo script temporanei in `/tmp/`, tutti rimossi. `BH-04`/
  `GATE-BH-04` e la sezione "Protocollo della roadmap per i subagent" non
  toccati. `backend` resta in esecuzione con l'immagine ricostruita in
  questa verifica (stateless, nessuna regressione attesa).

#### BH-04 — Piano fase C: drill-down dalla sessione alla timeline (non approvata)

- [x] GATE-BH-04 | OWNER: ROOT | STATUS: PASSED | Approvato dall'utente il
  03/08/2026, con un confine più stretto di quanto discusso nell'analisi
  tecnica sotto: **solo metadati di turno**, mai testo. Il testo originale
  della proposta resta invariato di seguito per il ragionamento tecnico che
  lo motiva ancora; l'addendum in coda registra la decisione e chiude le
  cinque domande aperte. `IMP-BH-04` è sbloccato.

  Testo originale della proposta. ADR 010 lascia
  esplicitamente fuori decisione la fase C («il drill-down sul contenuto dei
  turni resta esplicitamente fuori da questo round»): questa voce era nata
  come **solo** il piano tecnico da sottoporre a un gate di prodotto come
  `GATE-BH-00`, senza scrivere codice prima di un'approvazione esplicita
  dell'utente sui confini sotto.

  **Obiettivo.** Dalla riga di `session-usage-history.jsonl` "colpevole" di
  un picco (`session_uuid` + `bucket_start`, intervallo di 5 minuti) aprire
  la cronologia dei turni di quella sessione ristretta a quella finestra
  temporale — la domanda a cui BH-02 risponde è "chi ha consumato", questa è
  "cosa stava facendo in quel momento".

  **Perché `claude-history` (ADR 007) non è riusabile così com'è.**
  `ClaudeHistoryService`/`claude-history-collector.py` sono costruiti per un
  caso diverso: un adapter *live* sul pane tmux correntemente attaccato,
  correlato tramite la context cache, con una finestra di freschezza di
  default 30s (`claude_history_max_age_seconds`) e nessuna query per
  intervallo. Tre limiti concreti la escludono come base diretta per la fase
  C: (1) richiede un pane vivo — le sessioni headless che BH-02 rende
  finalmente visibili non ne hanno uno; (2) non fa query per range temporale,
  serve solo "adesso"; (3) è tenuta deliberatamente opt-in e a bassa
  persistenza proprio perché ADR 007 la considera un rischio di privacy da
  minimizzare («quando abilitata esiste una copia derivata persistente delle
  conversazioni») — estenderla a *qualsiasi* bucket storico passato
  allargherebbe quel rischio ben oltre quanto ADR 007 ha accettato,
  indipendentemente dai dettagli implementativi.

  **Blocchi riusabili individuati (solo lettura del codice esistente, nessuna
  modifica).**
  - `backend/app/services/claude_transcript_normalizer.py:normalize_transcript()`
    incapsula già le regole di minimizzazione approvate (solo testo
    user/assistant, eccezione `AskUserQuestion`, indicatori "activity" senza
    contenuto, esclusione di thinking/tool input-output/allegati): la fase C
    dovrebbe riusare queste regole invariate, non inventarne di nuove.
    Manca però un filtro per intervallo temporale — oggi normalizza l'intero
    file fino ai limiti di messaggi/dimensione, non un range `[bucket_start,
    bucket_start+5min)`.
  - La localizzazione del transcript dato un `session_uuid` è già risolta in
    parte da `deploy/session-usage-collector.py`: per Claude,
    `session_uuid` coincide con `path.stem` per le sessioni dirette
    (`discover_claude_files`/`process_claude_file`), quindi il file è
    riscopribile con un glob per nome sotto `claude_projects_root`; per i
    subagent il roll-up avviene sotto il `session_uuid` del genitore ma il
    contenuto utile del picco può stare nel transcript del subagent, non in
    quello padre — la fase C deve decidere se seguire anche i file
    `<progetto>/<parent-uuid>/subagents/agent-*.jsonl` o limitarsi al
    transcript principale. Per Codex la localizzazione analoga esiste in
    `discover_codex_files`/`process_codex_file`, ma
    `claude_transcript_normalizer` è specifico del formato Claude: Codex
    richiederebbe un normalizzatore separato, oggi inesistente.
  - Il percorso del transcript non deve mai attraversare il boundary verso
    il frontend (ADR 010, "Il boundary non si allarga": «Non lo
    attraversano... percorsi dei transcript»): la risoluzione
    `session_uuid` → percorso file deve restare interamente lato host/backend,
    mai un parametro esposto all'API.

  **Domande aperte che il gate deve chiudere prima di un `IMP-BH-04`.**
  1. Ambito privacy: resta testo minimizzato come ADR 007 (niente
     thinking/tool payload/percorsi), o serve un livello di dettaglio
     diverso per essere utile come drill-down di un picco di token (es.
     mostrare *quali* tool sono stati usati e quante volte, non solo il nome
     dell'ultimo in corso)?
  2. On-demand o persistito? Il pattern già accettato per l'aggiornamento
     forzato della quota (ADR 009: socket Unix, collector one-shot, nessun
     demone) sembra più coerente di un nuovo JSONL persistito — evita di
     moltiplicare copie derivate delle conversazioni sul disco — ma un
     bucket in una sessione headless conclusa richiede comunque rileggere un
     transcript che potrebbe essere stato ruotato o rimosso a monte: cosa
     mostra la UI in quel caso?
  3. Opt-in: riusare `MAC_CLAUDE_HISTORY_ENABLED` (stesso flag di ADR 007) o
     un flag dedicato, dato che l'esposizione è più ampia (qualsiasi sessione
     storica, non solo quella nel pane corrente)?
  4. Copertura Codex: incluso al v1 (richiede un normalizzatore nuovo) o
     limitata a Claude in una prima iterazione, con Codex esplicitamente
     `n/d` nel drill-down?
  5. Subagent: seguirli nel roll-up del drill-down o mostrare solo la
     sessione principale, rimandando ai subagent con un rimando testuale
     senza contenuto?

  Nessuna implementazione avviata al momento in cui questa analisi è stata
  scritta.

  **Addendum del 03/08/2026 — confine approvato e domande chiuse.** L'utente
  ha approvato la fase C con un confine più stretto di quanto discusso
  nell'analisi tecnica sopra: non testo minimizzato in stile ADR 007, ma
  **solo metadati di turno**. Il drill-down può pubblicare: istanti dei
  turni, modello, delta dei quattro contatori di token per turno, conteggi
  di strumenti per categoria (mai il nome o gli argomenti dello strumento),
  eventi di compattazione del contesto ed eventi di spawn di subagent (il
  fatto e l'istante, non il contenuto del subagent). Non può pubblicare in
  nessun caso testo di prompt, testo di risposte, ragionamento, nomi o
  argomenti di strumenti.

  Questo risponde alla Domanda 1 in modo più restrittivo di entrambe le
  opzioni lì discusse: non è il livello ADR 007 (testo minimizzato) né un
  livello di dettaglio maggiore (nomi degli strumenti) — è un livello
  inferiore a entrambi, puramente strutturale. Conseguenza pratica:
  `claude_transcript_normalizer.py` (che produce testo, non metadati) NON è
  il blocco riusabile per questa fase, a differenza di quanto ipotizzato
  nell'analisi tecnica originale sopra. Resta riusabile solo la parte di
  localizzazione file (`discover_claude_files`/`discover_codex_files`).

  Esplicitamente confermato: `claude-history` (ADR 007) e questo drill-down
  restano due domini indipendenti, non collegati. Non condividono flag, non
  condividono codice di estrazione contenuto, non si richiamano a vicenda
  nella UI. Un utente può avere l'uno senza l'altro.

  Chiusura delle domande aperte, entro questo confine più stretto:

  1. Ambito privacy: risolto sopra (metadati di turno, mai testo).
  2. **On-demand, non persistito.** Il metadato di turno non porta con sé il
     rischio specifico di ADR 007 (nessuna copia derivata di conversazione,
     mai testo), quindi in linea di principio potrebbe persistere senza
     allargare quel rischio — ma farlo comunque introdurrebbe un terzo JSONL
     che duplica in forma più fine ciò che `session-usage-history.jsonl` già
     aggrega per bucket, senza un bisogno concreto che lo giustifichi: il
     drill-down si apre solo quando un umano ispeziona un picco specifico,
     non serve una serie sempre aggiornata. Il backend legge il transcript
     on-demand alla richiesta, riusando la stessa localizzazione già usata da
     BH-02; niente demone, niente nuovo collector schedulato. Se il
     transcript sorgente è stato ruotato o rimosso, la UI dichiara
     esplicitamente "non più disponibile" per quel bucket — stesso principio
     "riferisce, non giudica" di BH-03, mai un errore silenzioso né un
     valore ricostruito.
  3. **Flag dedicato**, non `MAC_CLAUDE_HISTORY_ENABLED`. I due domini
     restano indipendenti per esplicita conferma dell'utente sopra:
     condividere il flag li accoppierebbe. Nome definitivo a scelta di
     `IMP-BH-04`, coerente con le convenzioni di naming già in uso (es.
     `MAC_SESSION_TIMELINE_ENABLED` o equivalente).
  4. **Copertura Codex inclusa dal v1**, non rimandata. Il confine più
     stretto approvato oggi la rende trattabile: istanti/modello/delta token
     sono già estratti per entrambi i provider da
     `deploy/session-usage-collector.py`
     (`process_claude_file`/`process_codex_file`, incluso
     `extract_codex_usage`) per costruire `session-usage-history.jsonl`;
     questa fase riusa la stessa estrazione a grana di turno invece di
     aggregarla per bucket. Conteggi di strumenti per categoria ed eventi di
     compattazione vanno verificati separatamente per ciascun formato di
     transcript: se per Codex uno dei due segnali non risultasse ricavabile
     dal formato reale entro questo giro, resta dichiarato `n/d` per quel
     segnale e quel provider soltanto, senza bloccare gli altri segnali né
     l'intera copertura Codex.
  5. **Subagent: spawn come evento, mai come contenuto.** Il drill-down
     pubblica il fatto e l'istante di uno spawn di subagent dentro la
     sessione ispezionata; non segue il subagent nel proprio transcript e
     non ne aggrega i turni nella stessa timeline — coerente con "solo
     metadati di turno" riferito alla sessione che l'utente ha aperto, non a
     un roll-up ricorsivo.

  Nota di implementazione non bloccante, non una domanda aperta: la forma
  esatta del record di compattazione del contesto nei transcript
  Claude/Codex non è stata ancora verificata su dati reali in questo
  repository (nessun codice esistente la gestisce oggi). `IMP-BH-04` deve
  accertarla con un'ispezione minima su transcript reali di questo host come
  primo passo, prima di scrivere il parser — coerente con la regola
  vincolante appena aggiunta al protocollo per collector/parser (verifica su
  dati reali, esito riportato per esteso nella voce).

  `IMP-BH-04` sbloccato.

- [x] IMP-BH-04 | OWNER: SA-IMP | STATUS: DONE | Implementare il drill-down
  di fase C entro il confine registrato in `GATE-BH-04`: solo metadati di
  turno (istanti, modello, delta dei quattro contatori di token, conteggi di
  strumenti per categoria, eventi di compattazione, eventi di spawn di
  subagent), mai testo di prompt/risposte/ragionamento né nomi o argomenti
  di strumenti. Flag di attivazione dedicato e indipendente da
  `MAC_CLAUDE_HISTORY_ENABLED` (i due domini non si collegano). Lettura
  on-demand del transcript alla richiesta (nessun nuovo JSONL persistito,
  nessun demone), riusando la localizzazione file già presente in
  `deploy/session-usage-collector.py`; transcript ruotato/rimosso →
  indisponibilità dichiarata, mai un errore 500 né un valore ricostruito.
  Copertura Claude e Codex entrambe nel v1; per ciascun segnale non
  ricavabile dal formato reale di un provider entro questo giro, dichiararlo
  `n/d` per quel segnale e provider soltanto, motivandolo nella voce, senza
  bloccare il resto. Primo passo vincolante: ispezionare su transcript reali
  di questo host la forma dei record di compattazione del contesto (non
  ancora verificata in questo repository) prima di scrivere il parser.
  Categorie di strumenti da definire come tassonomia fissa interna (mai il
  nome grezzo dello strumento). Percorso del transcript mai esposto
  all'API (ADR 010, "Il boundary non si allarga"). Test automatici
  proporzionati al rischio per collector/servizio/endpoint/frontend,
  aggiornamento di `docs/contracts/` e del gate manuale, verifica su dati
  reali con esito riportato per esteso (regola vincolante del protocollo).
  Chiudere con `TEST-BH-04`.
  Evidenze di chiusura (`ROOT`, 03/08/2026, commit `bce13f4`): collector su
  socket dedicata (`session-timeline-collector.py`), servizio e client backend,
  endpoint, vista e contratto `docs/contracts/session-timeline-v1.md`. Confine
  indipendente su tre livelli — flag `MAC_SESSION_TIMELINE_ENABLED` proprio,
  socket propria, mountpoint proprio — e spento di default anche con l'overlay
  attivo. Suite eseguite da `ROOT` prima del commit: backend 284 passati (ruff
  pulito), collector host 59, frontend 55 su cinque suite. Verifica su dati
  reali: la sessione di verifica notturna ha ispezionato i payload reali
  Claude/Codex prodotti dal collector senza trovare violazioni del confine e
  senza alcun file di timeline persistito.
  Due difetti d'incastro corretti nello stesso commit, non attribuibili al
  drill-down: l'immagine di test non copia `deploy/` e il mount era per singolo
  file, quindi ogni collector nuovo faceva fallire 13 test finché qualcuno non
  aggiungeva una riga a `compose.yaml` (ora si monta l'intera directory); le
  due asserzioni esaustive su `optional_features` non conoscevano la chiave
  nuova. **La funzione è committata ma non deployata**: flag spento e unit non
  installate, l'endpoint risponde `404`.

- [x] TEST-BH-04 | OWNER: SA-TEST | STATUS: FAILED | Sbloccato da
  `IMP-BH-04` (commit `bce13f4`, working tree pulito). Comandi:
  `docker compose build backend-test && docker compose run --rm backend-test`,
  `python3 -m unittest discover -s deploy/tests`,
  `cd frontend && npm run test:ui`. Il deploy della funzione (installazione
  delle unit, `MAC_SESSION_TIMELINE_ENABLED=true`, ricreazione dei soli
  `backend`/`web`) è **parte di questo check**: senza di esso il confine è
  verificato solo sui test, mai sull'installazione reale. Verificare in
  particolare: nessun testo di prompt/risposte/
  ragionamento né nome/argomento di strumento attraversa mai l'endpoint o la
  UI (ispezione avversariale del payload, non solo dei casi felici); flag
  spento → nessuna esposizione, nessuna lettura di transcript; transcript
  mancante/ruotato → indisponibilità dichiarata senza eccezioni; Claude e
  Codex entrambi coperti per i segnali dichiarati disponibili, `n/d`
  coerente per quelli dichiarati non disponibili; spawn di subagent
  pubblicato come evento senza seguirne il contenuto; `claude-history`
  resta indipendente (disattivarla non altera il drill-down e viceversa).
  **Esito (`SA-TEST`, 03/08/2026).** Suite tutte verdi con i numeri attesi:
  backend 285 (Ruff pulito), collector host 59, frontend 56. Confine
  confermato sull'istanza pubblicata: estrazione esaustiva delle stringhe su
  tre payload reali (Claude senza subagent, Codex, Claude con spawn reale) —
  nessuna chiave o valore fuori da `provider`, `session_uuid`, istanti ISO,
  `model` e contatori numerici; nessun testo, nome di strumento o percorso a
  nessun livello di annidamento. `model` vuoto su Codex quando manca
  `payload.info.model`, coerente con il contratto. Spawn di subagent
  pubblicato come solo istante, senza identificativo del thread figlio.
  Transcript inesistente → `available:false` con motivo e `200`. Parametri
  malformati → `422`. Raffiche di 25 e 30 richieste → `200` + `429` con
  `Retry-After`, socket rimasta `active (listening)`, nessun
  `trigger-limit-hit`: entrambi i difetti del deploy risultano chiusi.
  Scansione dati personali sul diff: nessuna occorrenza (l'unico match del
  pattern è la stringa `0.0.0.0` dentro una regola di sicurezza).
  **Difetto che motiva il `FAILED`:** `GET /api/v1/session-usage/timeline`
  **senza** `bucket_start` risponde `500` grezzo invece di `422`. Atteso:
  `422` con `loc: ["query", "bucket_start"]`, come già accade per
  `provider`/`session_uuid` mancanti. Ottenuto: `500 Internal Server Error`.
  Riproduzione (sessione admin valida in `jar.txt`, host da `.env`):
  `curl -sk -b jar.txt "$BASE/api/v1/session-usage/timeline?provider=claude&session_uuid=<uuid-valido>"`.
  Causa: `bucket_start: Annotated[datetime, Query()] = ...` in
  `backend/app/main.py` — il sentinella `Ellipsis` finisce nel corpo
  dell'errore di validazione, `jsonable_encoder` non lo serializza e solleva
  dentro l'handler di `RequestValidationError`, che degrada a `500`. Non è un
  bypass del confine (nessuno stack trace esposto, sessione admin comunque
  richiesta), ma viola l'invariante "errore genuino → HTTP tipizzato, mai un
  500 grezzo" rispettata ovunque altrove nel contratto. Nessun test copriva
  l'assenza del parametro: i test esistenti passavano sempre tutti e tre.
  Due punti dichiarati non verificati da `SA-TEST`, da non dare per chiusi:
  la copertura di `wait_closed()` contro un *hang* (non solo contro un errore
  immediato) non è riproducibile e resta un rischio teorico — il timeout è
  chiuso prima del `finally`; e la struttura `compactions` non è stata
  osservata su un bucket reale, perché nella finestra disponibile non ce
  n'erano, quindi è coperta solo da fixture.

- [x] IMP-BH-04-R1 | OWNER: ROOT | STATUS: DONE | Rework del difetto trovato
  da `TEST-BH-04`. I tre parametri di query dell'endpoint passano allo stile
  `Annotated[...]` **senza default**, che è già la convenzione del repo per i
  parametri obbligatori (vedi gli endpoint di lettura file in
  `backend/app/main.py`): il `= ...` era l'unica occorrenza anomala del
  repository. Test di regressione
  `test_missing_query_parameters_are_422_never_a_raw_500` in
  `backend/tests/test_session_timeline_api.py`: verifica tutti e tre i
  parametri a rotazione, non solo `bucket_start`, per non reintrodurre
  l'asimmetria che ha nascosto il difetto: finché due parametri su tre si
  comportano bene, il terzo non salta all'occhio. Verificato che il test
  fallisce davvero contro il codice difettoso — l'istanza pubblicata, che in
  quel momento eseguiva ancora il codice vecchio, ha risposto `500` dove il
  test pretende `422`. Suite backend: 286 passati, Ruff pulito.

- [x] TEST-BH-04-T2 | OWNER: SA-TEST | STATUS: PASSED | Sbloccato da
  `IMP-BH-04-R1`. Stessi comandi e stessi criteri di `TEST-BH-04`, che restano
  autorevoli. In più: confermare che i tre parametri mancanti diano `422` con
  `loc` corretto sull'**istanza pubblicata** (non solo nei test) e che il
  difetto non si ripresenti in altri endpoint — cercare nel repository altri
  `Annotated[...] = ...`, che è la forma esatta del difetto. Non serve
  ripetere l'ispezione avversariale dei payload se il diff del rework non
  tocca il confine: dichiararlo esplicitamente invece di rieseguirla per
  abitudine.
  **Esito (`SA-TEST`, 03/08/2026).** Suite: backend 286 con Ruff pulito,
  collector host 59, frontend 56 (14+24+3+5+10). Sull'istanza pubblicata i tre
  parametri omessi a turno danno `422` con `loc` corretto — `bucket_start`
  incluso, che era il difetto — e il percorso felice resta `200` su bucket
  reali Claude e Codex, con le sole chiavi del contratto. Anche i valori
  malformati (pattern violato, data non valida, stringa vuota) restano `422`
  tipizzati: nessun'altra via nota per degradare a `500` su questo endpoint.
  Ricerca della forma difettosa in tutto `backend/`: le uniche due occorrenze
  di `Annotated[...] = ...` sono il commento e il docstring che la descrivono,
  nessun codice vivo; gli altri usi di `Query(` hanno un default concreto
  oppure sono `Annotated` senza default. Il test di regressione è stato
  giudicato non vacuo: passa dall'handler reale di FastAPI e asserisce anche
  `stub.calls == 0`, quindi fallirebbe su una reintroduzione. Scansione dati
  personali: nessuna occorrenza. Ispezione avversariale dei payload non
  ripetuta e dichiarata tale — il diff del rework tocca solo la firma dei tre
  parametri, non l'estrazione né la serializzazione.
  Restano dichiarati non verificati, e non vanno considerati chiusi: l'`hang`
  di `wait_closed()` (rischio teorico, non riproducibile) e la struttura
  `compactions` su un bucket reale con compattazione effettiva — nella
  finestra disponibile non ne è comparsa nessuna, quindi è coperta solo da
  fixture. **Fase C chiusa.**

#### BH-05 — Ripristino del prossimo reset nel pannello quote

- [x] GATE-BH-05 | OWNER: ROOT | STATUS: PASSED | Approvato dall'utente il
  03/08/2026 dopo l'indagine sulla regressione. Il passaggio del collector a
  `--json` conservava `resets_at` nello storico ma lo scartava dalla proiezione
  istantanea; contemporaneamente lo script Codex usava `detail` per la durata
  della finestra, non per duplicare la data. Confine approvato: estensione
  compatibile dello snapshot con epoch opzionale validato, rendering esplicito
  in dashboard e Console anche con densità compatta, nessun parsing del testo
  libero e nessun allargamento dei dati già autorizzati dal threat model.

- [x] IMP-BH-05 | OWNER: ROOT | STATUS: DONE | Aggiunto
  `windows[].resets_at` alla proiezione del collector, al modello Pydantic e al
  tipo frontend; mantenere validi gli snapshot legacy senza campo e rifiutare
  epoch negativi. Mostrare la data locale senza dipendere da hover o `detail`,
  aggiornare contratti, ADR, architettura, sicurezza, gate, roadmap e
  `LATEST_RELEASE` nello stesso round. Implementazione conclusa in
  `deploy/rate-limit-collector.py`, modello e test backend, tipi/rendering/CSS
  frontend e documentazione elencata; nessuna modifica allo script quote
  esterno e nessun parsing della data dal suo `detail`.

- [x] TEST-BH-05 | OWNER: ROOT | STATUS: PASSED | Verificati collector,
  compatibilità legacy, rifiuto degli epoch negativi e propagazione API con i
  test mirati backend (67 passati); suite backend completa e Ruff
  `--no-cache` verdi. Suite UI del commit verde (46 test: Host 14, Budget 24,
  Console 3, Admin 5), build TypeScript/Vite locale e nel target
  Docker verdi; `docker compose config --quiet` e `git diff --check` puliti.
  Il timer reale ha scritto uno snapshot `0600` con `resets_at` su tutte le
  finestre strutturate Claude/Codex. Build e deploy hanno ricreato soltanto
  `backend` e `web` in modalità host, senza servizio `tmux-runtime` da toccare;
  le immagini finali sono state ricostruite da un export isolato del commit per
  escludere il lavoro locale BH-04 non ancora committato.
  Verifica HTTPS pubblicata: login `200`, endpoint quote `200`, finestra Codex
  `primaria` con epoch non negativo; gli asset web serviti contengono classe
  `provider-reset`, rendering di `resets_at` e il nuovo testo `LATEST_RELEASE`.
  Due tentativi di automazione browser Playwright non hanno restituito un esito
  osservabile nell'ambiente e non sono conteggiati come prova; la copertura del
  rendering normale/compatto resta nei test UI automatici verdi sopra.

## INC-PASTE-01 — il testo multilinea arriva a tmux come righe separate da Invio

- [x] INC-PASTE-01 | OWNER: ROOT | STATUS: DONE | Trovato il 03/08/2026
  durante lo spike OpenCode, ma **non è un difetto di OpenCode**: è del
  prodotto, e riguarda potenzialmente tutti i profili.
  `TmuxService.send_text` esegue `paste-buffer -b … -t … -d` **senza `-r`**.
  Il manuale di tmux: in assenza di `-r`, ogni LF del buffer viene sostituito
  con un separatore, per default **CR**. Il testo multilinea inviato dalla PWA
  non arriva quindi mai come testo multilinea — arriva come righe separate da
  Invio.
  **Conseguenza osservata** su una TUI OpenCode, con gli stessi flag del
  prodotto: `AAA\nBBB` è stato **inviato da solo**, senza che nessuno avesse
  chiamato l'endpoint dei tasti, e il newline è sparito dal testo. Con
  `paste-buffer -r` lo stesso identico testo è rimasto nell'input, su due
  righe, non inviato. La differenza è quel singolo flag.
  **Perché conta più di un difetto di rendering:** `CLAUDE.md` e
  `docs/architecture.md` dichiarano che l'invio di Enter è un'operazione
  separata e distinta (`POST /api/v1/sessions/{id}/keys`), ed è una scelta di
  sicurezza — l'utente deve poter incollare, rileggere e solo poi inviare. Con
  i flag attuali quella garanzia non vale per il testo multilinea, che è
  esattamente il caso in cui rileggere prima di inviare serve di più.
  **Da fare:** verificare il comportamento attuale su Codex, Claude e
  Antigravity prima di cambiare il flag — è possibile che alcune TUI
  dipendano oggi dalla conversione, e la correzione non deve rompere l'invio
  di prompt su una riga sola. Poi applicare `-r`, con test automatico che
  asseriti l'argv (il fake gateway rende il controllo banale) e un test
  manuale per profilo. Aggiornare `docs/architecture.md` se la sezione
  sull'input non menziona la semantica del separatore.
  **Nota di metodo:** questo difetto è stato trovato mentre si verificava
  tutt'altro, ed era invisibile ai test perché i test asseriscono l'argv che
  il codice costruisce, non l'effetto che quell'argv produce dentro tmux.
  **Esito (`ROOT`, 03/08/2026).** Comportamento misurato su ciascun profilo
  supportato, incollando `ciao\nmondo` con i flag del prodotto e poi con `-r`,
  su TUI reali avviate a mano:

  | profilo | flag attuali | con `-r` |
  |---|---|---|
  | `shell` | prima riga eseguita (corretto per una shell) | identico |
  | `codex` | due righe nell'input, non inviato | identico |
  | `claude` | **prima riga inviata**, il resto orfano nell'input | due righe, non inviato |
  | `antigravity` | **prima riga inviata** | due righe, non inviato |
  | `opencode` | **inviato**, con il newline perso | due righe, non inviato |

  Tre profili su quattro erano quindi rotti **in produzione**, non solo
  OpenCode: `claude` ha risposto davvero al frammento inviato per sbaglio.
  `codex` gestiva già correttamente il CR dentro un paste, ed è il motivo per
  cui il difetto è passato inosservato — chi provava con Codex non vedeva
  nulla di strano. `-r` è migliore o neutro su tutti e cinque i casi, quindi
  la correzione non richiede eccezioni per profilo.
  Applicato `-r` in `TmuxService.send_text`, con il perché nel commento
  (la prossima persona che vede un flag di tmux in mezzo all'argv deve capire
  che è una garanzia, non stile). Test: asserzione su `-r` nell'argv in
  `test_multiline_and_special_text_goes_through_stdin`; suite backend 286
  passati, Ruff pulito. Aggiornata la sezione sull'input in
  `docs/architecture.md`. Chiudere con `TEST-PASTE-01`.

- [x] TEST-PASTE-01 | OWNER: SA-TEST | STATUS: PASSED | Sbloccato da
  `INC-PASTE-01`. Il deploy è **parte di questo check**: la correzione vive
  nel backend e non è verificabile sui soli test. Verificare sull'istanza
  pubblicata, per **ciascun** profilo, che un testo con newline resti
  nell'input senza essere inviato e che l'invio avvenga solo chiamando
  l'endpoint dei tasti; verificare anche che il testo **su riga singola**
  continui a funzionare come prima, che è la regressione più probabile.
  Controllare infine che gli allegati e il percorso di consegna (che usano lo
  stesso meccanismo, `docs/architecture.md`) non siano cambiati di
  comportamento.
  **Deploy già eseguito da `ROOT` (03/08/2026), con verifica di primo livello
  sull'istanza pubblicata — non sostituisce questo check.** Ricreato il solo
  servizio `backend` da un export isolato di `HEAD`, `tmux-runtime` non
  toccato, `web` non ricostruito (frontend invariato), sessioni tmux
  dell'utente intatte. Verifica attraverso il percorso API completo su una
  sessione OpenCode reale: `POST /input` con `"riga uno\nriga due"` →
  `202`, le due righe compaiono **su due righe** nell'input e **non** vengono
  inviate; `POST /input` con testo su riga singola → appeso alla riga corrente,
  ancora non inviato; `POST /keys` con `Enter` → il turno parte. Il contratto
  regge quindi in entrambe le direzioni: il testo è testo, l'invio è un'altra
  operazione. Resta da verificare in modo indipendente il comportamento per
  `codex`, `claude`, `antigravity` e `shell` sull'istanza pubblicata: `ROOT` li
  ha misurati solo su TUI avviate a mano, prima del deploy.
  **Esito (`SA-TEST`, 03/08/2026).** Il buco è coperto: tutti e cinque i
  profili verificati sull'istanza pubblicata, su sessioni di prova create con
  `tmux` in `/tmp` e targettate via API. In ogni TUI (`codex`, `claude`,
  `antigravity`, `opencode`) il testo con newline resta **su due righe**
  nell'input senza essere inviato, il testo su riga singola si appende alla
  riga corrente (`beta` + `gamma` → `betagamma`) senza inviare, e `POST /keys`
  con `Enter` fa partire il turno davvero — su `claude` e `antigravity` con
  risposta reale, quindi la sottomissione è provata, non dedotta.
  Per `shell` il comportamento è diverso **e corretto**: la prima riga viene
  eseguita subito anche con `-r`, perché la modalità canonica del pty consegna
  una riga al processo non appena vede un LF, indipendentemente da come è
  stato prodotto. `-r` cambia cosa transita nel buffer, non la disciplina di
  linea. Nessuna regressione rispetto alle misure pre-deploy.
  Verificati anche i due percorsi che condividono il meccanismo: il percorso
  di consegna degli artefatti (che invia `Enter` in automatico) arriva integro
  e viene sottomesso; gli allegati M2A generano il proprio suffisso multilinea
  e si comportano come qualunque testo multilinea.
  **Dichiarato non verificato:** `attachment_ids` combinato con una TUI reale
  — sarebbe costato un turno a pagamento per ciascun profilo ed è ridondante
  rispetto al caso multilinea già confermato per quegli stessi profili. Lo
  scostamento è registrato invece di essere dato per buono.

## Integrazione OpenCode

**Stato: gate prodotto approvato dall'utente il 03/08/2026. `IMP-OC-00`
(spike host TUI) è aperto; nessuna modifica al prodotto è autorizzata prima
del suo esito.** L'analisi tecnica e la roadmap di riferimento vivono in
`docs/opencode-integration.md`: quel documento è la fonte dei confini e delle
verifiche, questa coda ne è l'esecuzione. Non riaprire né contraddire da qui
le sue conclusioni; se lo spike le smentisce, si aggiorna il documento e si
registra lo scostamento nella voce.

Vale lo stesso protocollo dei subagent già in uso per `HO-*` e `BH-*` (vedi
sopra, "Protocollo della roadmap per i subagent"): nomi logici
`ROOT`/`SA-IMP`/`SA-TEST`, `STATUS` come esito autorevole, rework con suffisso
`-R<n>` e nuovo check `-T<n+1>` a ogni fallimento.

#### OC-00 — Gate prodotto e spike host TUI

- [x] GATE-OC-00 | OWNER: ROOT | STATUS: PASSED | Integrazione approvata
  dall'utente il 03/08/2026. **Confine approvato:** percorso incrementale che
  parte da un profilo TUI eseguito dentro tmux, allo stesso livello di Codex,
  Claude e Antigravity — cioè riusando trasporto, sicurezza e semantica già
  esistenti, senza introdurre un secondo runtime di sessione. Restano
  esplicitamente **fuori** da questa autorizzazione, ciascuno dietro il proprio
  gate successivo: l'adapter sull'API HTTP nativa di OpenCode (`OC-04`), il
  supporto nel runtime Docker (`OC-05`, che richiede una finestra di
  manutenzione perché obbliga a ricreare `tmux-runtime` e a terminare tutte le
  sessioni vive), e qualunque forma di incorporazione di OpenCode Web o di
  esposizione diretta del suo server — quest'ultima non è rimandata, è
  sconsigliata: aggirerebbe l'API tipizzata, la CSRF e l'audit di Mobile Agent
  Console anziché preservarli.
  **Decisioni prese dal gate, vincolanti per le fasi successive:**
  1. Il comando di avvio resta una **costante server-side** in `PROFILE_ARGV`,
     come per gli altri profili. Non diventa un profilo configurabile dal
     client in nessuna fase.
  2. Il flag `--auto` non è il default e non lo diventa: approverebbe
     automaticamente le richieste non negate, cambiando materialmente il
     modello di rischio. Le policy OpenCode restano conservative sulle
     operazioni mutative o esterne, e versionabili solo se prive di segreti.
  3. L'installazione avviene **in host mode**, per lo stesso utente che possiede
     il server tmux, con versione pinnata e upgrade separato dal deploy
     ordinario di `web`/`backend`. Il backend non monta la configurazione né lo
     storage di OpenCode.
  4. L'autenticazione del provider è un'azione **dell'utente**: è interattiva e
     le credenziali non devono mai transitare per il backend né comparire in
     log, audit, snapshot o rapporti dei subagent.
  5. La persistenza di OpenCode (conversazioni, messaggi, credenziali) resta
     **fuori dai backup** di Mobile Agent Console: è fuori dal contratto
     minimizzato attuale.
  6. La separazione fra `agent_kind` e `model_provider` non va introdotta
     incidentalmente nel profilo TUI, ma è **necessaria prima** di attribuire
     quote, consumo o modello a una sessione OpenCode: una sessione OpenCode
     non equivale a un provider specifico. Vincola `OC-03` e qualunque
     estensione di `BH-*` che la incroci.

- [x] IMP-OC-00 | OWNER: ROOT | STATUS: DONE | Spike host TUI: **dimostrare
  che la TUI è controllabile con il protocollo corrente, senza modificare il
  prodotto.** Nessuna modifica a `backend/`, `frontend/` o al deployment in
  questa voce: l'unico output committabile è documentazione più eventuali
  fixture sanitizzate. Se lo spike richiede una modifica di prodotto per
  procedere, ci si ferma e la si registra come esito, non la si fa.
  Primo passo vincolante: **installare OpenCode a versione pinnata** sull'host
  (metodo, versione esatta, checksum se disponibile e procedura di rollback
  vanno documentati nella voce, non solo eseguiti), poi far configurare
  all'utente un provider — l'installazione e il login sono azioni sull'host,
  non nel container.
  Verifica del `PATH` **effettivo** del processo avviato da tmux con login
  shell, non di quello di una shell interattiva: se il binario non è visibile
  lì, il profilo non partirà anche se l'installazione è riuscita. Questo è un
  criterio di uscita, non un dettaglio.
  Matrice di verifiche da eseguire su una sessione tmux avviata a mano, con
  esito riportato per esteso voce per voce:
  1. `pane_current_command` osservato realmente durante l'esecuzione — wrapper
     o runtime possono esporre un nome diverso da `opencode`, e da quel valore
     dipende il riconoscimento del profilo.
  2. Resa ANSI con `capture-pane -e` e xterm.js.
  3. Comportamento su schermo alternativo e disponibilità dello scrollback.
  4. Reazione della TUI ai resize del pane, in particolare su viewport mobile.
  5. Paste di prompt brevi e multilinea via `load-buffer -`/`paste-buffer`,
     con Enter come operazione separata.
  6. Navigazione e risposta a **ciascun** tipo di richiesta di autorizzazione,
     usando solo i tasti già ammessi dall'allowlist.
  7. Interruzione con Escape e Ctrl-C senza lasciare processi orfani.
  8. Avvio in directory consentite con path lunghi e caratteri Unicode.
  9. Resume con più sessioni OpenCode nello stesso repository — è il caso in
     cui `--continue` può agganciare la conversazione sbagliata.
  10. Persistenza dopo riavvio dell'host e comportamento con configurazione o
      autenticazione mancanti.
  11. Assenza di segreti, prompt e output in audit, log, snapshot e backup.
  12. Compatibilità con le sessioni tmux preesistenti e con i client desktop
      collegati allo stesso server.
  Acquisire fixture TUI **sanitizzate** per la classificazione e il parsing
  futuri: servono a `OC-03`, dove i pattern di stato vanno raccolti da output
  reali e non riusati alla cieca da Codex o Claude. Le fixture sono file
  versionati in un repository pubblico: valgono per intero la regola vincolante
  di scansione dei dati personali.
  **Gate di uscita:** nessuna regressione per tmux, nessun segreto nei dati
  acquisiti, flusso base usabile da mobile. Chiudere con `TEST-OC-00`.
  **Avanzamento (03/08/2026, parte eseguibile senza provider).**
  Installazione: `opencode-ai@1.18.11` da npm nel prefisso utente
  (`npm install -g --prefix ~/.local opencode-ai@1.18.11`), **senza `sudo`** e
  senza toccare `/usr` — il prefisso npm di sistema non è scrivibile
  dall'utente, e un'installazione di sistema sarebbe stata la scelta sbagliata
  comunque: il binario deve appartenere allo stesso utente che possiede il
  server tmux. Integrità del tarball dichiarata dal registry:
  `sha512-2omDujweL9HNMCvz18PKUUkdOf5TbbzxhH43nLDHIQrWQIXM2poXjAjKpLyBCLP3LGj6vRNmB+1Q6CLKdV90cQ==`.
  Il pacchetto risolve un binario per piattaforma via dipendenze opzionali
  (`opencode-linux-x64` e varianti musl/baseline). Rollback:
  `npm uninstall -g --prefix ~/.local opencode-ai`, più rimozione di
  `~/.config/opencode` e `~/.local/share/opencode` se si vuole azzerare anche
  stato e credenziali.
  1. **`pane_current_command` = `opencode`**, senza wrapper che ne mascheri il
     nome: il riconoscimento del profilo può basarsi sul valore atteso.
  2. **ANSI**: `capture-pane -e` conserva sequenze *truecolor*
     (`ESC[38;2;R;G;B`) e caratteri di box-drawing UTF-8.
  3. **Schermo alternativo attivo** (`#{alternate_on}` = 1). È la stessa
     condizione che rende inaffidabile la classificazione testuale di stato per
     Antigravity (chrome permanente ripetuto in ogni frame): `OC-03` non dovrà
     dare per scontato che i pattern testuali funzionino, e lo scrollback non
     sarà disponibile per costruzione.
  4. **Resize**: la TUI riflette correttamente a 80x24, 60x24 e 50x22. A **40
     colonne** il suggerimento di piè di pagina si sovrappone al percorso del
     progetto (due stringhe sulla stessa cella); il difetto si auto-ripara
     tornando a una larghezza maggiore. Difetto upstream di rendering, non
     bloccante, ma rilevante per il gate "usabile da mobile": va riverificato
     su viewport reali prima di `OC-01`.
  10. **Autenticazione mancante**: la TUI parte comunque e degrada con un
      suggerimento esplicito (`/connect`), senza errori né uscita — il caso
      "provider non configurato" non è un crash.
  **Correzione registrata durante lo spike:** si era assunto che il resto
  della matrice richiedesse un provider configurato. È falso. Con `auth.json`
  a **zero credenziali** i round funzionano lo stesso, sul modello predefinito
  `Big Pickle` di OpenCode Zen: la TUI mostra il suggerimento `/connect` ma non
  lo impone. L'assunzione è stata smentita dall'uso reale, non dai documenti.
  Conseguenza per `OC-01`: una sessione OpenCode creata da Mobile Agent
  Console è operativa **senza** che nessuno abbia configurato nulla, quindi il
  prerequisito host si riduce al solo binario e non protegge da un uso
  involontario.
  **Seguito della matrice (stessa data, senza credenziali).**
  5. **Paste multilinea — DIFETTO.** Il testo passato con
     `load-buffer -`/`paste-buffer` perde i newline **silenziosamente**, senza
     nemmeno sostituirli con uno spazio: `AAA\nBBB` diventa `AAABBB`,
     `CCC\n\nDDD` diventa `CCCDDD`. Le parole a cavallo di riga si saldano e
     il prompt cambia significato. Riguarda direttamente il percorso di input
     del prodotto, che è multilinea per natura.
     *(Rettificato da `IMP-OC-00-R2`. Questo punto conteneva **due** errori,
     non uno. La diagnosi era sbagliata: il newline non veniva perso da
     OpenCode, veniva convertito in CR da `paste-buffer` invocato senza `-r`
     — un difetto del prodotto, non della TUI, tracciato e corretto in
     `INC-PASTE-01`. E la conclusione era falsa: qui si leggeva "è confermato
     che **Enter resta un'operazione separata**", mentre con un newline il
     messaggio partiva da solo. L'osservazione originale su cui si fondava
     quella frase — il comando che compare in palette senza essere eseguito —
     era corretta ma riguardava un paste **su riga singola**, e da essa era
     stata generalizzata una garanzia che il caso multilinea non aveva. Con
     `-r` applicato, entrambi i comportamenti sono ora quelli attesi su tutti
     i profili, verificati sull'istanza pubblicata da `TEST-PASTE-01`.)*
  6. **Richieste di autorizzazione — di norma assenti, ma esistono.**
     *(Rettificato da `IMP-OC-00-R1`: la formulazione originale diceva
     "nessuna osservata" ed è stata falsificata da `TEST-OC-00`, che ne ha
     vista una reale con azioni `Allow once`/`Allow always`/`Reject`. Non è
     riproducibile in modo deterministico e sembra dipendere dalla decisione
     del modello nel singolo turno.)* Con configurazione
     vuota (`~/.config/opencode/opencode.jsonc` contiene solo `$schema`) e
     **senza** `--auto`, l'agente ha eseguito comandi di shell (`wc -l`,
     `ls -la`) **senza chiedere alcuna conferma**. Il permesso di eseguire
     comandi è quindi il comportamento predefinito, non un'opzione da
     attivare. È il risultato più rilevante dello spike per il threat model:
     la decisione 2 del gate ("`--auto` non è il default") non basta, perché
     il default è già permissivo di suo. `OC-01` non può limitarsi ad
     aggiungere l'argv: deve rilasciare una policy dei permessi esplicita e
     conservativa, altrimenti creare una sessione OpenCode da mobile equivale
     a concedere esecuzione di comandi non sorvegliata con i privilegi
     dell'utente host.
  7. **Interrupt — parziale.** Un solo `Escape` non interrompe: la TUI passa a
     `esc again to interrupt`, quindi ne servono due. Il secondo non è stato
     dimostrato su un round davvero lungo, perché il round si è concluso da
     solo prima: l'interruzione pulita **resta non verificata** e non va data
     per buona. `Ctrl-C` non è stato provato. Nessun processo orfano rilevato
     dopo il round, ma con un round concluso normalmente è evidenza debole.
  9. **Resume — l'ambiguità è reale e riproducibile.** `opencode --continue`
     riprende correttamente la conversazione quando ce n'è una sola. Con
     **due** conversazioni nella stessa cartella riprende la **più recente**:
     creata una seconda conversazione distinta, `--continue` ha restituito
     quella e non la prima. Conferma sul campo il motivo per cui `OC-02` deve
     partire dal selettore nativo (strategia B) e non da `--continue`: una
     sessione archiviata da Mobile Agent Console verrebbe riagganciata alla
     conversazione sbagliata senza alcun segnale all'utente.
     `opencode session list` esiste e restituisce identificatori nella forma
     `ses_<alfanumerico>`, con titolo e data — quindi la strategia C è
     tecnicamente praticabile e l'ID è vincolabile con un pattern severo.
     **Attenzione al confine:** i titoli sono generati dal contenuto della
     conversazione, quindi esporre un elenco di sessioni OpenCode
     significherebbe esporre contenuto, non solo identificatori.
     *(Rettificato da `IMP-OC-00-R1`: il rischio è più ampio di come descritto
     qui. Lo store non è per progetto ma **globale per utente** —
     `opencode session list` eseguito in una directory vuota mai toccata
     elenca conversazioni di altri progetti dell'host. Quindi l'elenco non
     esporrebbe il contenuto delle conversazioni di questo progetto, ma di
     tutti. In una cartella nuova `--continue` produce inoltre un errore
     grezzo di server invece di dichiarare che non c'è nulla da riprendere.)*
  12. **Nessuna regressione per tmux.** Le cinque sessioni preesistenti
      dell'utente sono rimaste intatte per tutta la durata dello spike; tutte
      le sessioni sonda sono state rimosse. `tmux-runtime` mai coinvolto: lo
      spike vive interamente sul server tmux dell'host.
  **Chiusura della matrice (stessa data).**
  7. **Interrupt — completato, con una scoperta seria.** Su un round
     realmente lungo il **doppio `Escape` interrompe correttamente**: la TUI
     segna il turno come `interrupted`, restano solo i thread di `opencode` e
     nessun processo di shell superstite. **`Ctrl-C` invece non interrompe:
     termina l'intero agente.** Con `exec opencode` come comando del pane, la
     sessione tmux muore insieme a lui — verificato, la sessione è sparita
     dall'elenco e la conversazione in corso non è stata salvata. `C-c` è
     nell'allowlist dei tasti di Mobile Agent Console: oggi un utente che lo
     preme per fermare un turno **perde la sessione**. `OC-01` deve decidere
     esplicitamente cosa fare di `C-c` per questo profilo, non ereditarlo.
  8. **Path lunghi e Unicode — nessun problema.** Avvio corretto in una
     directory di 194 caratteri con accenti latini e ideogrammi CJK;
     `pane_current_path` esatto, `pane_current_command` sempre `opencode`, e
     il piè di pagina manda a capo il percorso senza corrompere i glifi.
  10. **Persistenza — parziale, e il limite è dichiarato.** Lo stato
      sopravvive alla chiusura del processo: uccisa la sessione tmux,
      `--continue` ha ripreso la conversazione. La persistenza attraverso un
      **riavvio dell'host non è verificabile in questa finestra** e non va
      considerata provata: lo stato vive su filesystem
      (`~/.local/share/opencode`, `~/.local/state/opencode`) e per costruzione
      sopravvive, ma ciò che non sopravvive è la sessione tmux, che è il vero
      contenitore del profilo.
  11. **Dati locali — nessuna esposizione lato Mobile Agent Console.**
      `~/.local/share/opencode` contiene `log/`, `repos/` e `snapshot/`;
      quest'ultimo è un git bare **per progetto**, inizializzato ma vuoto
      (zero commit) — il meccanismo per copiare file di progetto nello storage
      di OpenCode quindi esiste, anche se qui non ha ancora prodotto nulla, ed
      è un motivo in più per la decisione 5 del gate. `auth.json` è assente,
      coerente con l'uso senza credenziali. Il log **non** contiene il testo
      dei prompt né delle risposte (cercate stringhe distintive dei turni di
      prova: zero occorrenze), ma registra i **percorsi dei file toccati** e
      le directory di lavoro. Lato repository: nessun riferimento a
      `opencode` nel codice di prodotto (corretto, `OC-00` non lo consente) e
      gli unici script di deploy sono `snapshot-env.sh` e `tls-renew.sh`, che
      non toccano `~/.local/share` né `~/.config`. Nessun percorso di backup o
      audit di Mobile Agent Console ingerisce oggi dati di OpenCode.
  **Difetto aggiuntivo trovato durante la cattura delle fixture: l'input
  inviato subito dopo l'avvio viene scartato in silenzio.** Osservato due
  volte su due sessioni distinte: il primo `paste-buffer` dopo l'avvio della
  TUI non compare nell'input e l'`Enter` successivo non produce nulla; ripetuto
  a TUI stabilizzata, lo stesso testo entra ed esegue. Per `OC-01` significa
  che creare una sessione e inviarle subito un prompt — esattamente quello che
  fa un utente da mobile — può perdere il primo messaggio senza alcun segnale.
  Serve una condizione di prontezza osservabile, non una `sleep` a caso.
  **Fixture acquisite:** sei frame reali in
  `backend/tests/fixtures/opencode-tui/`, sanitizzati (l'unico dato variabile
  era il percorso del progetto), con un README che ne dichiara provenienza e
  limiti. Manca il frame di richiesta di autorizzazione perché in questo
  spike non se ne è presentata nessuna — *rettificato da `IMP-OC-00-R1`: la
  formulazione originale sosteneva che OpenCode non ne producesse mai, ed è
  stata falsificata da `TEST-OC-00`. Il frame va provocato deliberatamente
  prima di scrivere il classificatore di `OC-03`.*
  Verificato sui frame, non assunto: `esc interrupt` compare solo nel
  frame attivo e `interrupted` solo in quello interrotto, quindi i due
  marcatori sono discriminanti; sei frame di un solo turno restano comunque
  una base insufficiente per un classificatore.
  **Resta non verificato:** il punto 2 solo per la parte xterm.js — gli ANSI
  sono confermati su `capture-pane -e`, ma la resa effettiva nel terminale
  della PWA non è stata osservata, e richiederebbe un browser.

- [x] TEST-OC-00 | OWNER: SA-TEST | STATUS: FAILED | Sbloccato da
  `IMP-OC-00` (commit dello spike; nessuna modifica al prodotto).
  Verifica indipendente dello spike: rieseguire la matrice sui punti
  riproducibili senza fidarsi del rapporto dell'implementatore, controllare che
  le fixture acquisite siano davvero prive di segreti, prompt e percorsi
  personali (ispezione dell'insieme completo delle stringhe, non a campione),
  e confermare che nessuna sessione tmux preesistente sia stata persa o
  alterata dallo spike. Verificare inoltre che il repo non contenga modifiche
  di prodotto: `IMP-OC-00` non è autorizzata a farne.
  **Esito (`SA-TEST`, 03/08/2026).** Confermati: nessuna modifica di prodotto
  (i tre commit toccano solo `docs/backlog.md` e le fixture), nessuna sessione
  tmux dell'utente persa, fixture prive di dati personali all'ispezione
  integrale, scansione dati personali senza occorrenze, tre suite verdi
  (286/59/56). Riprodotte e confermate le affermazioni su installazione, round
  senza credenziali, esecuzione di comandi senza conferma, `Ctrl-C` che uccide
  la sessione, doppio `Escape` che interrompe pulito, warm-up che scarta il
  primo invio (in un caso **due** invii), path lunghi/Unicode,
  `pane_current_command`, schermo alternativo, log senza testo dei turni.
  Verificata sui file anche l'affermazione del README sui marcatori
  `esc interrupt`/`interrupted`: vera.
  **Tre difetti che motivano il `FAILED`**, tutti riverificati da `ROOT` prima
  di accettarli:
  1. **Il paste multilinea si auto-invia.** Atteso: il testo incollato resta
     nell'input, perché in Mobile Agent Console l'invio di Enter è
     un'operazione separata e distinta. Ottenuto: con un `\n` incorporato il
     messaggio parte da solo. Riprodotto da `ROOT` con gli stessi flag usati
     dal prodotto: `AAA\nBBB` è stato inviato senza alcun `send-keys Enter`.
  2. **`--continue` è più pericoloso di come lo aveva descritto lo spike.**
     Non è ambiguità *fra conversazioni della stessa cartella*: lo store è
     **globale per utente**. Verificato da `ROOT`: `opencode session list`
     eseguito in una directory vuota mai toccata prima elenca conversazioni di
     altri progetti dell'host. In una cartella nuova `--continue` ha inoltre
     restituito un errore grezzo di server invece di dichiarare che non c'è
     nulla da riprendere.
  3. **La richiesta di autorizzazione esiste.** Lo spike affermava che
     OpenCode non ne avesse "mai prodotta una". `SA-TEST` ne ha osservata una
     reale, con azioni `Allow once`/`Allow always`/`Reject` su un pattern di
     percorsi, non riproducibile in modo deterministico. `ROOT` non è
     riuscito a riprodurla: l'affermazione categorica va comunque ritirata,
     perché una sola osservazione credibile basta a falsificarla, mentre
     nessun numero di tentativi falliti basta a confermarla.
     *(Chiuso definitivamente il 03/08/2026 leggendo la documentazione
     ufficiale dei permessi: il comportamento **non era casuale**. Quasi tutti
     i permessi predefiniscono ad `allow`, tranne `external_directory` e
     `doom_loop` che predefiniscono ad `ask` — la richiesta osservata
     riguardava un accesso fuori dalla directory di progetto ed era quindi
     deterministica. Mancava la conoscenza della regola, non la
     riproducibilità. Due round hanno descritto quello stato prima come
     inesistente e poi come non deterministico, e in entrambi i casi la causa
     è stata dedurre il comportamento dall'osservazione senza cercare se
     fosse documentato.)*

- [x] IMP-OC-00-R1 | OWNER: ROOT | STATUS: DONE | Rework documentale dei tre
  difetti di `TEST-OC-00`. Nessuna modifica al prodotto: il gate `OC-00` non
  la consente, e il difetto 1 ne richiederebbe una.
  **Difetto 1 — causa individuata, e non è di OpenCode.** `TmuxService.send_text`
  invoca `paste-buffer -b … -t … -d` **senza `-r`**. Il manuale di tmux è
  esplicito: in assenza di `-r` ogni LF del buffer viene sostituito con un
  separatore, per default **CR** — cioè un Invio. Il testo multilinea del
  prodotto non arriva quindi mai come testo multilinea: arriva come righe
  separate da Invio. Verifica differenziale eseguita sulla stessa sessione:
  con i flag attuali `AAA\nBBB` si è auto-inviato e il newline è sparito; con
  `paste-buffer -r` lo stesso testo è rimasto nell'input **su due righe** e
  **non** è stato inviato. La correzione è un singolo flag, ma è una modifica
  di prodotto che tocca tutti i profili, quindi va aperta come voce propria e
  verificata anche contro Codex, Claude e Antigravity prima di essere
  applicata: vedi `INC-PASTE-01`.
  **Difetto 2 — corretta la caratterizzazione** nella voce `IMP-OC-00`: il
  rischio non è l'ambiguità dentro un progetto ma l'esposizione trasversale
  di tutte le conversazioni dell'utente. Rafforza, non indebolisce, la
  decisione di `OC-02` di partire dal selettore nativo, e aggiunge un vincolo:
  un eventuale elenco di sessioni esposto da Mobile Agent Console mostrerebbe
  titoli generati dal contenuto di conversazioni di **altri** progetti.
  **Difetto 3 — ritirata l'affermazione categorica** in `IMP-OC-00` e nel
  `README.md` delle fixture, sostituita dalla formulazione verificabile: di
  norma non chiede, ma esiste un percorso di autorizzazione non ancora
  caratterizzato. Per il classificatore di `OC-03` è il caso peggiore — uno
  stato raro non viene coperto per caso — quindi il frame va provocato
  deliberatamente prima di scrivere il classificatore, non atteso.

- [x] TEST-OC-00-T2 | OWNER: SA-TEST | STATUS: FAILED | Sbloccato da
  `IMP-OC-00-R1`. Il rework è documentale: verificare che le tre correzioni
  siano effettivamente riportate in `IMP-OC-00` e nel `README.md` delle
  fixture, che non sia rimasta da nessuna parte l'affermazione "nessuna
  richiesta di autorizzazione osservata", e che `INC-PASTE-01` esista e
  descriva il difetto in modo riproducibile. Non rieseguire l'intera matrice:
  dichiarare esplicitamente cosa è stato ricontrollato e cosa no. Confermare
  che il repository continui a non contenere modifiche di prodotto.
  **Esito (`SA-TEST`, 03/08/2026).** Confermati: le rettifiche dei difetti 2 e
  3 sono presenti e coerenti in `IMP-OC-00` e nel `README.md` delle fixture;
  nessuna affermazione categorica attiva sull'assenza di richieste di
  autorizzazione sopravvive nel repository (le due occorrenze restanti sono
  citazioni dentro le rettifiche, correttamente classificate come tali);
  `INC-PASTE-01` è riproducibile da sola, senza contesto aggiuntivo; i quattro
  commit dello spike toccano solo `docs/` e fixture, mai `backend/app/`,
  `frontend/src/` o `deploy/`; scansione dati personali senza occorrenze;
  stati della sezione coerenti, nessuna fase sbloccata da un `DONE` senza un
  `SA-TEST` `PASSED`.
  **Difetto che motiva il `FAILED`:** la rettifica del difetto 1 **non è mai
  stata applicata**. Il punto 5 della matrice in `IMP-OC-00` è rimasto
  invariato — `git show a09a81e -- docs/backlog.md` non tocca quelle righe —
  e continuava ad affermare "è confermato che **Enter resta un'operazione
  separata**", cioè esattamente la frase che `TEST-OC-00` aveva falsificato.
  `IMP-OC-00-R1` aveva discusso la causa e aperto `INC-PASTE-01`, ma aveva
  lasciato l'errore nella voce che l'aveva originato. Riproduzione:
  `sed -n '3114,3124p' docs/backlog.md` confrontato con l'esito di
  `TEST-OC-00`.
  Segnalato inoltre un riferimento obsoleto: `IMP-OC-01` diceva "Sbloccato da
  `TEST-OC-00` `PASSED`", mentre quel tentativo è chiuso `FAILED` in modo
  permanente. Non causava uno sblocco indebito, ma era fuorviante.

- [x] IMP-OC-00-R2 | OWNER: ROOT | STATUS: DONE | Rework del difetto di
  `TEST-OC-00-T2`. Il punto 5 di `IMP-OC-00` conteneva **due** errori, non
  solo la frase segnalata, e la rettifica scritta ora li ritratta entrambi:
  la **diagnosi** era sbagliata — il newline non veniva perso da OpenCode ma
  convertito in CR da `paste-buffer` senza `-r`, difetto del prodotto tracciato
  in `INC-PASTE-01` — e la **conclusione** era falsa, perché con un newline il
  messaggio partiva da solo. Registrato anche come nacque l'errore, che è la
  parte riutilizzabile: l'osservazione di partenza era corretta ma riguardava
  un paste **su riga singola**, e da quella era stata generalizzata una
  garanzia che il caso multilinea non aveva. Corretto anche il riferimento
  obsoleto in `IMP-OC-01`, ora legato all'ultimo tentativo `SA-TEST` con esito
  `PASSED` invece che a un tentativo chiuso `FAILED`.
  **Nota di metodo:** due round di verifica sono serviti a scoprire che una
  correzione dichiarata non era stata applicata. `IMP-OC-00-R1` elencava tre
  difetti corretti; due lo erano davvero. Dichiarare una correzione e farla
  sono eventi distinti, e solo il secondo lascia traccia nel diff — è lì che
  va cercata la prova, non nella voce che se ne attribuisce il merito.

- [x] TEST-OC-00-T3 | OWNER: SA-TEST | STATUS: PASSED | Sbloccato da
  `IMP-OC-00-R2`. Verificare che il punto 5 di `IMP-OC-00` porti ora una
  rettifica che ritratta **sia** la diagnosi **sia** la conclusione, e che nel
  file non sopravviva altrove un'affermazione secondo cui l'invio resterebbe
  separato anche nel caso multilinea. Ricontrollare, con lo stesso metodo che
  ha trovato questo difetto, che **ciascuna** correzione dichiarata da
  `IMP-OC-00-R1` e `IMP-OC-00-R2` compaia davvero nel diff dei rispettivi
  commit, invece di fidarsi dell'elenco nella voce. Confermare che il
  riferimento in `IMP-OC-01` non punti più a un tentativo `FAILED`. Non
  rieseguire la matrice dello spike.
  **Esito (`SA-TEST`, 03/08/2026).** `PASSED`. Ogni correzione dichiarata è
  stata confrontata con il diff del proprio commit, una per una: delle tre di
  `IMP-OC-00-R1`, due erano presenti e la terza (punto 5) risultava assente —
  riconfermando dal diff il difetto trovato da `TEST-OC-00-T2` — ed è ora
  applicata da `IMP-OC-00-R2`, il cui diff contiene entrambe le correzioni
  dichiarate. Il punto 5 ritratta ora sia la diagnosi sia la conclusione, come
  frase attiva e non come semplice citazione. Nessuna affermazione attiva
  residua nel repository: le occorrenze superstiti sono citazioni dentro le
  rettifiche, voci di checklist di verifiche future, o testo che descrive lo
  stato attuale e vero dopo il fix di `INC-PASTE-01`. Riferimento di
  `IMP-OC-01` aggiornato, stati coerenti, scansione dati personali senza
  occorrenze. **Fase `OC-00` chiusa**: lo spike è verificato e `IMP-OC-01`
  passa a `READY`.
  Verifica di secondo livello da `ROOT` sull'affermazione centrale, perché è
  lo stesso controllo fallito in `R1`: `git show 53a45b2` rimuove la riga
  "è confermato che **Enter resta un'operazione separata**" e introduce la
  rettifica; `git show a09a81e` non toccava quelle righe.

#### OC-01 — Profilo TUI di base

- [x] IMP-OC-01 | OWNER: SA-IMP | STATUS: DONE | Sbloccato dall'ultimo
  tentativo `SA-TEST` di `OC-00` con esito `PASSED` — oggi `TEST-OC-00-T3`.
  Il riferimento originale era a `TEST-OC-00`, che è chiuso `FAILED` in modo
  permanente: un tentativo fallito non si riapre e non sblocca nulla.
  Creare e controllare sessioni OpenCode dalla PWA come terminali
  generici: aggiungere `opencode` alle union backend/frontend, argv costante
  server-side, aggiornare creazione, fake e test, mostrare il profilo nel
  selettore. Mantenere inizialmente la sola vista Terminale se "Blocchi" non è
  ancora affidabile per questa TUI. Documentare il prerequisito host e il
  messaggio d'errore quando il binario manca — un profilo che fallisce in
  silenzio perché `opencode` non è nel `PATH` di tmux è il modo più probabile
  in cui questa fase si rompe in produzione.
  **Decisioni di `ROOT` prese all'apertura (03/08/2026), da non rinegoziare
  in implementazione:**
  - **Policy dei permessi: conservativa** — conferma richiesta per
    l'esecuzione di comandi **e** per le scritture su file; letture libere.
    Scelta dall'utente il 03/08/2026, ed è la lettura fedele della decisione
    già approvata in `GATE-OC-00` ("conservative per le operazioni mutative o
    esterne"). Allinea inoltre OpenCode al comportamento che l'utente già
    conosce da Codex.
  - **Meccanismo: variabile d'ambiente della sessione tmux**, non un file
    sull'host. OpenCode supporta `OPENCODE_CONFIG_CONTENT` (verificato nel
    binario 1.18.11), e `tmux new-session` accetta `-e VAR=valore`: la policy
    diventa così una **costante server-side** come l'argv, senza dipendere da
    un file da deployare e senza mai passare da una stringa di shell.
    Verificato sul campo che un JSON attraversa `tmux -e` integro, virgolette
    comprese. Il backend continua a non montare `~/.config/opencode`, come
    prescrive l'analisi.
    **Schema confermato dalla documentazione ufficiale**
    (`https://opencode.ai/docs/permissions/`): chiave `permission`, valori
    `allow`/`ask`/`deny`, chiavi fra cui `read`, `edit`, `bash`, `webfetch`,
    `websearch`, `external_directory`; sono ammessi pattern granulari
    (`"git *": "allow"`, `"rm *": "deny"`). La policy conservativa di questo
    round è quindi `{"permission":{"bash":"ask","edit":"ask"}}`, verificata
    end-to-end: con `bash:"deny"` l'agente dichiara di non avere lo strumento
    (il tool viene rimosso dal set, non bloccato alla chiamata); con
    `bash:"ask"` compare il dialog `Permission required` con
    `Allow once`/`Allow always`/`Reject`, acquisito come fixture
    `07-autorizzazione.txt`.
    **Rischio da accettare consapevolmente:** `OPENCODE_CONFIG_CONTENT` esiste
    nel binario e funziona, ma **non è documentata**. Un `opencode upgrade`
    potrebbe rimuoverla senza preavviso e la policy smetterebbe di essere
    applicata **in silenzio** — l'agente tornerebbe permissivo e nulla lo
    segnalerebbe. `IMP-OC-01` deve quindi prevedere una verifica di efficacia
    della policy all'avvio della sessione, o in mancanza di quella un test
    automatico che fallisca se il meccanismo smette di funzionare: un
    invariante di sicurezza che dipende da un'API non documentata va
    sorvegliato, non dato per acquisito.
  - **Resume: non usare `--continue`.** Lo store delle conversazioni è
    globale per utente, quindi `--continue` può agganciare la conversazione di
    un altro progetto. Per `OC-01` il profilo di ripresa avvia OpenCode
    normalmente; l'aggancio alla conversazione giusta è materia di `OC-02`,
    che partirà dal selettore nativo.
  - **`C-c` resta nell'allowlist e non viene intercettato.** Mobile Agent
    Console è un terminale generico: inoltra i tasti, e `C-c` fa quello che
    farebbe in un terminale vero. Bloccarlo per un profilo significherebbe far
    dipendere la semantica dei tasti dall'agente, cioè il contrario di ADR
    002. Va invece **documentato** che per OpenCode l'interruzione è il doppio
    `Escape` e che `C-c` chiude la sessione.
  **Due prerequisiti aggiunti dallo spike, senza i quali questa voce non è
  la modifica contenuta che sembrava all'inizio:**
  1. **Policy dei permessi esplicita.** Con la configurazione predefinita
     OpenCode esegue comandi di shell senza chiedere conferma. Aggiungere
     l'argv e basta significherebbe offrire da mobile un agente che esegue
     comandi non sorvegliati con i privilegi dell'utente host, dentro
     `MAC_ALLOWED_ROOTS`. La policy va decisa e rilasciata **in questo
     round**, non rimandata a `OC-03`.
  2. **Decidere cosa fare di `C-c` per questo profilo.** `Ctrl-C` non
     interrompe il turno: termina l'agente, e con `exec opencode` la sessione
     tmux muore con lui. `C-c` è nell'allowlist dei tasti, quindi un utente
     che lo preme per fermare un turno perde la sessione. L'interruzione
     corretta è il doppio `Escape`.
  Tenere inoltre presente il difetto di warm-up: l'input inviato subito dopo
  l'avvio viene scartato in silenzio, quindi creare una sessione e inviarle
  subito un prompt — cioè il gesto naturale da mobile — può perdere il primo
  messaggio. Serve una condizione di prontezza osservabile, non una `sleep`.
  **Gate:** creazione, prompt, output, tasti speciali e terminazione verificati
  sull'istanza pubblicata.
  **Esito (`SA-IMP`, 03/08/2026).** Implementato il profilo `opencode` come
  unione chiusa in tutte le superfici verificate direttamente nel codice
  (non solo dall'elenco di `docs/opencode-integration.md`):
  - `backend/app/services/tmux_service.py`: `PROFILE_ARGV`/`RESUME_PROFILE_ARGV`
    condividono lo stesso argv (`_OPENCODE_LAUNCH`) per avvio e ripresa —
    nessun `--continue`. Nuovo `PROFILE_ENV`, usato da `create_session` per
    aggiungere `-e OPENCODE_CONFIG_CONTENT=...` a `new-session` solo per
    questo profilo: la policy resta una costante server-side, mai una
    stringa costruita da input client, e nessun altro profilo la riceve.
  - Binario mancante: l'argv del profilo (`_missing_binary_shell_command`)
    esegue `command -v opencode` nella stessa login shell che tmux userebbe
    e, se assente, stampa un messaggio comprensibile e lascia la sessione
    viva in `bash -l` invece di lasciarla sparire in silenzio (comportamento
    di default oggi per qualunque profilo il cui unico processo termini
    subito). Verificato dal vivo con un binario fittizio: senza questo ramo
    la sessione tmux spariva entro pochi decimi di secondo, con la API che
    aveva comunque risposto `201`.
  - Schemi Pydantic (`backend/app/schemas.py`): `opencode` aggiunto a
    `CreateSessionInput.profile`, `ArchivedSessionView.profile`,
    `SnapshotSelectionInput.mode`, `SnapshotSessionView.mode`.
  - `ArchiveService.PROFILES` e `SnapshotService.SNAPSHOT_MODES`
    (`backend/app/services/archive_service.py`,
    `backend/app/services/snapshot_service.py`) estesi.
  - `session_profile()` in `backend/app/main.py` riconosce `opencode` da
    `pane_current_command` (confermato `== "opencode"` senza wrapper dallo
    spike). `restore_snapshot()` aveva un ramo chiuso che avrebbe silenziato
    `opencode` a shell semplice al restore (stesso bug-shape già evitato per
    `antigravity`): aggiunto un ramo dedicato che rilancia il profilo e
    dichiara esplicitamente che la ripresa della conversazione resta manuale
    (selettore nativo `/sessions`, materia di `OC-02`). `restore_archive()`
    non ha richiesto modifiche: è già generico su qualunque profilo valido.
  - Frontend: `frontend/src/api.ts` (`SessionProfile`, `SnapshotMode`,
    `ArchivedSession.profile`) e `frontend/src/App.tsx` (selettore di
    creazione, euristica e selettore di `SnapshotModal`) estesi. **Non**
    aggiunto a `agentic`/`inferredProvider`/polling di `AgentStatusService`:
    quella classificazione riconosce solo Codex/Claude/Antigravity (decisione
    6 di `GATE-OC-00`, materia di `OC-03`), quindi il profilo resta
    intenzionalmente in sola vista Terminale, come richiesto.
  - `backend/tests/fakes.py`: `FakeTmux` accetta `opencode` nella mappa
    profilo→comando osservato.
  - Test aggiunti (9 casi nuovi, +10 nella suite contando il caso aggiunto a
    un test esistente): `test_tmux_service.py` (argv identico avvio/ripresa
    senza `--continue`/`--session`; sorveglianza della policy — fallisce se
    `OPENCODE_CONFIG_CONTENT` smette di essere passata a `new-session`, e
    verifica che gli altri profili non la ricevano; due test che eseguono
    realmente `_missing_binary_shell_command` con `bash` — non mockato, non
    tmux — sia con un binario inesistente sia con uno presente; un test sul
    contenuto del messaggio), `test_api.py` (creazione sessione `opencode`
    end-to-end sul fake; restore di uno snapshot `opencode` che non degrada
    a shell semplice e non inietta testo), `test_snapshot_service.py`
    (round-trip del modo `opencode`), `test_database.py` (ciclo
    archivio→restore completo con DB reale, profilo `opencode` preservato).
  - Documentazione: nuova sezione "OpenCode (profilo TUI)" in
    `docs/architecture.md` (prerequisito host, meccanismo della policy,
    doppio `Escape` vs `C-c`, comportamento a binario mancante) più
    aggiornamento dei paragrafi su archivio/snapshot che elencavano i
    profili; `docs/api-contract.md` aggiornato dove enumera profili e
    modalità. `docs/opencode-integration.md` non modificato: nessuna delle
    sue conclusioni è stata smentita da questo round.
    `frontend/src/App.tsx`: `LATEST_RELEASE` aggiornato.
  **Interpretazioni della voce, dichiarate come tali:**
  1. Il "test automatico di sorveglianza" per `OPENCODE_CONFIG_CONTENT`
     richiesto dalla voce è stato letto come: un test che fallisce se il
     backend smette di *passare* la variabile a `new-session` (verificato).
     Non copre il caso in cui un futuro `opencode upgrade` smetta di
     *onorarla* lato binario — quel rischio resta accettato esplicitamente,
     come previsto dalla voce, e richiederebbe una verifica di efficacia
     runtime (chiedere a OpenCode il permesso effettivo su `bash`, se un
     comando del genere esisterà) che non ho implementato di mia iniziativa,
     come la voce stessa invitava a fare: la propongo come miglioramento
     futuro, non necessario per chiudere `OC-01`.
  2. Il prerequisito "binario mancante" è stato risolto con una modifica di
     prodotto (script argv con fallback) invece che con la sola
     documentazione suggerita dal testo della voce. L'ho preferito perché
     verificabile in unit test senza tmux reale e perché rende l'errore
     visibile esattamente dove l'utente guarda (il terminale), invece di
     affidarsi a un operatore che consulti la documentazione dopo aver visto
     una sessione sparire. Ho scartato un'alternativa (probe tramite una
     sessione tmux usa-e-getta) perché avrebbe introdotto una sessione tmux
     reale, temporaneamente visibile in `list_sessions`, e latenza non
     deterministica su ogni creazione — un rischio sproporzionato rispetto al
     guadagno, dato che la reale esigenza era "errore leggibile", non
     "verifica preventiva".
  3. Nel restore di snapshot ho esteso lo stesso ramo già usato per
     `antigravity` (rilancio diretto del profilo, nessun testo iniettato)
     invece di introdurre un nuovo meccanismo: è la lettura più fedele di
     "il profilo di ripresa avvia OpenCode normalmente" applicata al percorso
     di snapshot, che il testo della voce non menzionava esplicitamente
     riga per riga.
  **Suite (03/08/2026):** `docker compose run --rm backend-test` →
  **296 passati**, Ruff pulito (era 286 prima di questo round, +10 test
  dedicati a OpenCode). `python3 -m unittest discover -s deploy/tests` →
  **59 passati** (invariato, nessuna modifica in `deploy/`). `npm run
  test:ui` → **56 passati**. `npm run build` → pulito (`tsc -b` + `vite
  build`). `docker compose config --quiet` → nessun errore.
  **Verifica su dati reali (vincolante).** Eseguita due volte: una prima
  volta a mano con uno script bash equivalente, e una seconda volta
  importando direttamente `TmuxService`/`PROFILE_ARGV`/`PROFILE_ENV` dal
  modulo reale (non un fake) per escludere ogni scarto fra quanto verificato
  e quanto verrà eseguito in produzione. Sessione `sai-oc-codepath` creata
  con `create_session(..., "opencode")` sul socket tmux di default
  dell'host: `pane_current_command` risultante `opencode`, coerente con
  `IMP-OC-00`. Inviato via `send_text`/`send_key` (stesso percorso
  `load-buffer`/`paste-buffer -r` del prodotto) il prompt "run the shell
  command `whoami` and tell me the output": il modello ha eseguito il
  comando ed è comparso il dialog `△ Permission required` con `Allow
  once`/`Allow always`/`Reject` sul comando `whoami` — la policy
  `{"permission":{"bash":"ask","edit":"ask"}}` consegnata via
  `OPENCODE_CONFIG_CONTENT` è quindi effettivamente applicata end-to-end, non
  solo presente nell'argv registrato dai test. Verificato anche il difetto di
  warm-up già noto (`IMP-OC-00`): il primo invio a 1.5s dall'avvio è stato
  scartato in silenzio, il secondo a TUI stabilizzata è arrivato. Sessione di
  prova terminata con doppio `Escape` + `kill-session` espliciti; nessuna
  sessione utente toccata da questi comandi (sempre mirati per `-t
  sai-oc-codepath`).
  **Anomalia osservata durante la verifica, per trasparenza (non causata da
  questa voce per quanto accertato).** Durante le ~3 ore di lavoro su questa
  voce, due delle quattro sessioni tmux preesistenti indicate come lavoro
  vivo dell'utente sono scomparse dall'elenco: prima una il cui nome
  descriveva un'infrastruttura personale (redatto qui perché un dettaglio di
  infrastruttura, coerente con l'indicazione di non versionarli — nome
  esatto nel rapporto di chiusura di questa sessione, non versionato), poi
  anche `RefreshOverview` (`Mac` e `Test video` sono rimaste intatte, stessi
  timestamp di creazione dall'inizio alla fine). Nessun comando eseguito in
  questa voce ha mai referenziato quei due nomi: ogni `kill-session`,
  `send-keys` e `capture-pane` di questa voce ha usato un `-t` esplicito
  verso sessioni proprie con prefisso `sai-oc-`, mai un comando "corrente"
  senza target. Verificato inoltre che non ci fossero eventi OOM nel kernel
  log e che nessun processo collegato alla prima sessione risultasse ancora
  in corso al momento del controllo. Il crontab dell'host mostra un
  orchestratore esterno (fuori da questo repository) con più job ogni 5 minuti che generano e
  chiudono sessioni Claude Code programmate (`check-wakeups`), oltre a un job
  settimanale chiamato letteralmente "refresh overview progetti" — coerente
  con `RefreshOverview` come sessione effimera che ha semplicemente concluso
  il proprio compito, non con un'interruzione causata da questa voce. Non ho
  gli elementi per una conferma definitiva (richiederebbe i log di quel
  componente, fuori dal perimetro di questo repository), quindi lo riporto
  come osservazione, non come fatto accertato: se `ROOT`/l'utente vogliono
  la certezza, i log dell'orchestratore per la finestra 20:30–23:40 del
  03/08/2026 lo chiarirebbero.
  **Scansione dati personali sul diff:** nessuna occorrenza di percorsi
  assoluti della macchina, username, hostname/IP Tailscale, token o nomi di
  progetti privati — i soli riferimenti a directory nei test sono `/tmp`,
  `/workspace` e `tmp_path` di pytest, già lo standard del resto della suite.
  *(Rettificato da `IMP-OC-01-R1`: **questa dichiarazione era falsa.** Il diff
  introduceva tre volte il nome di un progetto privato dell'utente, nel
  paragrafo sull'anomalia delle sessioni. Il pattern `grep` di riferimento non
  lo intercettava — cerca percorsi, indirizzi e token, non nomi propri — e chi
  ha eseguito il controllo ha letto l'esito del comando invece del proprio
  diff. Corretto prima della pubblicazione.)*
  Porto `TEST-OC-01` da assente a `READY_FOR_TEST` (vedi sotto).

- [x] TEST-OC-01 | OWNER: SA-TEST | STATUS: FAILED | Sbloccato da
  `IMP-OC-01` `STATUS: DONE`. Verifica indipendente del profilo `opencode`.
  Comandi: `docker compose build backend-test && docker compose run --rm
  backend-test` (atteso 296 passati, Ruff pulito), `python3 -m unittest
  discover -s deploy/tests` (atteso 59, invariato), `cd frontend && npm run
  test:ui` (atteso 56) e `npm run build`. Criteri manuali, senza fidarsi del
  rapporto di `SA-IMP`:
  1. Rieseguire la verifica su dati reali: creare una sessione `opencode` con
     nome `sat-oc-<qualcosa>` (prefisso distinto da `sai-oc-` per non
     confondere le tracce dei due esecutori), inviare un prompt che richieda
     un comando di shell e confermare che compaia `Permission required` con
     `Allow once`/`Allow always`/`Reject`. Terminare con doppio `Escape` +
     `kill-session` espliciti.
  2. Verificare nel diff di `IMP-OC-01` (non fidarsi della sola dichiarazione)
     che `OPENCODE_CONFIG_CONTENT` sia effettivamente passata a `new-session`
     via `-e` e che nessun altro profilo la riceva.
  3. Verificare che l'argv del profilo `opencode` sia identico fra avvio e
     ripresa e non contenga `--continue`/`--session`.
  4. Verificare a mano (senza installare/disinstallare `opencode`, che
     resta un'installazione host da preservare) il comportamento a binario
     mancante: chiamare `_missing_binary_shell_command` con un nome di
     binario inventato ed eseguirlo con `bash -c` come fa
     `test_missing_binary_script_reports_and_keeps_pane_alive`, confermando
     che il processo resta vivo e stampa un messaggio invece di terminare.
  5. Confermare che nessuna delle sessioni tmux protette rimaste (`Mac`,
     `RefreshOverview`, `Test video` — o quelle ancora presenti fra le
     quattro originarie) sia stata toccata dalle proprie sessioni di prova,
     e verificare l'elenco finale.
  6. Scansione dati personali sul proprio diff ed eventuali fixture/log
     prodotti.
  7. Confermare che `docs/backlog.md` non lasci `IMP-OC-02` sbloccato prima
     che questo tentativo chiuda `PASSED`, e che l'anomalia delle sessioni
     scomparse sia riportata così com'è (osservazione, non fatto accertato)
     senza essere né amplificata né minimizzata.
  **Esito (`SA-TEST`, 04/08/2026).** Superati tutti i criteri tecnici. Suite:
  backend 296 con Ruff pulito, frontend 56, build pulita; i collector host
  hanno dato `58 passed, 1 error` al primo giro e `59` rieseguiti a host
  scarico — flake da contesa di risorse su un host a due core con cinque TUI
  aperte, non una regressione (`deploy/` non è toccato dal diff). Policy
  verificata sui **due** permessi, non solo su `bash`: comando di shell e
  modifica di file producono ciascuno il proprio dialog, il rifiuto non
  esegue nulla e la sessione resta viva. Binario mancante: eseguito lo script
  reale con un nome inesistente, il pane resta vivo con il messaggio invece di
  sparire. Argv di avvio e ripresa identici e senza `--continue`, confermato
  sia da sorgente sia archiviando e ripristinando una sessione vera. Nessun
  leak della variabile: `cat /proc/<pid>/environ` sui quattro altri profili dà
  zero occorrenze, e `PROFILE_ENV` ha `opencode` come unica chiave. Il test di
  sorveglianza è stato giudicato non vacuo: verifica il valore esatto
  nell'argv reale e l'assenza di `-e` per gli altri profili.
  **Difetto che motiva il `FAILED`:** il diff introduceva **tre volte il nome
  di un progetto privato dell'utente** in `docs/backlog.md`, mentre il resto
  del documento lo chiama genericamente "orchestratore esterno" — convenzione
  che il documento stesso prescrive poco sopra ("nessun nome di componente
  esterno"). La voce dichiarava "nessuna occorrenza": il pattern `grep` di
  riferimento cerca percorsi, indirizzi e token, **non nomi propri**, e chi ha
  eseguito il controllo si è fidato dell'esito del comando invece di leggere
  il proprio diff. Riproduzione:
  `git diff origin/main..HEAD -- docs/backlog.md | grep -n '<nome del progetto>'`.
  Trovato prima della pubblicazione: il commit era ancora locale.

- [x] IMP-OC-01-R1 | OWNER: ROOT | STATUS: DONE | Rimosse le tre occorrenze,
  sostituite con la forma generica già in uso nel documento, senza alterare il
  contenuto fattuale del paragrafo. Ritrattata nella voce `IMP-OC-01` la
  dichiarazione "nessuna occorrenza", che era falsa. Verificato che il nome non
  compaia più in alcun file versionato.
  **Nota di metodo, la parte riutilizzabile.** Il comando di riferimento della
  regola vincolante è un aiuto, non la verifica: intercetta percorsi, IP e
  token perché hanno una forma riconoscibile, ma un **nome proprio** non ne ha
  nessuna. La regola dice "verifica il proprio diff", e il diff va **letto**.
  È la seconda volta in due giorni che questo dato sfugge — la prima era un
  percorso assoluto, arrivata fino a `git filter-repo`. Questa volta il commit
  era ancora locale, e la differenza non è stata la fortuna: è stata la
  verifica indipendente.

- [x] TEST-OC-01-T2 | OWNER: SA-TEST | STATUS: PASSED | Sbloccato da
  `IMP-OC-01-R1`. Rework documentale: verificare che il nome del progetto
  privato non compaia in **nessun** file versionato né nella storia dei commit
  non ancora pubblicati, che la rettifica sia presente in `IMP-OC-01`, e che
  il paragrafo sull'anomalia resti comprensibile dopo la sostituzione. Non
  rieseguire i criteri tecnici già superati: dichiarare quali si assumono
  validi dal tentativo precedente. Verificare inoltre, con un'ispezione del
  diff e non solo con il comando di riferimento, che non siano rimasti altri
  nomi propri riconducibili all'infrastruttura personale dell'utente.
  **Esito (`SA-TEST`, 04/08/2026).** `PASSED`. Il nome non compare in alcun
  file versionato né in alcun punto della storia pubblicata, verificato con
  due metodi indipendenti: il pickaxe di `git log -S` su tutta la storia
  raggiungibile da `origin/main`, e una scansione esaustiva **a livello di
  blob** — enumerati 945 blob distinti, cioè ogni versione di ogni file mai
  committata in questa storia, e ispezionato il contenuto di ciascuno. Il
  secondo metodo copre il caso che il pickaxe potrebbe non centrare. `ROOT` ha
  rieseguito entrambi in modo indipendente ottenendo gli stessi numeri.
  La rettifica in `IMP-OC-01` è una ritrattazione esplicita, non una
  cancellazione silenziosa. Il paragrafo sull'anomalia resta comprensibile:
  la generalizzazione ha tolto il nome ma ha lasciato i dettagli concreti che
  ancorano il ragionamento. Nessun altro nome proprio dell'infrastruttura
  personale nei due commit pubblicati, verificato incrociando l'elenco dei
  venti progetti dei preset di workspace contro entrambi i diff. Suite backend
  296 con Ruff pulito; frontend e collector host assunti validi dal tentativo
  precedente, dopo aver verificato che il rework tocca **solo**
  `docs/backlog.md`.
  **Fase `OC-01` chiusa.** `IMP-OC-02` passa a `READY`.

## INC-DEPLOY-01 — i container non si riavviano se la directory di deploy sparisce

- [x] INC-DEPLOY-01 | OWNER: ROOT | STATUS: DONE | Trovato il 04/08/2026
  durante il ripristino dopo l'incidente di memoria di `OC-CAP-01`.
  I deploy recenti sono stati eseguiti da un **export isolato del commit in una
  directory temporanea**, per evitare di includere nell'immagine il lavoro non
  committato di sessioni parallele. Era la scelta giusta per quel problema, ma
  ha introdotto una dipendenza fragile: i bind mount dei container puntano a
  quella directory, e quando il sistema ha ripulito `/tmp` i container non si
  sono più potuti riavviare — `bind source path does not exist` su
  `.secrets/session_secret` e sul certificato TLS. Nessun problema
  applicativo: soltanto un percorso svanito.
  **Perché conta più di un fastidio:** il modo in cui questo si manifesta è il
  peggiore possibile. Non si vede al deploy, si vede al **riavvio** — cioè
  esattamente quando si sta già cercando di rimettere in piedi il servizio
  dopo un altro guasto. Il 04/08/2026 ha allungato un'indisponibilità già in
  corso.
  **Da fare:** ricreare i container con il contesto nella directory del
  repository, che è stabile, mantenendo però la garanzia che ha motivato
  l'export isolato — l'immagine non deve contenere lavoro non committato.
  Le due esigenze non sono in conflitto: `git stash` non è ammesso su un
  checkout condiviso, ma si può costruire l'immagine da un export isolato e
  poi **ricreare** i container dal repository, oppure verificare che il
  working tree sia pulito prima di costruire dal repository. Decidere quale, e
  scriverlo in `docs/architecture.md` o nella guida di deploy, perché oggi la
  procedura non è documentata da nessuna parte: esiste solo nella memoria di
  chi l'ha eseguita.
  **Esito (`ROOT`, 04/08/2026).** La regola scelta separa le due cose invece
  di sacrificarne una: **il contesto di build può essere temporaneo, il
  contesto di esecuzione no.** Si costruisce da un export isolato quando il
  working tree è sporco (il checkout è condiviso con altre sessioni), oppure
  direttamente dal repository quando è pulito; ma i container si creano e si
  ricreano **sempre dalla directory del repository**. Scritto in `AGENTS.md`,
  nella sezione sul deploy, che è dove un round va a leggere le regole.
  Applicato: `backend` e `web` ricreati dal repository. Mount fragili residui
  su percorsi temporanei: **zero** su entrambi (erano due per i segreti del
  backend e due per i certificati TLS di `web`). Il socket tmux dell'host
  (`/tmp/tmux-1000`) resta in `/tmp` ed è corretto così: è il suo percorso di
  progetto, non un artefatto di deploy.
  Dettaglio operativo utile: Compose **non** ha ricreato `web` con un semplice
  `up -d` pur essendo cambiato il percorso dei mount — l'ha riportato come
  `Running`. È servito `--force-recreate`. Chi rifà questa migrazione deve
  verificare i mount container per container, non fidarsi dell'output.
  **Verifica decisiva:** rimossa la directory temporanea e il collegamento che
  la puntava, quindi riavviati entrambi i container. Sono ripartiti puliti,
  `health` `200` e `login` `200` — cioè esattamente lo scenario che al
  mattino aveva impedito il ripristino, ora innocuo. Chiudere con
  `TEST-DEPLOY-01`.

- [ ] TEST-DEPLOY-01 | OWNER: SA-TEST | STATUS: READY_FOR_TEST | Sbloccato da
  `INC-DEPLOY-01`. Verificare che nessun container in esecuzione abbia mount
  che puntano fuori da percorsi stabili (repository, `~/.config`, runtime
  utente, volumi Docker), con l'unica eccezione legittima del socket tmux
  dell'host; che la regola in `AGENTS.md` sia coerente con quanto realmente
  applicato; e che un riavvio dei soli servizi stateless riporti l'istanza
  sana senza dipendere da alcuna directory temporanea. Verificare inoltre che
  l'immagine in esecuzione corrisponda al codice pubblicato — la migrazione ha
  ricreato i container senza ricostruire le immagini, quindi vale la pena
  confermare che non ci sia deriva fra ciò che gira e ciò che è committato.

#### OC-UX-01 — I dialog di autorizzazione non sono navigabili dall'app

- [ ] OC-UX-01 | OWNER: ROOT | STATUS: READY | Trovato da `SA-TEST` durante
  `TEST-OC-01` (04/08/2026). Il dialog `Permission required` di OpenCode si
  naviga con **Sinistra/Destra** per scegliere fra `Allow once`,
  `Allow always` e `Reject`, ma `ALLOWED_KEYS` in
  `backend/app/services/tmux_service.py` non contiene `Left`/`Right`: l'API
  risponde `400 Unsupported key`. Dall'app si può quindi solo accettare
  l'opzione predefinita con `Enter`, oppure annullare con `Escape`.
  **Non è un difetto di `IMP-OC-01`** — la limitazione dell'allowlist è
  preesistente — ma è quella voce ad averla resa visibile: avendo scelto una
  policy conservativa, i dialog ora compaiono a ogni comando e a ogni
  scrittura. L'utente non può **rifiutare esplicitamente** né concedere
  `Allow always`, che è proprio la scelta che eviterebbe di dover confermare
  ogni volta.
  `Escape` ottiene l'effetto pratico del rifiuto (verificato: nessun comando
  eseguito, nessun file creato, sessione viva), quindi la funzione non è
  bloccata — è scomoda, e lo è esattamente nel flusso che il gate ha
  approvato.
  **Da decidere:** se estendere l'allowlist a `Left`/`Right`. Sono tasti di
  navigazione senza effetti collaterali, come `Up`/`Down` già ammessi, quindi
  il costo per il threat model appare nullo — ma l'allowlist è un invariante
  di sicurezza e si allarga leggendo `docs/security.md`, non per comodità.
  Valutare anche se serva un'affordance dedicata nella UI invece di tasti
  grezzi.

#### OC-CAP-01 — Costo di una sessione OpenCode e capienza dell'host

- [ ] OC-CAP-01 | OWNER: ROOT | STATUS: READY | Emerso il 04/08/2026 durante
  `TEST-OC-01`: la verifica ha aperto cinque TUI insieme e ha saturato l'host
  — due core, load average 13.5, **swap esaurito**, memoria disponibile sotto
  i 500MB. Misure grezze di quel momento: `opencode` ~480MB RSS, `claude`
  ~197MB, `agy` ~141MB, su 3.7GB totali. Nessuna fase precedente aveva
  misurato il costo di una sessione: lo spike `OC-00` ha verificato che
  OpenCode funziona, mai quante sessioni ne reggano insieme. È un vincolo di
  capacità reale per un prodotto pensato attorno a sessioni concorrenti.
  **Da misurare, non da stimare:**
  1. RSS a regime di una sessione OpenCode inattiva, e come cresce con la
     lunghezza della conversazione — il numero sopra è un'istantanea sotto
     carico, non una linea di base.
  2. **Se una sessione aperta dall'utente via SSH pesi quanto una aperta da
     Mobile Agent Console.** Ipotesi da falsificare: in modalità host le due
     girano sullo stesso server tmux e dovrebbero costare uguale in memoria;
     la differenza attesa è semmai in **CPU**, perché per le sessioni viste
     dalla PWA gira anche il loop di `capture-pane` dello stream WebSocket.
     Se invece la memoria differisse, l'ipotesi è sbagliata e va capito
     perché — sarebbe un costo introdotto dal prodotto, non dall'agente.
  3. Quante sessioni OpenCode concorrenti regge questo host prima che lo swap
     inizi a sostituire la RAM, e cosa succede al superamento: degrado
     graduale o OOM killer che sceglie una sessione a caso. La seconda
     ipotesi è la pericolosa, perché il killer potrebbe scegliere una
     sessione di lavoro dell'utente.
  Esito atteso: un numero di sessioni concorrenti sostenibile, e la decisione
  se il prodotto debba conoscerlo (avviso, limite, o nulla). `OC-02` e `OC-03`
  non vanno chiuse senza questa risposta: entrambe assumono implicitamente che
  aprire sessioni sia economico.
  **Misure (`ROOT`, 04/08/2026).**
  1. **Una sessione OpenCode inattiva costa ~480 MB e si assesta lentamente.**
     Partenza a 578 MB, poi 552 → 500 → 496 → 485 → 483 MB, plateau a ~484 MB
     dopo circa tre minuti. `Pss` 479 MB, quindi quasi nulla è condiviso: il
     costo è reale, non un artefatto di `Rss`. **Misurare subito dopo l'avvio
     sovrastima di circa il 20%** — chiunque rifaccia questa misura deve
     aspettare il plateau.
  2. **Domanda chiusa: una sessione aperta via SSH e una aperta da Mobile
     Agent Console costano uguale.** `Pss` 440 MB contro 452 MB, differenza
     dentro il rumore delle due misure. L'ipotesi era corretta: in modalità
     host girano sullo stesso server tmux e il prodotto non aggiunge peso al
     processo dell'agente. Il costo del prodotto, se esiste, è in **CPU** e
     solo mentre un client sta guardando: il loop di `capture-pane` vive per
     connessione WebSocket, quindi una sessione senza spettatori non costa
     nulla al backend. Quest'ultima parte è dedotta dall'architettura e
     **non** misurata: resta da verificare con un client collegato.
  3. **Quante ne regge l'host: due sono già troppe.** Non è una stima, è un
     incidente. Tenendo vive contemporaneamente le due sessioni di questa
     misura, con ~450 MB ciascuna su 3.7 GB e swap già saturo, il kernel ha
     terminato i container `backend` e `web` (uscita 255) e l'app è diventata
     irraggiungibile per l'utente. Le sessioni tmux dell'utente sono
     sopravvissute perché vivono sul server tmux dell'host, mai toccato.
     **La risposta alla domanda 3 è quindi: su questo host, due sessioni
     OpenCode concorrenti non convivono con l'applicazione.**
  **Decisione ancora aperta:** se il prodotto debba conoscere questo limite.
  Le opzioni non sono equivalenti — un avviso informa ma non protegge, un
  limite protegge ma va scelto su una soglia che dipende dall'host. Un dato
  in più per deciderlo: il fallimento non è graduale, è un OOM che colpisce
  **l'applicazione**, non la sessione che ha causato la pressione.

#### OC-02 — Archivio e snapshot

- [ ] IMP-OC-02 | OWNER: SA-IMP | STATUS: READY | Sbloccato da `OC-01`
  (`TEST-OC-01-T2` `PASSED`). **Non chiudibile senza `OC-CAP-01`**: questa
  fase assume che aprire sessioni sia economico, e quel costo non e' ancora
  stato misurato.
  Estendere archivio, snapshot e restore preservando la semantica già offerta
  agli altri profili. Usare inizialmente il **selettore nativo delle sessioni**
  (strategia B dell'analisi): è la scelta prudente per il primo rilascio e non
  richiede di persistere un identificatore OpenCode. Testare esplicitamente il
  caso con più conversazioni nello stesso progetto. La persistenza dell'ID
  OpenCode (strategia C) richiede una decisione separata, con ADR se necessario:
  l'ID resterebbe un dato distinto dal target tmux e non dovrebbe mai diventare
  input shell. Conversazioni e credenziali restano fuori dai backup MAC.
  **Gate:** restore non ambiguo, o esplicitamente mediato dall'utente, senza
  comandi arbitrari persistiti.

#### OC-03 — Stato agente e notifiche

- [ ] IMP-OC-03 | OWNER: SA-IMP | STATUS: BLOCKED | Sbloccato da `OC-02`.
  Introdurre `opencode` come tipo agente **senza attribuirgli un provider
  modello fittizio** (vedi decisione 6 del gate). Classificatore dedicato
  costruito su fixture reali, non su pattern presi in prestito da Codex o
  Claude; coprire attività, inattività, feedback e autorizzazione. Web Push
  solo dopo la validazione dei falsi positivi/negativi: un falso negativo
  nasconde una richiesta importante, un falso positivo erode la fiducia in
  tutte le notifiche. Valutare la vista Blocchi come trasformazione
  client-side opzionale.
  **Gate:** classificazione conservativa, fallback `unknown`, nessuna
  persistenza dell'output.

#### OC-04 — Adapter strutturato (opzionale, gate a sé)

- [ ] GATE-OC-04 | OWNER: ROOT | STATUS: BLOCKED | Non autorizzato da
  `GATE-OC-00`. Richiede un ADR sul secondo runtime di sessione e sulla
  correlazione dei due identificatori prima di qualunque implementazione. Da
  aprire solo se l'uso di API ed eventi OpenCode migliora **materialmente**
  affidabilità o UX rispetto al terminale tmux: il server OpenCode dovrebbe
  ascoltare esclusivamente su loopback o socket locale, mai su `0.0.0.0`, con
  FastAPI come adapter minimizzato e nessun accesso diretto del browser. tmux
  resta autorevole per il terminale live e il fallback deve essere completo.

#### OC-05 — Supporto Docker (opzionale, finestra di manutenzione)

- [ ] GATE-OC-05 | OWNER: ROOT | STATUS: BLOCKED | Non autorizzato da
  `GATE-OC-00`. Il rollout obbliga a ricreare `tmux-runtime`, terminando tutte
  le sessioni vive: richiede una finestra di manutenzione esplicita,
  comunicazione preventiva della perdita dei processi attivi e un gate
  separato. Binario con versione e checksum pinnati, mai un installer remoto
  non verificato durante l'avvio del container; storage, secret e rete del
  runtime vanno progettati prima, preservando filesystem read-only e container
  non-root.

## Parcheggiati il 2026-08-05 (budget 7d al 91%, ripresa dal 2026-08-09)

Due temi aperti dall'utente, entrambi **da discutere prima di implementare**:
nessuna decisione di design è stata presa.

### BL-HOST-01 — Comandi sysadmin nella vista Host

Serve una lista di comandi rapidi con pulsante copia accanto, limitata a
start/stop di container e servizi (il caso concreto: il dev server del sito
personale). Collocazione proposta dall'utente: una card dedicata nella vista
Host, chiusa di default, e in più il comando accanto a ogni riga della tabella
"Chi consuma".

**Vincolo esplicito e non negoziabile:** nessun path e nessun nome reale può
finire nel repository. L'intera mappatura vive in una configurazione privata
fuori dal repo, come già fanno `container_policies` e `services.policies`.

Domande aperte prima di scrivere codice:

- se i comandi restano **testo da copiare** (nessuna esecuzione, nessun nuovo
  verbo nell'API) o se qualcuno li esegue: la prima opzione non tocca il
  threat model, la seconda apre una superficie di esecuzione remota che
  `docs/security.md` oggi esclude per costruzione;
- se il comando è **dichiarato** per servizio nella config privata oppure
  **derivato** dalla policy esistente (label → `docker start <nome>`), che
  richiederebbe di far attraversare il boundary il nome reale del container,
  oggi vietato;
- quale componente lo espone: il collector (che ha già la config privata) o il
  backend (che oggi non legge configurazione host).

### BL-HOST-02 — Attribuzione dei listener nel collector

Oggi la fotografia mostra dodici porte con "proprietario ignoto" e il reason
`listeners_partial`: il collector vede il socket ma non risale al processo,
perché legge `/proc` senza privilegi e i socket di altri utenti non sono
risolvibili. Il modulo lo dichiara invece di indovinare — comportamento
corretto — ma la domanda "chi ascolta sulla porta N?" oggi non ha risposta
dalla dashboard.

Da discutere: se e come colmarlo senza allentare l'hardening del collector
(ADR 009), tenendo presente che la soluzione adottata due volte per lo stesso
tipo di problema è un helper fuori banda (ADR 011, ADR 012), non un aumento di
privilegi. Va valutato anche il costo in privacy: l'attribuzione porta con sé
nomi di processi di terzi.

## INC-HOST-01 — creazione sessione impossibile quando il server tmux host è giù

**Stato:** cause 1, 2 e 3 corrette e verificate su host reale il 05/08/2026.
Resta aperta la sola remediation aggiuntiva (protezione della sessione di
servizio dentro MAC), in fondo alla scheda.

**Sintomo:** `create_session` fallisce ("unable to create session") ogni volta
che il server tmux host non ha nessuna sessione attiva. È by design (ADR 005,
guardia anti auto-start in `TmuxService._require_server`) che il backend non
avvii mai da sé il server in modalità host — ma la conseguenza è che **la
disponibilità di MAC dipende dall'esistenza di almeno una sessione tmux sul
socket di default dell'utente host**, oggi garantita solo dalla unit
`mobile-agent-console-tmux-host.service` (sessione keepalive).

Due cause distinte individuate, entrambe da correggere:

1. **Nessuna auto-guarigione se la keepalive sparisce a host acceso.** La unit
   è `Type=oneshot`, eseguita una sola volta all'avvio (`After=default.target`)
   e resa idempotente da un `ExecStart=-...` che tollera "duplicate session".
   Se la sessione `keepalive` viene chiusa mentre l'host resta acceso (es.
   archiviata per errore dall'utente da dentro MAC, che può terminare
   qualunque sessione visibile compresa questa), nessun meccanismo la
   ricrea finché non c'è un nuovo riavvio. Precedente diretto nel repo per lo
   stesso tipo di problema: le unit a timer che ririeseguono periodicamente
   un'azione idempotente (`mobile-agent-console-docker-state.{service,timer}`,
   ADR 011) — stesso pattern applicabile qui.
2. **Ciclo di ordinamento systemd, riprodotto con un riavvio host reale il
   05/08/2026.** La unit keepalive dichiara `After=default.target` pur essendo
   anche `WantedBy=default.target` (che le aggiunge implicitamente
   `Before=default.target`): un'altra unit che fa partire i container con
   `After=mobile-agent-console-tmux-host.service` chiude il ciclo. Al boot
   `systemd` lo rompe **cancellando il job di avvio della unit keepalive**, che
   quindi resta inattiva finché non la si avvia a mano — esattamente il
   sintomo osservato dopo il riavvio. Fix minimo: rimuovere il
   `After=default.target` ridondante dalla unit keepalive (il `WantedBy`
   basta già a ordinarla correttamente rispetto al target).

3. **Gli overlay compose opzionali si perdono a ogni riavvio dell'host.** Le
   unit `mobile-agent-console-{host,docker}.service` passavano solo i file
   compose base con `-f` espliciti. `docker compose` **non** legge
   `COMPOSE_FILE` dal file indicato con `--env-file` (verificato con un caso
   minimo: l'overlay non viene unito), quindi il `COMPOSE_FILE` del `.env` non
   aveva alcun effetto e il riavvio ricreava i container senza gli overlay.
   Effetto osservato: la sezione Host sparita dalla UI, perché il backend
   ripartiva senza `MAC_HOST_OBSERVABILITY_ENABLED` e `GET /api/v1/config`
   riportava la feature spenta. Corretto con `$MAC_COMPOSE_OVERLAYS` (forma
   non graffata, l'unica su cui systemd fa word splitting) nelle quattro
   direttive Exec\* di entrambe le unit, valorizzata nel file `environment`
   privato.

**Correzioni applicate il 05/08/2026** (`deploy/systemd/`, regressioni coperte
da `deploy/tests/test_host_observability_systemd.py`):

- rimosso `After=default.target` dalla keepalive;
- aggiunta `mobile-agent-console-tmux-host.timer`
  (`OnBootSec=1min`, `OnUnitActiveSec=2min`) e tolto `RemainAfterExit` dal
  servizio, altrimenti un'unit `active (exited)` ignorerebbe il trigger;
- aggiunto `$MAC_COMPOSE_OVERLAYS` alle unit compose e a `environment.example`.

**Trappola trovata applicando il fix, costata la perdita di tutte le sessioni
vive.** `tmux new-session` lascia il **server** tmux come figlio nel cgroup
della unit. Finché la keepalive aveva `RemainAfterExit=yes` la unit restava
attiva per sempre e nessuno fermava quel cgroup; togliendolo per far
funzionare il timer, ogni scatto esegue `Stopping` e con il `KillMode` di
default systemd uccide il cgroup — **cioè il server tmux e tutte le sessioni
dell'utente, non solo la keepalive**. Rimedio: `KillMode=process`. Da questo
segue anche che il commento "fermare l'unità non deve terminare le sessioni
operative" era falso prima di oggi: `systemctl stop` le avrebbe terminate.
Verificato dopo il fix creando una seconda sessione e riavviando la unit
(sopravvissuta), e uccidendo la keepalive (ricreata dal timer in ~100s).

**Idea di remediation aggiuntiva proposta dall'utente:** impedire che la
sessione keepalive possa essere terminata/archiviata dall'interfaccia di MAC
stessa — o escludendola dall'elenco (c'è già un precedente di filtro per nome
riservato lato `TmuxService.list_sessions`, oggi applicato solo in modalità
Docker) o bloccando esplicitamente l'azione di terminazione su quel
nome/id riservato. Da decidere se questo confligga con l'obiettivo dichiarato
in ADR 005 di mostrare in MAC *tutte* le sessioni host senza eccezioni.

**Non contiene** nomi host, IP o path reali per costruzione — vedi
`docs/adr/005-host-default-socket.md` per i placeholder di riferimento.
