# Download file dalla directory

## Copertura

- download autenticato di immagini, PDF, documenti Word e audio MP3;
- elenco, download e anteprima audio degli MP3 nella cartella Artefatti, con
  validazione della firma ID3 o del frame MPEG;
- selezione e upload degli MP3 dal pulsante Allega, con la stessa validazione
  del contenuto lato backend;
- risoluzione del path entro `MAC_ALLOWED_ROOTS`;
- risposta in streaming con `Content-Disposition: attachment`;
- pulsante dedicato nel browser della directory;
- anteprima testuale invariata e tipi non consentiti rifiutati.

## Evidenza

Verifica del 13 agosto 2026:

- 372 test backend passati e controlli Ruff superati;
- build frontend completata;
- deploy mirato di `backend` e `web`, senza ricreare `tmux-runtime`;
- health applicazione/tmux operativo;
- download MP3 autenticato confermato sull'istanza pubblicata sia dalla
  directory sia dagli Artefatti, con contenuto integro e media type atteso.
