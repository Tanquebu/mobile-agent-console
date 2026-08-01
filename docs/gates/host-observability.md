# Gate manuale — Host observability

Questo gate valida boundary HO-01, collector/contratto HO-02, endpoint backend
HO-03 e UI Host HO-04. Va eseguito su un host Linux con systemd user, ACL POSIX
e Docker Compose.

## Prerequisiti una tantum

Installare `setfacl` (pacchetto `acl` nelle distribuzioni Debian/Ubuntu). Le ACL
nominali autorizzano soltanto l'UID host effettivo del backend; il gruppo
proprietario e `other` restano senza accesso.

Installare lo script e le tre unit user:

```bash
install -m 0644 deploy/systemd/mobile-agent-console-host-observability.socket ~/.config/systemd/user/
install -m 0644 deploy/systemd/mobile-agent-console-host-observability@.service ~/.config/systemd/user/
install -m 0644 deploy/systemd/mobile-agent-console-host-observability-prepare.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemd-analyze --user verify deploy/systemd/mobile-agent-console-host-observability-prepare.service deploy/systemd/mobile-agent-console-host-observability.socket deploy/systemd/mobile-agent-console-host-observability@.service
```

`systemd-analyze` deve terminare con exit `0` e senza `ordering cycle`. Il flag
`--user` è obbligatorio: la preparazione usa `DefaultDependencies=no` per non
acquisire l'`After=basic.target` che richiuderebbe il ciclo con `sockets.target`.

Creare la configurazione host privata partendo esclusivamente dall'esempio
fittizio, sostituire path, soglie, porte e mapping e mantenerla `0600`:

```bash
install -m 0600 deploy/host-observability.example.json ~/.config/mobile-agent-console/host-observability.json
```

Nel file `~/.config/mobile-agent-console/environment` configurare:

```text
MAC_HOST_OBSERVABILITY_CONFIG_FILE=/home/example/.config/mobile-agent-console/host-observability.json
```

Nel `.env` Compose privato configurare invece:

```text
MAC_HOST_OBSERVABILITY_SOCKET_DIR=/run/user/UID/mobile-agent-console
```

L'overlay imposta esplicitamente `MAC_HOST_OBSERVABILITY_ENABLED=true`; senza
overlay il default backend è `false`. I default del rate limit dedicato sono 6
richieste ogni 60 secondi e il limite risposta non può superare 131072 byte.

Il numero è un esempio: usare `id -u`. Il path sorgente deve essere la
directory, non il file socket.

Se `docker info --format '{{json .SecurityOptions}}'` riporta `rootless` o il
daemon usa `userns-remap`, rilevare l'UID host mappato all'UID backend `10001`
con un probe isolato:

```bash
probe_dir=$(mktemp -d)
chmod 1777 "$probe_dir"
docker run --rm --user 10001:10001 -v "$probe_dir:/probe" alpine:3.22 touch /probe/backend-uid
stat -c '%u' "$probe_dir/backend-uid"
rm -r "$probe_dir"
```

Registrare il numero ottenuto soltanto nel file environment privato:

```text
MAC_HOST_OBSERVABILITY_ROOTLESS_UID=UID_HOST_RILEVATO
```

Attivare la socket dopo aver completato la configurazione. Riavviare
preparazione e socket dopo ogni modifica del mapping:

```bash
systemctl --user enable --now mobile-agent-console-host-observability.socket
systemctl --user restart mobile-agent-console-host-observability-prepare.service
systemctl --user restart mobile-agent-console-host-observability.socket
```

## Check comuni

1. Confermare tipo, mode e ACL:

   ```bash
   stat -c '%F %U %G %a' "$XDG_RUNTIME_DIR/mobile-agent-console" "$XDG_RUNTIME_DIR/mobile-agent-console/host-observability.sock"
   getfacl -p "$XDG_RUNTIME_DIR/mobile-agent-console" "$XDG_RUNTIME_DIR/mobile-agent-console/host-observability.sock"
   ```

   Atteso: directory `750`, socket `660`, `group::---`, entry nominativa per
   `10001` e, in rootless/userns-remap, per l'UID host rilevato. Le ACL default
   della directory devono essere ereditate dal socket.

