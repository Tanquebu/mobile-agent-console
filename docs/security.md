# Sicurezza e threat model

## Asset e confini

Asset principali: accesso alla shell dell'utente, sorgenti e segreti nei
workspace, input/output terminale, token e audit. I confini sono browser ↔
FastAPI, FastAPI ↔ tmux e host ↔ rete Tailscale.

## Minacce principali e controlli

| Minaccia | Controllo presente / previsto |
|---|---|
| Esposizione Internet | bind `127.0.0.1` o IP 100.x esplicito; porta host 8081; firewall |
| Accesso non autorizzato | password runtime, sessione firmata HttpOnly con scadenza |
| CSRF / furto token | SameSite strict, CSRF in memoria e Origin check |
| Command injection | argv, `shell=False`, operazioni tipizzate, regex sessioni/pane |
| Input interpretato da tmux | `load-buffer -` + `paste-buffer`; tasti su endpoint separato |
| Path traversal | nessun path dal client nello slice; poi resolve + `is_relative_to` allowlist |
| Upload malevoli | nomi fisici UUID, tipi e signature allowlist, limite dimensione, nessuna estrazione archivi; anteprime immagine generate da Pillow in modo best-effort (eccezioni di decodifica non bloccano l'upload, semplicemente non producono thumbnail) |
| Abuso risorse | limiti payload; rate limit in memoria separati per login e mutazioni; quota aggregata di byte allegati per sessione oltre al limite per singolo file |
| WebSocket hijacking | cookie autenticato e Origin allowlist; nessun token nell'URL |
| Leakage | niente output/prompt nell'audit; notifiche senza contenuto di default |
| Audit sensibile o eccessivo | solo metadati tipizzati; esclusi body, query, IP, prompt, output, filename e operazioni terminali ad alta frequenza |
| Privilege escalation | servizio non-root, stesso utente proprietario del socket tmux |
| Confused deputy | ruoli ricontrollati dal database, permessi espliciti per operazioni mutative |
| Snapshot manipolati | file UUID mode 0600, schema validato, path nuovamente sottoposti ad allowlist e soli comandi resume costanti |
| Archivio manipolato | directory ricontrollata contro l'allowlist e profilo server-side prima del rilancio |
| Database locale | path privato nel workspace, nessun prompt/output/segreto, migrazioni versionate |
| Backup manipolati | checksum archivio e file, manifest con path chiusi, restore offline e riservato all'operatore host |
| Quote provider sensibili | collector host-side, output JSON sanitizzato; credenziali e transcript non montati nel backend |
| Ricognizione host | collector one-shot via socket Unix 0660; nessun mount di `/proc`, `/sys` o Docker, nessuna porta TCP e nessuna API nello spike |
| Cronologia Claude | opt-in esplicito, derivato `0600`, soli messaggi testuali, limiti/staleness e endpoint autenticato |
| Classificazione agenti | sole ultime righe in memoria, risposta con stato tipizzato; nessun output persistito, restituito o inserito nell'audit |
| Password account | solo hash Argon2id nel database; secret usato esclusivamente per bootstrap iniziale |
| Web Push abusata | chiave privata VAPID `0600` generata/persistita lato server, mai esposta al client (solo la pubblica); payload push senza output/prompt, stesso invariante delle notifiche locali; subscription rimosse automaticamente se il push service segnala 404/410 |

## Rischi residui del vertical slice

L'account amministratore persistente resta single-user in questa fase; ruoli e
gestione account applicano `admin`, `operator` e `viewer`. Nessun segreto entra nel bundle o nelle immagini: Compose
monta file ignorati da Git. tmux eredita l'autorità dell'utente Linux, quindi la
compromissione del backend equivale alla compromissione di quell'utente.

## Deployment

Non eseguire come root e non fare bind su wildcard. Preferire:

```bash
tailscale serve --bg http://127.0.0.1:8081
```

La policy Tailscale deve limitare utenti/dispositivi; l'applicazione mantiene
comunque autenticazione propria. Verificare con `ss -ltnp` che la porta ascolti
solo su loopback o sull'IP Tailscale.

Con il bind diretto sull'IP Tailscale (alternativa sopra), nginx può
comunque terminare TLS con un certificato reale (`tailscale cert`) invece di
restare in `http://`: le API `Notification`/`ServiceWorker` del browser
richiedono un contesto sicuro indipendentemente dalla cifratura di trasporto
già fornita da Tailscale. Vedi ADR 008 e `deploy/tailscale/README.md`.

Per un repository pubblico: `.secrets/`, `.env`, immagini e log non devono mai
contenere credenziali. Usare secret scanning in CI e ruotare immediatamente
qualsiasi valore accidentalmente pubblicato; rimuoverlo dalla cronologia non è
sufficiente a renderlo nuovamente sicuro.

Gli snapshot di riavvio non contengono output del terminale, environment,
segreti, PID o comandi arbitrari. Nome e directory vengono ricontrollati al
ripristino; Codex e Claude sono rilanciati soltanto verso il picker di resume
con stringhe definite dal server. La directory `.agent-snapshots` deve restare
su storage persistente e non essere versionata.

La modalità host-tmux (ADR 005) amplia l'autorità del backend: il container
si collega al socket tmux di default dell'utente host, quindi una sua
compromissione permette di leggere e comandare **tutte** le sessioni tmux di
quell'utente — esecuzione arbitraria come l'utente host. Il rischio coincide
con quello residuo già dichiarato sopra, ma senza la mitigazione del socket
dedicato: è accettato deliberatamente per un deployment single-user su rete
Tailscale privata. Contromisure obbligatorie: attivazione solo tramite
opt-in esplicito (`COMPOSE_FILE` + `MAC_TMUX_SOCKET_FILE`, mai default
silenziosi), backend con lo stesso UID/GID dell'utente proprietario del
socket, verifica del socket e del server all'avvio (log + campo `tmux` in
`/health`), e divieto per il backend di avviare il server tmux (altrimenti
il server partirebbe dentro il container in modo silenzioso). I tre
controlli di autenticazione e il bind loopback/Tailscale restano invariati
e diventano più critici. Le user unit Compose non usano `PrivateTmp`, così
il socket host in `/tmp/tmux-$UID` resta quello reale dell'utente.

