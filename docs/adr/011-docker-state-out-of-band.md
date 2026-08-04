# ADR 011 — Stato Docker raccolto fuori dal collector one-shot

## Stato

Accettata.

## Contesto

Il collector di osservabilità host (ADR 009) eseguiva `docker ps` come
subprocess e riceveva sempre un errore, esposto come `docker_unavailable`. Il
componente Docker della fotografia è quindi rimasto vuoto da quando esiste, e
con esso ogni possibilità di rispondere a "quale container sta consumando
memoria".

La causa non è nel codice né nei permessi del socket. Il collector gira con
`PrivateTmp`, `ProtectHome` e `ProtectSystem`: ognuna di queste direttive
costruisce per il servizio un mount namespace. Su Ubuntu 24.04 la protezione
`apparmor_restrict_unprivileged_userns` confina i processi che creano namespace
senza privilegi nel profilo AppArmor `unprivileged_userns` in enforce, che nega
la `connect()` verso il socket Docker rootless.

Verificato sull'host di riferimento: dentro la sandbox il socket è lo stesso
inode, su un mount rw, e il test di scrivibilità passa; la `connect()` fallisce
comunque con `EACCES`, e il processo risulta etichettato `unprivileged_userns`.
Basta una qualsiasi delle tre direttive perché accada, e `ReadWritePaths` sul
socket non lo risolve.

```
systemd-run --user --pipe --wait -q -p PrivateTmp=yes /usr/bin/docker ps -q
→ permission denied ... unix:///run/user/1000/docker.sock
```

La memoria per container aggiunge un secondo vincolo, indipendente dal primo:
`docker stats --no-stream` impiega circa 2 secondi sull'host di riferimento,
contro i circa 200 ms dell'intera fotografia. Non sarebbe eseguibile dentro una
raccolta on-demand nemmeno se il socket fosse raggiungibile.

## Decisione

La raccolta che richiede il socket Docker esce dal collector one-shot e vive in
una unit separata, `mobile-agent-console-docker-state`, oneshot su timer da 30s,
che scrive `docker-state.json` con permessi `0600`. Il collector legge quel file
— leggere è permesso anche dentro il namespace — tramite `docker.state_file` e
`docker.max_age_seconds` nella configurazione v2. Senza `state_file` resta il
comportamento storico a subprocess.

L'hardening della unit Docker omette deliberatamente ogni direttiva che crea un
mount namespace; il collector di osservabilità conserva il proprio invariato. Il
compromesso è confinato a un processo che esegue solo `docker ps` e
`docker stats`, non legge `/proc` di terzi e scrive un solo file. Un test di
regressione fallisce se una di quelle direttive viene aggiunta alla unit Docker,
e un altro verifica che il collector non le abbia perse.

La mappatura nome → label e la classificazione degli stati restano nel collector:
il file contiene i nomi reali dei container, non li espone a nessuno e non
attraversa mai il boundary. Un file assente, scaduto oltre `max_age_seconds`,
malformato o scritto da un helper che non ha raggiunto Docker produce evidenza
esplicita (`docker_unavailable`, `docker_state_stale`, `docker_output_invalid`)
e mai un esito positivo sintetico. L'età della raccolta viaggia nello snapshot
come `docker.state_age_seconds` e la vista la dichiara, perché è l'unico
componente della fotografia che non è istantaneo.

In v2 solo i container con una label configurata concorrono alla severità, come
già avviene per i gruppi di processi senza policy: senza questa regola i
container fermi di progetti non sorvegliati renderebbero l'host critico in
permanenza. Restano contati in `unmapped_problematic_count`, quindi visibili.

## Conseguenze

L'ADR 009 scartava un "collector a timer" perché raccoglie senza richiesta e
apre implicitamente alla persistenza temporale. Questa decisione introduce
un'eccezione delimitata a quel principio, non una revoca: il timer raccoglie
solo nomi, stato e memoria dei container in un unico file sovrascritto, senza
storico, e la fotografia host resta interamente on-demand. Il collector di
osservabilità continua a non raccogliere nulla senza una richiesta.

Il prezzo è che l'evidenza Docker è vecchia fino a 30 secondi, e che un timer
fermo è un modo nuovo di perdere il dato — reso visibile da `docker_state_stale`
invece che silenzioso.

## Alternative scartate

- allentare l'hardening del collector di osservabilità: è il componente che
  legge `/proc` di tutti i processi e le porte in ascolto, cioè quello su cui
  quelle protezioni valgono di più;
- eccezione AppArmor per il collector: stesso effetto della precedente, con in
  più una configurazione fuori dal repo che nessun test può sorvegliare;
- helper socket-activated interrogato dal collector: impossibile, perché è
  proprio la `connect()` a essere negata;
- helper socket-activated interrogato dal backend: sposterebbe nel backend la
  composizione delle evidenze e il calcolo dello stato complessivo, che oggi
  appartengono al collector;
- lettura diretta dei cgroup (`memory.current`): dà byte esatti e istantanei, ma
  richiede di indovinare il layout dei path, diverso fra rootless e rootful e fra
  driver cgroup, e comunque non fornisce i nomi dei container.