2. Prima e dopo una connessione, verificare che non compaiano listener TCP:

   ```bash
   ss -ltnp
   systemctl --user status mobile-agent-console-host-observability.socket
   systemctl --user is-active mobile-agent-console-host-observability-prepare.service mobile-agent-console-host-observability.socket
   ```

   Entrambe le unit devono essere `active`; se la preparazione fallisce, la
   socket deve restare inattiva (fail-closed). Il journal delle nuove
   invocazioni non deve contenere `218/CAPABILITIES`, direttive ignorate o
   errori di namespace.

   Verificare inoltre sullo stesso manager user che un processo con le
   restrizioni comuni abbia capability permesse, effettive e ambienti nulle e
   non possa creare socket IP:

   ```bash
   systemd-run --user --wait --collect \
     -p NoNewPrivileges=yes -p RestrictAddressFamilies=AF_UNIX \
     /usr/bin/python3 -c 'import socket; rows=dict(line.rstrip().split(":\t",1) for line in open("/proc/self/status") if line.startswith(("CapInh:","CapPrm:","CapEff:","CapAmb:"))); assert all(int(rows[k],16)==0 for k in ("CapPrm","CapEff","CapAmb")); socket.socket(socket.AF_UNIX).close(); blocked=False; exec("try:\n socket.socket(socket.AF_INET)\nexcept OSError:\n blocked=True"); assert blocked'
   ```

3. Connettersi direttamente e verificare la fotografia v1 completa:

   ```bash
   python3 -c 'import json,os,socket; s=socket.socket(socket.AF_UNIX); s.connect("/run/user/%d/mobile-agent-console/host-observability.sock" % os.getuid()); p=json.loads(b"".join(iter(lambda:s.recv(65536),b""))); print(p["schema_version"],p["status"],len(p["processes"]["top"]),len(p["listeners"]["items"]))'
   ```

   Atteso: schema `1`, stato tipizzato e liste entro i limiti. Validare l'intero
   payload con `HostObservabilitySnapshot`, non solo i campi stampati. Ripetere
   con almeno quattro client contemporanei e verificare quattro fotografie
   valide e quattro istanze one-shot terminate.

4. Verificare che il backend non monti viste host proibite:

   ```bash
   docker compose -f compose.yaml -f compose.host-observability.yaml config
   docker inspect mobile-agent-console-backend-1 --format '{{json .Mounts}}'
   ```

   Devono comparire la directory `/host-observability` in read-only e i mount
   applicativi già noti; non devono comparire `/proc`, `/sys` o il socket Docker.

## Modalità Docker tmux

Avviare/ripubblicare solo il backend con l'overlay, preservando `tmux-runtime`:

```bash
docker compose -f compose.yaml -f compose.host-observability.yaml up -d --no-deps backend
docker compose -f compose.yaml -f compose.host-observability.yaml exec backend id
docker compose -f compose.yaml -f compose.host-observability.yaml exec backend python -c 'import asyncio; from app.services.host_observability_contract import HostObservabilitySnapshot; from app.services.host_observability_socket_client import HostObservabilitySocketClient; p=asyncio.run(HostObservabilitySocketClient("/host-observability/host-observability.sock").fetch()); s=HostObservabilitySnapshot.model_validate(p); print(s.schema_version,s.status,len(s.processes.top))'
```

Atteso: UID/GID container `10001:10001` e handshake riuscito. In Docker rootful
l'accesso usa l'ACL host `10001`; in rootless/userns-remap usa l'ACL dell'UID
host rilevato dal probe.

## Modalità host-tmux

Usare anche l'override host senza avviare o ricreare `tmux-runtime`:

```bash
docker compose -f compose.yaml -f compose.host.yaml -f compose.host-observability.yaml up -d --no-deps backend
docker compose -f compose.yaml -f compose.host.yaml -f compose.host-observability.yaml exec backend id
docker compose -f compose.yaml -f compose.host.yaml -f compose.host-observability.yaml exec backend python -c 'import asyncio; from app.services.host_observability_contract import HostObservabilitySnapshot; from app.services.host_observability_socket_client import HostObservabilitySocketClient; p=asyncio.run(HostObservabilitySocketClient("/host-observability/host-observability.sock").fetch()); s=HostObservabilitySnapshot.model_validate(p); print(s.schema_version,s.status,len(s.processes.top))'
```

Atteso: identità configurata dalla modalità host, handshake riuscito e sessioni
tmux preesistenti ancora vive. Con rootless Docker l'UID container `0` mappa
normalmente all'owner host; confermarlo con un connect reale, non presumerlo.