Il cookie v2 include l'username nel payload firmato. Ogni richiesta
ricontrolla nel database che l'account esista e sia attivo: disabilitare un
utente revoca quindi anche cookie già emessi. `viewer` può consultare output,
directory e download; `operator` aggiunge le mutazioni sulle sessioni;
`admin` gestisce gli account. L'ultimo amministratore attivo non può essere
disabilitato.

Creazione, elenco, download ed eliminazione dei backup sono riservati agli
amministratori e le mutazioni entrano nell'audit. I backup contengono hash
password e metadati applicativi: devono quindi restare con permessi `0600` e,
se copiati fuori dalla VPS, su storage cifrato. Il contenuto dei file allegati
(con TTL) non è incluso; i loro metadati (nome, tipo, dimensione, path) vivono
nel database insieme a utenti/archivi/audit e rientrano quindi nel backup del
database, con lo stesso TTL di scadenza dei file corrispondenti. Il restore
non è esposto via HTTP e deve essere eseguito con backend fermo.

Il collector quote invoca soltanto i due path di script fissati nella user unit,
con argv e timeout, senza `shell=True` e senza `--fresh`. Nel file condiviso
finiscono provider, percentuali, reset, timestamp ed eventuali errori troncati:
mai token, header HTTP o contenuti dei transcript. Il file usa permessi `0600`.

