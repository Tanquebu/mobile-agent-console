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

**Stato: piano operativo pronto, validazione prodotto pendente, non avviato.**
Discusso il 30/07/2026, nato da un
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
- `SA-IMP` può prendere soltanto la prima voce con `OWNER: SA-IMP` e
  `STATUS: READY` o `STATUS: REWORK_REQUIRED`, portandola prima a
  `IN_PROGRESS`.
- Ogni voce di implementazione include anche test automatici proporzionati al
  rischio e aggiorna il gate manuale in `docs/gates/host-observability.md`.
  Non è pronta per la consegna con test mancanti o non passanti.
- Quando `SA-IMP` conclude, chiude la propria voce con `STATUS: DONE` e porta
  il corrispondente check `SA-TEST` da `BLOCKED` a `READY_FOR_TEST`, indicando
  commit/working tree, test aggiunti, comandi da eseguire e criteri manuali.
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
