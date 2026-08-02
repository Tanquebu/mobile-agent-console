# Contratto host observability v1

Il collector host-side produce un solo oggetto JSON per connessione. Il modello
Pydantic autorevole per questa variante è `HostObservabilitySnapshotV1` in
`backend/app/services/host_observability_contract.py`; campi extra e forme v2
mescolate nel payload v1 sono rifiutati. L'endpoint accetta anche il contratto
v2 durante il rollout, documentato in `host-observability-v2.md`. La validazione è non coercitiva: stringhe al
posto di numeri o booleani non sono convertite implicitamente e ogni valore
timestamp di tipo non ammesso produce una normale `ValidationError` Pydantic.

HO-03 restituisce lo stesso modello, senza wrapper, da
`GET /api/v1/host-observability`. Il backend applica nuovamente la validazione
completa: un envelope manipolato o fuori schema non viene inoltrato al browser.
La route è disattivata per default (`404`), richiede ruolo admin (`401`/`403`),
applica un rate limit dedicato (`429`) e usa errori sicuri tipizzati:
`host_observability_unavailable` e `host_observability_invalid_response` con
HTTP 503, `host_observability_timeout` con HTTP 504. Nessun errore include il
payload o dettagli grezzi del collector.

La vista HO-04 esporta il corpo di questa stessa risposta con
`JSON.stringify(snapshot, null, 2)`: nessun envelope, campo UI, timestamp di
copia o altra informazione viene aggiunta. L'export resta legato all'ultimo
snapshot valido; un errore di refresh non lo sostituisce. Clipboard e selezione
manuale non effettuano richieste API e non cambiano il contratto.

## Envelope

- `schema_version`: sempre `1`;
- `collected_at`: timestamp timezone-aware con offset UTC esatto;
- `duration_ms`: durata della fotografia, massimo contrattuale 10 secondi;
- `status`: `ok`, `warning`, `critical` o `unknown`;
- `reasons`: massimo otto codici tipizzati;
- componenti `memory`, `load`, `filesystems`, `processes`, `listeners`,
  `docker`.

Ogni componente ha stato e motivazioni propri. Un dato indisponibile è
`unknown`, mai `ok`; un errore Docker non rimuove gli altri componenti.

## Dati ammessi

- memoria/swap: byte e percentuali;
- load average 1/5/15, numero CPU e valore a 1 minuto normalizzato per CPU;
- filesystem: label configurata, byte e percentuale, massimo 16;
- processi: PID, nome `comm` sanitizzato, label opzionale, RSS ed età; massimo
  10 processi e 20 aggregazioni omonime;
- listener: porta, scope normalizzato (`loopback`, `tailscale`, `wildcard`,
  `other`), processo sanitizzato opzionale e corrispondenza alle attese;
  massimo 50;
- Docker opzionale: disponibilità, label configurate dei container
  problematici, stato normalizzato e numero di problematici senza label;
  massimo 50 label.

Non sono ammessi hostname, username, cmdline, environment, working directory,
path filesystem, IP grezzi, inode socket, container ID, image name, nome reale
di container non mappato o `stderr`.

## Limiti di raccolta

La configurazione è al massimo 64 KiB e deve essere un file regolare con mode
esatto `0600`, posseduto dall'utente collector. Nessun componente del path,
incluso il file, può essere un symlink: il collector apre il percorso un
componente alla volta, legge dallo stesso file descriptor con limite effettivo
e verifica che metadati e identità non cambino durante la lettura. La risposta
è al massimo 128 KiB. La scansione
considera al massimo 4096 PID e 1024 fd per PID; l'output Docker è limitato a
64 KiB durante lo streaming (il processo viene terminato appena supera il
limite), il subprocess a 2 secondi e la unit one-shot a 5 secondi. Record
Docker malformati rendono il componente `unknown`. La deadline copre l'intero
lifecycle: anche se stdout raggiunge EOF, un processo ancora vivo viene
terminato e reaped entro il timeout.

La lettura listener considera insieme `/proc/net/tcp` e `/proc/net/tcp6`: se
una vista manca, è vuota, ha un header/record significativo non interpretabile
o la scansione supera 1.000 listener, la copertura è incompleta e il componente
è almeno `unknown` con `listeners_partial`. Il prefisso Tailscale IPv6
`fd7a:115c:a1e0::/48` è normalizzato nello scope `tailscale`. Contatori
filesystem incoerenti producono `filesystem_unavailable`; stato e ragioni dei
singoli filesystem risalgono al componente e all'envelope.

## Configurazione privata

`deploy/host-observability.example.json` documenta lo schema con dati fittizi.
L'esempio corrente è v2; una configurazione v1 privata esistente continua a
essere accettata. La copia reale rimane fuori dal repository e contiene path, porte attese, label,
mapping dei nomi container e soglie. Il collector Docker usa esclusivamente
`/usr/bin/docker ps -a --format ...` con argv fissi e `shell=False`.