## Negative check e limiti

- In rootless, rimuovere temporaneamente l'ACL nominativa dell'UID mappato dalla
  directory e dal socket: il connect deve fallire per permessi. Riavviare poi
  la unit preparatoria e la socket per ripristinare le ACL dichiarate.
- Fermare la socket unit: il client deve produrre l'errore tipizzato
  `host collector unavailable` entro il timeout configurato.
- Una risposta oltre 128 KiB, bloccata o non JSON deve essere rifiutata dai test
  automatici e non deve propagare il contenuto grezzo.
- Un UID mappato errato deve produrre `PermissionError`; segnare il gate
  `FAILED`, correggere il mapping privato e non allargare mode/ACL.
- Config assente, oltre 64 KiB, con mode diverso dall'esatto `0600`, non
  posseduta dal collector, raggiunta tramite un symlink leaf/parent, modificata
  durante la lettura o con campi extra deve impedire la risposta. Nessun valore
  della configurazione privata deve apparire negli errori.
- Verificare separatamente Docker assente, non autorizzato, in timeout e con
  record malformato/output oltre 64 KiB: solo `docker.status=unknown`; il limite
  deve interrompere il subprocess durante lo streaming, non dopo la
  bufferizzazione. Un producer che chiude stdout ma rimane vivo deve essere
  terminato e reaped entro la stessa deadline. Memoria, processi e disco
  restano disponibili.
- Rendere alternativamente illeggibile `tcp` o `tcp6`: il listener component
  deve riportare `listeners_partial` e non `ok`. Verificare lo scope
  `tailscale` per un indirizzo nel prefisso IPv6 `fd7a:115c:a1e0::/48`.
- Ripetere con file TCP vuoto, header/record invalido e 1.001 record: la
  copertura deve risultare partial, la scansione troncata dove applicabile e lo
  stato non può essere `ok`.
- Passare a `collected_at` un intero e altri tipi non datetime/stringa: il
  contratto deve restituire `ValidationError`, mai un'eccezione grezza dal
  validator.
- Simulare contatori `statvfs` incoerenti e soglie warning/critical: lo stato e
  le ragioni devono propagarsi dall'item filesystem al componente e
  all'envelope.
- Confrontare il payload con `docs/contracts/host-observability-v1.md`: vietati
  cmdline, path, username, hostname, IP, inode, container name/ID/image e
  `stderr`; un componente indisponibile deve essere `unknown`, mai `ok`.

## Gate API HO-03

Con overlay attivo, autenticarsi come admin e invocare:

```bash
curl --fail-with-body --cookie cookies.txt https://HOST/api/v1/host-observability
```

Validare la risposta completa con `HostObservabilitySnapshot`. Verificare
inoltre in modo indipendente:

- flag disattivato: `404` e nessuna connessione al socket;
- richiesta anonima `401`, viewer/operator `403`, admin `200` anche con
  componenti parziali `unknown` validi;
- superamento del limite dedicato: `429`, codice
  `host_observability_rate_limited` e `Retry-After`;
- socket assente: `503/host_observability_unavailable`; payload non JSON,
  oltre 128 KiB o non conforme allo schema:
  `503/host_observability_invalid_response`; timeout:
  `504/host_observability_timeout`;
- `/api/v1/config` riporta il flag vero soltanto all'admin; `/health` non
  contiene stato o metriche host;
- prima e dopo il GET, audit e database non acquisiscono nuovi record relativi
  alla fotografia; log e risposte di errore non contengono payload, path
  privati o dettagli grezzi del collector.

## Comandi automatici

