# ADR 008 — TLS in nginx con certificato Tailscale

## Stato

Accettata.

## Contesto

Il gate `docs/gates/tailscale-deployment.md` ha validato il bind diretto di
`web` sull'IP Tailscale esplicito (`MAC_BIND_IP`), servito in `http://`:
Tailscale cifra già il traffico a livello di rete (WireGuard), quindi non è
un'esposizione non cifrata verso terzi.

Le API browser `Notification` e `ServiceWorker` (necessarie per le notifiche
locali e lo shell offline, vedi `docs/roadmap.md` M3) sono però disponibili
solo in un "contesto sicuro": `https://`, oppure `http://localhost`. Il
bind diretto su un IP Tailscale in `http://` non soddisfa questo requisito,
indipendentemente dalla cifratura di trasporto già presente — è una policy
del browser, non un giudizio sulla sicurezza reale del canale. Le due voci
sono quindi rimaste `[~]` in roadmap finché non risolto.

## Alternative considerate

- **`tailscale serve`** (`docs/security.md`, pattern generico consigliato):
  bind di `web` su `127.0.0.1`, `tailscale serve` fa reverse proxy HTTPS sul
  MagicDNS name. Scartata per questo deployment: con Docker rootless il bind
  su `127.0.0.1` aveva già dato problemi in passato (da cui la scelta
  originaria del bind diretto sull'IP Tailscale); riproverlo avrebbe
  rimesso in discussione una configurazione già validata dal gate, oltre a
  spostare la porta pubblicata dal 8081 esplicito al 443 di Serve.
- **Certificato self-signed**: evita la dipendenza da Tailscale ma richiede
  di fidarsi manualmente del certificato su ogni dispositivo/browser (una
  PWA installata da un contesto "non attendibile" ha comunque limitazioni),
  attrito ripetuto per uno use-case single-user.

## Decisione

nginx termina TLS sulla stessa porta pubblicata (`8080` nel container,
`MAC_BIND_PORT` sull'host), con un certificato reale ottenuto tramite
`tailscale cert` per il nome MagicDNS del nodo — bind identico a prima
(nessuna nuova esposizione, nessun cambio di porta), ma raggiungibile solo
via `https://<nome-magicdns>:<MAC_BIND_PORT>` invece che dall'IP nudo in
`http://`.

- Il certificato/chiave vengono montati nel container `web` come Compose
  `secrets` (stesso meccanismo già usato per password e session secret),
  di default da `.secrets/tls/` (gitignored, mai nell'immagine).
- Richiede una tantum `sudo tailscale set --operator=$USER`, poi
  `tailscale cert` non necessita più di root.
- Rinnovo: `deploy/tls-renew.sh` più
  `deploy/systemd/mobile-agent-console-tls-renew.{service,timer}` (stesso
  pattern degli altri collector host-side), che rieseguono `tailscale cert`
  e riavviano `web` **solo se il certificato è effettivamente cambiato**.
- `MAC_COOKIE_SECURE` passa a `true` (i cookie `Secure` richiedono HTTPS) e
  `MAC_CORS_ORIGINS` include la nuova origine `https://`; nessun altro
  controllo di sicurezza (cookie firmato, CSRF, Origin check WebSocket)
  cambia.
- Nessun riferimento all'hostname o all'IP reali in file versionati:
  restano solo in `.env` (gitignored) e nell'environment file della user
  unit sotto `~/.config/`.

## Conseguenze

- L'accesso via IP nudo in `http://` smette di funzionare (nginx ora fa solo
  `listen 8080 ssl`): bookmark/scorciatoie PWA esistenti vanno aggiornati
  all'URL `https://<nome-magicdns>:<porta>`.
- Il certificato dipende dal servizio `tailscale cert`/tailnet: se il nodo
  perde la capacità di emettere/rinnovare certificati (policy tailnet
  disattivata), il timer di rinnovo fallisce silenziosamente finché non
  osservato — da monitorare come per gli altri collector opzionali.
- Rimane valido il bind esclusivo sull'IP Tailscale del gate esistente: solo
  lo schema (`http` → `https`) e il meccanismo di verifica (`curl` senza
  `-k`, dato il certificato pubblico attendibile) cambiano nella procedura
  del gate.
