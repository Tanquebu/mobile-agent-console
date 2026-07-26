# Gate deployment Tailscale

## Obiettivo

Verificare che Mobile Agent Console sia raggiungibile dalla tailnet ma non
pubblichi la propria porta sull'interfaccia Internet dell'host.

## Procedura

1. Identificare le interfacce con `ip -brief address`, distinguendo loopback,
   interfaccia pubblica e `tailscale0`.
2. Controllare con `docker compose config` che `web.ports[].host_ip` sia
   l'indirizzo Tailscale esplicito o `127.0.0.1`, mai `0.0.0.0`.
3. Confrontare il mapping effettivo tramite `docker compose ps web`.
4. Verificare i socket con `ss -ltnp`: la porta web deve comparire soltanto
   sull'indirizzo autorizzato.
5. Controllare `tailscale serve status` e assicurarsi che eventuali regole
   Serve/Funnel di altri servizi non puntino alla porta di Mobile Agent
   Console.
6. Confermare `/health` e il normale accesso autenticato dalla tailnet.

## Esito

Gate superato sull'istanza di riferimento: porta web associata esclusivamente
all'indirizzo Tailscale, assente dagli indirizzi IPv4/IPv6 pubblici e da bind
wildcard. Un Funnel presente sull'host appartiene a un servizio differente e
non inoltra traffico verso Mobile Agent Console.