```bash
docker compose run --rm backend-test pytest tests/test_host_observability_api.py tests/test_host_observability_socket_client.py tests/test_host_observability_contract.py
python3 -m unittest deploy/tests/test_host_observability_runtime.py deploy/tests/test_host_observability_systemd.py deploy/tests/test_host_observability_collector.py
systemd-analyze --user verify deploy/systemd/mobile-agent-console-host-observability-prepare.service deploy/systemd/mobile-agent-console-host-observability.socket deploy/systemd/mobile-agent-console-host-observability@.service
docker compose run --rm backend-test ruff check --no-cache app/config.py app/services/host_observability_contract.py app/services/host_observability_service.py app/services/host_observability_socket_client.py tests/test_host_observability_api.py tests/test_host_observability_contract.py tests/test_host_observability_socket_client.py
docker run --rm -v "$PWD/deploy:/deploy:ro" mobile-agent-console-backend-test ruff check --no-cache /deploy/host-observability-collector.py /deploy/host-observability-runtime.py /deploy/host-observability-spike.py /deploy/tests/test_host_observability_collector.py /deploy/tests/test_host_observability_runtime.py /deploy/tests/test_host_observability_systemd.py
cd frontend && npm run test:host && cd ..
docker compose run --rm frontend-build
docker compose config --quiet
MAC_HOST_OBSERVABILITY_SOCKET_DIR="/run/user/$(id -u)/mobile-agent-console" docker compose -f compose.yaml -f compose.host-observability.yaml config --quiet
MAC_HOST_OBSERVABILITY_SOCKET_DIR="/run/user/$(id -u)/mobile-agent-console" docker compose -f compose.yaml -f compose.host.yaml -f compose.host-observability.yaml config --quiet
git diff --check
```

## Gate UI mobile HO-04

Eseguire il gate con un account admin e flag attivo, poi ripeterlo con flag
spento, viewer e operator:

- la voce **Host** compare soltanto nel primo caso; back torna alle sessioni e
  non esiste una route o scorciatoia alternativa per montare la vista;
- a 320, 390 e 768 CSS pixel non devono comparire overflow orizzontale, testo
  tagliato o controlli sotto 44 px; summary e anomalie precedono i dettagli,
  mentre le griglie passano a due colonne soltanto dal breakpoint desktop;
- navigare interamente da tastiera e screen reader: back/refresh hanno nomi
  accessibili, heading in ordine, loading usa `role=status`/`aria-live`, errori
  usano `role=alert`, badge e ragioni non dipendono soltanto dal colore;
- attivando **Host** da tastiera, `document.activeElement` deve diventare il
  titolo `H1[tabindex="-1"]` senza scroll o contorno da falso controllo. Dopo
  **Back**, il focus deve tornare al pulsante **Host** rimontato; ripetere a
  320/390 px e verificare che click/tap non lascino focus impropri o spostino
  la pagina;
- DevTools Network deve mostrare esattamente un GET host all'apertura, nessun
  timer o polling (anche i polling dashboard sono sospesi), e un GET per ogni
  pressione manuale di **Aggiorna**; tornando indietro durante una richiesta
  non devono apparire update React o errori in console;
- simulare due risposte concorrenti fuori ordine: soltanto la più recente può
  aggiornare la vista. Durante il refresh i dati correnti restano visibili;
  su 503/504 diventano stale con errore, senza essere cancellati;
- provare initial loading, errore senza snapshot con **Riprova**, liste vuote,
  timestamp vecchio e snapshot partial. Le ragioni `unknown` devono restare
  visibili insieme ai valori validi degli altri componenti;
- espandere **Esporta snapshot JSON** per ogni severity. Il testo della
  `textarea` read-only deve essere parseabile e deep-equal alla risposta API
  già sanitizzata, usando la stessa struttura senza wrapper, metadati UI o
  campi aggiunti. In stato `critical` la sezione deve avere evidenza visiva e
  testuale maggiore senza dipendere solo dal colore;
- con Clipboard API consentita, **Copia JSON** deve scrivere esattamente il
  valore della textarea e annunciare il successo via `aria-live`, senza nuove
  richieste. Negare o rimuovere `navigator.clipboard.writeText`: la textarea
  deve ricevere focus e selezione completa con istruzione per la copia manuale,
  senza `execCommand`. Verificare tastiera, screen reader e assenza di overflow
  a 320/390 px. Registrare nel gate il rischio residuo: pur sanitizzato, lo
  snapshot condiviso volontariamente può esporre dati operativi minimizzati
  fuori dal contesto amministrativo previsto;
- dopo refresh riuscito il JSON deve diventare deep-equal al nuovo snapshot;
  su refresh fallito devono restare invariati snapshot e JSON precedenti,
  insieme allo stato stale. Apertura, copia e fallback non devono aggiungere GET
  oltre a quelli già previsti per apertura e refresh manuale;
- verificare timestamp/durata, severity globale e per componente,
  memoria/swap, load, filesystem, gruppi e top processi, sole porte inattese,
  container problematici e conteggio dei problematici senza label.