Il boundary di osservabilità host (ADR 009) è opt-in e usa socket activation
systemd con `Accept=yes`: ogni richiesta crea un processo one-shot confinato a
`AF_UNIX`. La directory del socket è `0750`, il socket è `0660` e l'accesso del
backend usa ACL POSIX nominali per i soli UID host autorizzati, mai permessi
world-writable. Il gruppo proprietario non ha accesso effettivo. L'overlay
monta soltanto quella directory in read-only;
vietati `/proc`, `/sys` e `/var/run/docker.sock`. Il client impone timeout,
limite di risposta e JSON object envelope senza propagare errori grezzi. HO-02
raccoglie solo su richiesta. HO-03 espone la fotografia solo con feature flag
opt-in, tramite GET admin-only e rate limit in memoria separato: viewer e
operator ricevono `403`, socket/risposta invalida `503` e timeout `504` con
codici stabili che non includono dettagli del collector. Il payload viene
validato integralmente con il contratto v1 e non entra in log, audit, database,
`/health` o metriche. La vista HO-04 è montata soltanto per admin+flag, non
effettua polling, sospende i polling dashboard mentre è aperta e scarta
risposte obsolete o successive all'unmount; un errore di refresh conserva i
dati validi marcandoli stale. L'export della vista serializza esattamente quel
payload già validato e sanitizzato, senza fetch, arricchimenti o persistenza
aggiuntivi. La copia negli appunti o la selezione manuale sono azioni esplicite
dell'admin. Resta il rischio residuo di condividere volontariamente anche dati
operativi minimizzati con destinatari o applicazioni non fidati: la UI lo
descrive come snapshot sanitizzato, ma non può controllarne l'uso dopo la copia.
In rootless Docker o
con user namespace remapping l'UID host mappato viene rilevato con un file probe
isolato e salvato solo nell'environment privato; un mapping errato deve fallire
chiuso. Il gate verifica ACL e connect reale in ogni modalità.

La unit collector viene eseguita dal manager user, parte con capability
effettive/permesse/ambienti nulle e abilita filesystem/home protetti in
lettura, protezioni cgroup e tunable kernel, restrizioni namespace, realtime,
SUID/SGID e IPC, architettura syscall nativa, sola `AF_UNIX` e umask `0077`. Non usa
`ProtectProc`/`ProcSubset` perché il suo compito richiede le viste host
minimizzate di `/proc`; il backend continua a non montarle. Non vengono
impostate `CapabilityBoundingSet`, `AmbientCapabilities` o `IPAddressDeny`:
nei manager user rootless le prime possono fallire con `218/CAPABILITIES` e
l'ultima è ignorata. Per lo stesso motivo non vengono dichiarate
`PrivateDevices`, `ProtectClock`, `ProtectKernelLogs` o
`ProtectKernelModules`; `ProtectHostname` richiederebbe un namespace UTS che
il manager può ignorare. La prepare mantiene sola `AF_UNIX` e le restrizioni non
basate su mount namespace. Socket e directory usano `0660`/`0750`, massimo 16 connessioni
e trigger limitato; nessuna unit imposta o richiede root.

La oneshot che prepara le ACL usa `DefaultDependencies=no` per essere completata
prima del bind della user socket senza introdurre un ciclo attraverso
`basic.target`/`sockets.target`. Non applica un mount namespace filesystem:
nelle user unit questo renderebbe non rappresentabili gli UID subordinati e
farebbe fallire `setfacl`. Per lo stesso motivo non usa `PrivateTmp`. Il rischio
residuo è che la breve oneshot conservi la visibilità di filesystem e home
dell'utente; viene contenuto usando un path costante sotto `%t`, uno script di
installazione fidato, ACL dichiarative, timeout dei subprocess e un gate
runtime fail-closed. Restano `NoNewPrivileges`, `RestrictNamespaces`,
`RestrictSUIDSGID`, `RestrictAddressFamilies=AF_UNIX`, umask `0077` e nessuna
identità privilegiata. Collector e socket conservano l'hardening filesystem.

Il collector host observability legge soltanto `meminfo`, `loadavg`, `uptime`, statistiche e fd
dei processi, tabelle TCP e filesystem configurati. Non legge cmdline,
environment o working directory. IP e indirizzi diventano scope tipizzati;
path e nomi reali dei container restano nella configurazione privata `0600`.
Docker è opt-in e invocato con `/usr/bin/docker ps -a --format ...`, argv fisso,
`shell=False`, timeout due secondi, `stderr` scartato e output massimo 64 KiB
applicato mentre il subprocess è in esecuzione; record malformati falliscono
chiuso. Il timeout copre anche l'attesa dopo EOF di stdout: il processo viene
terminato e reaped, evitando sia attese fuori bound sia zombie. La configurazione è aperta componente per componente senza seguire
symlink, richiede mode esatto `0600` e viene letta dallo stesso file descriptor
con limite e confronto dei metadati pre/post per rilevare sostituzioni in race.
La risposta è limitata a 128 KiB e la unit a cinque secondi. Un errore parziale
produce `unknown` nel solo componente coinvolto e non viene trasformato in
`ok`; il contratto completo e i limiti sono in
`docs/contracts/host-observability-v1.md` e
`docs/contracts/host-observability-v2.md`. La v2 aggiunge un campione locale e
limitato dei contatori swap e policy private per porta/scope e aggregati
count/RSS. Il payload espone solo delta, esito policy e scope normalizzati:
nessuna soglia privata, attestazione firewall, raggiungibilità presunta, sonda
esterna, API cloud o credenziale attraversa il boundary. Backend e frontend
accettano v1/v2 durante il rollout; versioni future, forme miste e campi extra
falliscono chiuso senza essere loggati.

