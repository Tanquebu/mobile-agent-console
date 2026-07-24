# ADR 004: host tmux come modalità MVP

Stato: superata da ADR 005 — la modalità host usa il socket tmux di
default dell'utente, non un socket dedicato.

Gli agenti CLI installati sull’host non sono automaticamente disponibili nel
runtime Docker. L’MVP supporterà quindi una modalità host-tmux esplicita, con
un solo socket dedicato dell’host, ad esempio `/tmp/mobile-agent-console.sock`,
montato in read-write nel backend. Non verrà montata indiscriminatamente
`/tmp` né il socket tmux personale globale.

Configurazione prevista:

```env
TMUX_MODE=host
TMUX_SOCKET_FILE=/tmp/mobile-agent-console.sock
```

La modalità Docker-runtime resterà disponibile per sviluppo e test isolati.
Confronteremo compatibilità agenti, persistenza, ownership del socket,
superficie di compromissione e semplicità operativa prima della decisione
definitiva.
