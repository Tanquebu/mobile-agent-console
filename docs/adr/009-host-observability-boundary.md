# ADR 009 — Boundary host per l'osservabilità

## Stato

Accettata. Il contratto v1 è stato aggiunto in HO-02 e l'endpoint HTTP
admin-only opt-in in HO-03; la UI resta fuori da questa decisione e viene
affrontata nella fase successiva.

## Contesto

Il backend containerizzato non deve ricevere accesso diretto a `/proc`, `/sys`
o al socket Docker dell'host. Un collector periodico introdurrebbe raccolta e
stato anche quando nessun amministratore richiede una fotografia. Un demone
HTTP aggiungerebbe invece una porta di rete e un servizio persistente.

Le due modalità di deployment eseguono il backend con identità differenti: in
modalità Docker usa `10001:10001`, mentre in modalità host-tmux usa UID e GID
dell'utente host. I permessi del socket non possono quindi dipendere dal solo
owner.

## Decisione

L'osservabilità usa un collector one-shot attivato da una user socket unit
systemd:

1. la socket unit crea un solo socket Unix `AF_UNIX`, senza listener TCP;
2. `Accept=yes` avvia una nuova istanza del collector per ogni connessione e
   collega il socket accettato a stdin/stdout;
3. il collector termina dopo aver scritto un singolo oggetto JSON;
4. il backend monta in sola lettura la **directory** del socket tramite un
   overlay Compose opt-in e applica timeout e limite di byte lato client;
5. una unit preparatoria crea la directory `0750` e applica ACL POSIX nominali
   all'UID host effettivo del backend; le ACL predefinite vengono ereditate dal
   socket `0660` a ogni nuova attivazione;
6. l'ACL include sempre l'UID `10001` usato dal Docker rootful e, quando
   configurato, l'UID host a cui rootless Docker o `userns-remap` mappano il
   processo backend; il gruppo proprietario resta senza accesso.

La preparazione è una oneshot richiesta e ordinata prima della socket. Usa
`DefaultDependencies=no` perché le socket user sono ordinate prima di
`sockets.target`: acquisire il normale `After=basic.target` creerebbe il ciclo
`socket → prepare → basic → sockets.target → socket`.

HO-02 sostituisce l'handshake dello spike con una fotografia v1 minimizzata.
Il collector resta one-shot e non espone un endpoint API: memoria, processi,
listener, filesystem e Docker opzionale attraversano soltanto il socket Unix.

## Conseguenze e limiti

- Socket activation fornisce raccolta realmente on-demand e concorrenza senza
  un demone residente.
- L'assenza dell'overlay mantiene invariato il deployment attuale.
- `setfacl` è un prerequisito host. La unit preparatoria è idempotente e ricrea
  directory e ACL prima che systemd apra il socket.
- Docker rootless e `userns-remap` richiedono l'UID host mappato, ricavato con
  un probe isolato e configurato solo nell'environment host privato. Un UID
  errato non degrada i permessi: il connect fallisce chiuso.
- La sola preparazione ACL non usa `ProtectSystem`, `ProtectHome` o `PrivateTmp`:
  in una user unit i relativi namespace non rappresentano gli UID subordinati
  e `setfacl` fallisce con `EINVAL`. Resta il rischio residuo della visibilità
  filesystem/home dell'utente durante la breve oneshot. Lo contengono
  argv/path fissi e fidati, `NoNewPrivileges`, sola `AF_UNIX`, namespace e SUID
  vietati, umask `0077` e il gate runtime fail-closed. Socket e collector
  mantengono filesystem protetto e `PrivateTmp`.
- Collector e prepare sono user unit con capability effettive, permesse e
  ambienti nulle verificate a runtime. Non impostano direttive `Capability*`
  incompatibili con alcuni manager user né `IPAddressDeny`, che lì sarebbe
  ineffettiva; `RestrictAddressFamilies=AF_UNIX` è il blocco applicabile della
  rete IP. Le protezioni device/clock/log/moduli e hostname non sono dichiarate
  perché sul manager user richiedono operazioni di capability/namespace che
  falliscono o vengono ignorate; il collector conserva filesystem/home
  protetti e le restrizioni kernel applicabili. Socket e directory restano
  `0660`/`0750`, con concorrenza e trigger limitati.
- Il backend valida nuovamente il JSON con lo schema HO-02; API admin-only e
  rate limit sono in HO-03, mentre la UI HO-04 resta on-demand e senza polling.

## Alternative scartate

- mount di `/proc` o `/sys`: amplia eccessivamente la vista del backend;
- mount del socket Docker: equivale a un'autorità di controllo molto maggiore
  della sola osservazione;
- collector a timer: raccoglie senza richiesta e apre implicitamente alla
  persistenza temporale;
- demone TCP/HTTP: aggiunge una nuova superficie di rete;
- socket world-writable: evita il problema UID/GID sacrificando l'isolamento;
- solo gruppo supplementare: non attraversa in modo affidabile un bind mount
  rootless perché il daemon traduce le credenziali del processo container.

## Rollback

Rimuovere `compose.host-observability.yaml` dalla composizione, ricreare solo
`backend` e `web`, poi disabilitare la socket unit. `tmux-runtime` non deve
essere ricreato. Lo spike non lascia dati persistenti da eliminare.
