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