Il collector dello stato sessioni legge processi e transcript esclusivamente
sull'host. Il file atomico risultante contiene solo identificatore numerico
tmux, provider e modalità permessi normalizzata. Percorsi dei transcript,
prompt, risposte e argomenti dei processi non sono serializzati né esposti
dall'API; il backend non riceve accesso a `/proc`, `~/.codex` o `~/.claude`.
La cache context Claude contiene soltanto session UUID, percentuale, capienza,
timestamp e pane tmux; i file sono `0600`. Il collector pubblica al backend
soltanto la percentuale normalizzata `0..100`.

La cronologia Claude è una deliberata estensione del dato esposto: quando
abilitata, il collector host legge il transcript e copia nel workspace
persistente soltanto testo `user`/`assistant`, UUID e timestamp. Esclude
thinking, tool use/result, allegati, record meta e sidechain; limita la sorgente
a 16 MiB, ogni messaggio a 32 KiB, ogni sessione a 500 messaggi e il file
complessivo a 1,5 MiB. Il backend rifiuta file oltre 2 MiB, record non conformi
e raccolte più vecchie di 30 secondi. Il file e la scrittura temporanea sono
`0600`; prompt e risposte restano esclusi da log, audit e database.

Il default è `MAC_CLAUDE_HISTORY_ENABLED=false`. Spegnere il flag rimuove
l'endpoint e la UI ripiega sul live senza modificare WebSocket o tmux; fermare
il timer elimina inoltre nuove copie persistenti. Il file derivato esistente
va rimosso manualmente se si vuole cancellarne i contenuti.

Il collector dell'orchestratore usa URL, header e token configurati solo nel
file environment privato e li invia a un endpoint read-only. L'endpoint deve
usare HTTPS, salvo quando è strettamente su loopback. Il collector convalida e
riscrive il contratto prima della condivisione con il backend; il file
risultante contiene solo identificatori opachi, stato e metadati di scheduling.
URL, header, token, prompt, path, pane, checkpoint ed errori grezzi non sono
serializzati né montati.

L'endpoint degli stati agentici è autenticato e restituisce soltanto session id,
provider, stato e descrizione fissa. I frammenti di terminale usati dalle
euristiche non lasciano il backend e vengono sostituiti a ogni polling. I
pattern non devono mai essere inclusi nei log insieme alle righe corrispondenti.

Gli artefatti prodotti dall'agente sono serviti solo da dentro
`MAC_ARTIFACTS_ROOT/<session_id>/`: il backend non si fida di alcun path
stampato nel terminale né apre altre directory, e la lista/il download
rivalidano nome file e tipo (by-signature, stessa allowlist di M2A: immagini,
PDF, testo) a ogni accesso, indipendentemente da cosa sia stato scritto lì. Il
rischio residuo è che l'agente (se istruito, deliberatamente o per prompt
injection) copi lì un file non voluto — stesso modello di fiducia già accettato
per gli allegati M2A, qui invertito. La pulizia è legata al ciclo di vita della
sessione (archiviazione/terminazione), non a un TTL: la cartella si popola solo
per consegna deliberata, non per cattura automatica di tutto ciò che l'agente
tocca.

Quando il client specifica un pane, il backend accetta soltanto un id numerico
e verifica tramite tmux che appartenga alla sessione indicata prima di usarlo
per capture, input, tasti o resize. Questo impedisce di usare una sessione
autorizzata come tramite verso un pane arbitrario dello stesso server.
