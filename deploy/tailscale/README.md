# Tailscale Serve o bind diretto

## Bind diretto sull'interfaccia Tailscale

Ricavare l'IPv4 Tailscale e impostarlo in `.env`:

```bash
tailscale ip -4
MAC_BIND_IP=100.x.y.z
MAC_BIND_PORT=8081
MAC_CORS_ORIGINS=http://100.x.y.z:8081
docker compose up -d web
```

Il mapping Docker è parametrizzato e si lega esclusivamente a quell'IP.
Non impostare `MAC_BIND_IP=0.0.0.0`.

## Tailscale Serve

Con il web container pubblicato su `127.0.0.1:8081`:

```bash
tailscale serve --bg http://127.0.0.1:8081
tailscale serve status
```

Limitare l'accesso con policy/grant Tailscale e mantenere l'autenticazione
applicativa. Non usare `tailscale funnel`.

## TLS con bind diretto (`tailscale cert`)

Le API `Notification` e `ServiceWorker` del browser richiedono un contesto
sicuro (`https://` o `localhost`): il solo bind diretto sull'IP Tailscale
resta `http://`, quindi non basta a sbloccarle, anche se il traffico è già
cifrato da Tailscale a livello di rete. Vedi
`docs/adr/008-tailscale-cert-tls.md` per la decisione completa. Per
mantenere il bind diretto sull'IP Tailscale (nessuna nuova esposizione) e
avere comunque un contesto sicuro, nginx termina TLS con un certificato
reale emesso per il nome MagicDNS del nodo:

```bash
sudo tailscale set --operator=$USER   # una tantum
mkdir -p .secrets/tls
tailscale cert --cert-file .secrets/tls/tailscale.crt \
  --key-file .secrets/tls/tailscale.key <nome-magicdns>   # tailscale status --self
```

In `.env`: `MAC_COOKIE_SECURE=true` e `MAC_CORS_ORIGINS` con l'origine
`https://<nome-magicdns>:8081`. Poi `docker compose up -d web backend`.
L'app va raggiunta da `https://<nome-magicdns>:8081`, non più dall'IP nudo
in `http://`. Rinnovo automatico: installare
`deploy/systemd/mobile-agent-console-tls-renew.service`/`.timer` (stesso
pattern degli altri collector host-side) con `MAC_TAILNET_HOSTNAME`
impostato in `~/.config/mobile-agent-console/environment`.