Il test nativo senza dipendenze `npm run test:host` controlla gating, assenza di
polling Host, sospensione dei polling dashboard, lifecycle concorrente,
preservazione dello snapshot, serializzazione JSON esatta, Clipboard API,
fallback manuale e marker accessibili; viene eseguito anche durante la build
dell'immagine frontend.

## Gate end-to-end candidato HO-05/HO-06

Questo è l'ordine vincolante del gate finale. In HO-05 eseguire preflight e
controlli statici; i comandi che mutano l'istanza sono autorizzati soltanto
quando ROOT attiva HO-06.

1. Registrare senza pubblicarli gli identificatori tmux e l'hash dei listener
   TCP prima del deploy; catturare anche stato e ID di `tmux-runtime`. Non
   inserire output host-specific nella roadmap o nei log condivisi.
2. Eseguire tutti i comandi automatici sopra, la suite backend completa e lint
   globale. Failure già presenti devono essere riprodotti sul baseline e
   distinti da regressioni del round.
3. Ispezionare l'intero diff e tutti i file nuovi con secret scanner. Devono
   essere assenti home reali, hostname/IP, tailnet, UID inventariati, token,
   chiavi, nomi container reali e path privati. L'esempio deve contenere solo
   `example-*`, domini `.invalid`, path fittizi e soglie generiche.
4. Verificare le unit installate con `systemd-analyze --user verify` e
   `systemd-analyze --user security`. Collector e prepare devono essere vere
   user unit senza `User=root` e senza direttive `CapabilityBoundingSet`,
   `AmbientCapabilities` o `IPAddressDeny`: sui manager user rootless le prime
   possono impedire l'avvio con `218/CAPABILITIES`, mentre l'ultima non viene
   applicata. Dimostrare su processi reali `CapPrm`, `CapEff` e `CapAmb` nulli
   e registrare senza pubblicare anche `CapInh` (che il manager può ereditare,
   ma non rende utilizzabile una capability assente dai set permesso/effettivo);
   `RestrictAddressFamilies=AF_UNIX` è il blocco applicabile
   della rete IP. La prepare non deve acquisire `ProtectSystem`, `ProtectHome`
   o `PrivateTmp`: i relativi namespace romperebbero le ACL subuid. Il rischio
   residuo è la visibilità filesystem/home propria dell'utente durante la breve
   oneshot; sono obbligatori path runtime costante, script installato non
   scrivibile da soggetti non fidati, `NoNewPrivileges`, restrizioni
   namespace/SUID e verifica ACL/connect. Collector e socket conservano le
   restanti protezioni e i limiti runtime/connessioni.
5. Risolvere con probe l'UID rootless, avviare prepare/socket e ripetere ACL,
   negative permission, quattro connect concorrenti, timeout, cap, privacy e
   one-shot reaped. Nessuna porta TCP può apparire.
6. Prima del deploy ispezionare la configurazione Compose risolta e, dopo il
   deploy, il container:

   ```bash
   docker inspect mobile-agent-console-backend-1 --format '{{json .Config.User}} {{json .HostConfig.Privileged}} {{json .HostConfig.CapAdd}} {{json .Mounts}}'
   docker compose ps --format json
   ```

   Atteso: backend non-root nella modalità Docker, `Privileged=false`, nessuna
   capability aggiunta, sola directory socket `ro`; mai `/proc`, `/sys`, socket
   Docker, `network_mode: host`, porte wildcard o `group_add`. Il bind HTTP
   resta loopback/IP Tailscale esplicito secondo la configurazione esistente.
7. In HO-06 ricreare esclusivamente gli stateless con overlay, mai runtime:

   ```bash
   docker compose -f compose.yaml -f compose.host-observability.yaml up -d --no-deps backend web
   # oppure aggiungere anche compose.host.yaml nella modalità host-tmux
   ```

   Confrontare immediatamente ID/stato `tmux-runtime`, sessioni tmux e hash TCP
   con il preflight. Eseguire gate API e UI completi sia rootless sia host-tmux,
   inclusi RBAC, partial/stale, focus, no polling e refresh manuale.
8. Solo dopo `TEST-HO-06-T1 PASSED`, cambiare “What's new” da candidata a
   funzionalità rilasciata e validata. In caso contrario eseguire rollback:
   rimuovere l'overlay dalla composizione, ricreare soltanto `backend web`,
   disabilitare socket/prepare e rimuovere runtime/config temporanei. Verificare
   nuovamente che tmux e le sessioni non siano cambiati.
