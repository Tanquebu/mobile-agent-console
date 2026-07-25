# Download file dalla directory

## Copertura

- download autenticato di immagini, PDF e documenti Word;
- risoluzione del path entro `MAC_ALLOWED_ROOTS`;
- risposta in streaming con `Content-Disposition: attachment`;
- pulsante dedicato nel browser della directory;
- anteprima testuale invariata e tipi non consentiti rifiutati.

## Evidenza

Verifica del 25 luglio 2026:

- 58 test backend passati;
- build frontend completata;
- deploy mirato di `backend` e `web`, senza ricreare `tmux-runtime`;
- health applicazione/tmux operativo;
- download manuale confermato sull'istanza pubblicata.
