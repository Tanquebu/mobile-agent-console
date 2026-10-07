# ADR 016 — Alert spazio disco da timer orario

## Stato

Accettata.

## Contesto

Il collector di osservabilità host (ADR 009) misura già i filesystem, ma solo
on-demand, quando qualcuno apre la vista Host, e con soglie percentuali. Un
disco che si riempie nel giro di qualche ora passa inosservato finché i servizi
non iniziano a fallire. Sull'host di riferimento è successo: root al 100% con
124 MB liberi, scoperto solo a guasto in corso.

Su dischi piccoli una soglia percentuale da sola è poco leggibile: il 90% di
40 GB lascia 4 GB, abbastanza per una giornata normale ma non per un batch di
rendering o un aggiornamento di immagini Docker.

## Decisione

Una unit host oneshot, `mobile-agent-console-disk-space`, gira ogni ora
(`OnCalendar=hourly`, `Persistent=true`). Esegue solo `statvfs` sui path
elencati in `MAC_DISK_SPACE_FILESYSTEMS` (file di environment privato, formato
`etichetta=path`) e scrive atomicamente un file `0600` con etichette, byte
totali e liberi (`f_bavail`, cioè lo spazio usabile senza privilegi),
percentuale e motivi dell'alert. I path non lasciano mai il file di
environment.

L'alert scatta se lo spazio libero scende sotto `MAC_DISK_SPACE_MIN_FREE_GB`
(default 5) **oppure**, se impostata, l'occupazione raggiunge
`MAC_DISK_SPACE_MAX_USED_PERCENT`. Un path non leggibile è esso stesso un alert.

Il backend legge il file da `GET /api/v1/disk-space` e calcola `stale` rispetto
a `MAC_DISK_SPACE_MAX_AGE_SECONDS` (default 3 ore). La PWA interroga l'endpoint
ogni 5 minuti e mostra il banner in cima alla dashboard e dentro l'header della
Console. Il dato scaduto resta visibile e viene segnalato come non aggiornato.

## Conseguenze

- Il controllo è indipendente dal collector on-demand: nessun allentamento del
  suo hardening, nessuna nuova superficie nel contratto v3.
- Con il disco pieno la scrittura del file può fallire. Il file precedente
  diventa `stale` entro tre ore e la PWA continua a mostrare l'ultimo alert,
  quindi il guasto non si traduce in silenzio.
- Nessuna notifica push: l'alert è visibile solo aprendo la PWA. Il
  `push_service` esistente è il punto di estensione se servirà.
