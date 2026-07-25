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
| Upload malevoli | nomi fisici UUID, tipi e signature allowlist, limite dimensione, nessuna estrazione archivi |
| Abuso risorse | limiti payload; rate limit in memoria separati per login e mutazioni |
| WebSocket hijacking | cookie autenticato e Origin allowlist; nessun token nell'URL |
| Leakage | niente output/prompt nell'audit; notifiche senza contenuto di default |
| Privilege escalation | servizio non-root, stesso utente proprietario del socket tmux |
| Confused deputy | permessi espliciti per create/interrupt/terminate e profili server-side |
| Snapshot manipolati | file UUID mode 0600, schema validato, path nuovamente sottoposti ad allowlist e soli comandi resume costanti |
| Database locale | path privato nel workspace, nessun prompt/output/segreto, migrazioni versionate |
| Password account | solo hash Argon2id nel database; secret usato esclusivamente per bootstrap iniziale |

## Rischi residui del vertical slice

L'account amministratore persistente resta single-user in questa fase; ruoli e
gestione account arriveranno separatamente. Nessun segreto entra nel bundle o nelle immagini: Compose
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
e diventano più critici. Nota operativa: l'unit systemd in `deploy/systemd/`
usa `PrivateTmp=true`, incompatibile con un socket in `/tmp` — non usarla
per componenti che devono raggiungere il socket host.

Quando il client specifica un pane, il backend accetta soltanto un id numerico
e verifica tramite tmux che appartenga alla sessione indicata prima di usarlo
per capture, input, tasti o resize. Questo impedisce di usare una sessione
autorizzata come tramite verso un pane arbitrario dello stesso server.
