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

L'endpoint degli stati agentici è autenticato e restituisce soltanto session id,
provider, stato e descrizione fissa. I frammenti di terminale usati dalle
euristiche non lasciano il backend e vengono sostituiti a ogni polling. I
pattern non devono mai essere inclusi nei log insieme alle righe corrispondenti.

Quando il client specifica un pane, il backend accetta soltanto un id numerico
e verifica tramite tmux che appartenga alla sessione indicata prima di usarlo
per capture, input, tasti o resize. Questo impedisce di usare una sessione
autorizzata come tramite verso un pane arbitrario dello stesso server.
