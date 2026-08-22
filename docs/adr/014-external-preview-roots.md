# ADR 014 — Root esterne per anteprime dai blocchi

## Stato

Accettata.

## Contesto

Gli agenti possono creare immagini, audio, video o Markdown fuori dalla
working directory della sessione, per esempio sotto `/tmp`, e citarne il path
nell'output. `MAC_ALLOWED_ROOTS` governa invece directory navigabili, upload e
download: ampliarla renderebbe queste capacità disponibili su tutta la root
aggiunta.

## Decisione

Introdurre `MAC_PREVIEW_ROOTS`, allowlist separata usata soltanto da metadata,
lettura testuale e streaming inline dell'anteprima. Le root esterne sono
montate read-only sotto `MAC_PREVIEW_MOUNT_ROOT`, conservando il path assoluto
(`/<root>` -> `/preview/<root>` nel container). Il browser continua a inviare
il path visto nell'output; il backend risolve il mount, segue i symlink e
rifiuta ogni destinazione che esca dalla root montata.

L'abilitazione in host mode è opt-in tramite `compose.host-preview.yaml`. La
root non compare nel browser directory, non accetta upload e non amplia gli
endpoint di download. Il media type è dedotto dai byte e resta ristretto a
Markdown UTF-8, JPEG/PNG/WebP, MP3/M4A e MP4.

## Conseguenze

Un utente autenticato può costruire manualmente richieste di anteprima per
qualunque file supportato dentro una root configurata, anche se il path non è
apparso davvero in un blocco. La regex client è una comodità, non un controllo
di autorizzazione. Per questo le root devono essere minime, read-only e mai
impostate a `/`; esporre l'intero `/tmp` è una scelta operativa esplicita.

La UI riusa `PreviewModal` e l'adapter file già impiegato dalla directory:
fullscreen, tipi media, date e correzioni future restano centralizzati.
