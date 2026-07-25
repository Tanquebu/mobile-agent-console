# M1 — Integrazione con tmux reale

## Obiettivo

Verificare automaticamente il gateway contro un server tmux effettivo senza
toccare il socket host o le sessioni operative.

## Isolamento

Ogni test usa un socket tmux dedicato sotto la directory temporanea di pytest.
Il server viene terminato nel teardown con argv espliciti e `shell=False`.
La suite gira nel container `backend-test` con la stessa versione tmux
pinnata per il backend.

## Copertura

- ciclo create/list/capture/terminate;
- target canonico tramite session id numerico;
- directory corrente del pane;
- invio di testo senza Enter implicito;
- rinomina con spazi;
- testo libero incollato letteralmente tramite buffer, inclusi `$()`, `;`,
  virgolette e UTF-8;
- scomparsa della sessione e del server.

## Evidenza

Esecuzione del 25 luglio 2026:

- `docker compose run --build --rm backend-test`;
- 52 test passati, inclusi 3 test d'integrazione con tmux reale;
- nessuna sessione di test sul socket operativo.

I warning Starlette/httpx e cache pytest read-only sono noti e non bloccanti.
