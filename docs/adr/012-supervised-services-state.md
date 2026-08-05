# ADR 012 — Stato dei servizi supervisionati fuori dal collector one-shot

## Stato

Accettata.

## Contesto

La fotografia host sa rispondere a "quale container è giù" (ADR 011) ma non a
"quale servizio è giù", perché non tutto ciò che deve restare in piedi gira in
un container. Su un host tipico la supervisione è divisa fra più gestori:
Docker, systemd di sistema, systemd utente e un process manager come pm2. Un
singolo servizio applicativo può essere spezzato fra due di essi — un'API sotto
systemd e il suo frontend sotto pm2 — e oggi nessuno dei due pezzi è
sorvegliato.

Il meccanismo esistente più vicino, `process_policies`, non copre il caso per
due ragioni distinte.

La chiave è il `comm` del processo, che il kernel tronca a 15 caratteri e che
non identifica un servizio: due app pm2 diverse condividono `npm start` e sono
quindi indistinguibili, mentre il demone pm2 si presenta come `PM2 v7.0.1: God`
e porta dentro il proprio numero di versione, cioè una chiave che si rompe da
sola al primo aggiornamento.

Soprattutto, il modello esprime solo limiti superiori: `evaluate_process_policy`
confronta count e RSS aggregato con soglie che scattano quando un gruppo
*cresce*. Non esiste un minimo, quindi "questo servizio non deve mai stare giù"
non è esprimibile. È lo stesso vuoto che il modello di priorità ha appena
colmato per i container, rimasto aperto su tutto ciò che container non è.

Interrogare i supervisori dal collector one-shot è impossibile per la ragione
già documentata in ADR 011: `pm2 jlist` parla con il proprio demone su un socket
in `~/.pm2` e `systemctl --user` sul bus utente, e il collector gira con
`PrivateTmp`, `ProtectHome` e `ProtectSystem`, cioè dentro il profilo AppArmor
`unprivileged_userns` che nega quelle `connect()`. `ProtectHome` da solo
basterebbe a nascondere il socket di pm2.

## Decisione

La raccolta dello stato dei servizi supervisionati esce dal collector one-shot e
vive in una unit separata, `mobile-agent-console-service-state`, oneshot su
timer da 30s, che scrive `service-state.json` con permessi `0600`. Il collector
legge quel file tramite `services.state_file` e `services.max_age_seconds` nella
configurazione v2, esattamente come già fa con lo stato Docker. Senza la sezione
`services` il componente non compare affatto nello snapshot: un host che non lo
configura non vede una scheda vuota.

L'hardening della unit omette deliberatamente ogni direttiva che crea un mount
namespace, e lo stesso test di regressione che sorveglia la unit Docker
sorveglia anche questa.

La unit resta separata da quella Docker invece di essere fusa con essa. Il
motivo è l'isolamento dei fallimenti: `docker stats` impiega circa 2s e ha un
timeout da 20s, e un Docker che non risponde non deve ritardare né oscurare
l'evidenza sui servizi, che si raccoglie in meno di un secondo.

Le policy hanno chiave `supervisore:nome` — `systemd_user:example-api.service`,
`pm2:example-frontend` — cioè un identificatore stabile scelto da chi ha creato il
servizio, non un `comm` dedotto. Portano label e priorità nella stessa forma
delle `container_policies`: un servizio `essential` che non è in esecuzione
rende l'host critico con `essential_service_down`, uno `optional` resta visibile
con il suo stato senza concorrere alla severità.

L'assenza è un'evidenza di primo livello. Una policy la cui chiave non compare
nel file di stato significa che il servizio non esiste più per il suo
supervisore, ed è lo stato `absent`, giudicato come "giù". Ma questo vale solo
se il supervisore ha risposto: se non ha risposto, tutte le sue policy valgono
`unknown` con `supervisor_unavailable`, perché un supervisore irraggiungibile
non è la prova che i suoi servizi siano caduti. Il file dichiara quindi quali
supervisori hanno risposto, non solo cosa hanno detto.

I conteggi dei non dichiarati seguono la stessa asimmetria, e per un motivo
concreto: le app pm2 non dichiarate sono contate in `unmapped_count`, perché
esistono solo se qualcuno le ha create ed è utile sapere di averle dimenticate;
gli unit systemd non dichiarati non sono contati affatto, perché un host ne ha
decine che non appartengono all'operatore e il numero non direbbe nulla.

Come per i container, il file contiene i nomi reali di unit e app: resta
sull'host, e solo le label configurate attraversano il boundary.

## Conseguenze

È la seconda eccezione delimitata al principio dell'ADR 009 per cui nulla viene
raccolto senza una richiesta, e ha la stessa forma della prima: un unico file
sovrascritto, nessuno storico, nessuna serie temporale. La fotografia host resta
on-demand; ciò che è a timer è soltanto la fonte che non si può interrogare
dentro la richiesta.

Il prezzo è simmetrico a quello dell'ADR 011: l'evidenza sui servizi è vecchia
fino a 30 secondi, e un timer fermo diventa un modo nuovo di perdere il dato,
reso visibile da `services_state_stale` invece che silenzioso.

Il numero di riavvii viaggia nello snapshot ma non produce severità. È un
contatore cumulativo senza una linea di base con cui confrontarlo, quindi una
soglia sarebbe arbitraria; resta un fatto mostrato, nella stessa posizione dei
gruppi di processi senza policy — visibile, non giudicato. Vale però la pena
mostrarlo, perché un servizio che rimbalza è in esecuzione a ogni istante in cui
lo si guarda.

## Alternative scartate

- estendere `process_policies` con una soglia di conteggio minimo: la chiave
  `comm` resterebbe ambigua fra app pm2 diverse e legata alla versione per il
  demone, e un "almeno N processi" non distingue un servizio sano da uno che è
  ripartito in loop;
- fondere la raccolta nella unit Docker esistente: un solo timer e un solo file,
  ma il timeout lungo di `docker stats` diventerebbe il tempo di risposta anche
  dell'evidenza sui servizi, e un Docker guasto la cancellerebbe;
- interrogare direttamente D-Bus e il socket di pm2 dal collector: è proprio la
  `connect()` a essere negata dal profilo AppArmor, come per Docker;
- leggere `~/.pm2/dump.pm2`: descrive la configurazione salvata delle app, non
  il loro stato di esecuzione, quindi non distingue una app online da una
  fermata;
- una policy sul `MainPID` di ogni unit: identifica il processo ma non il suo
  stato per il supervisore, e perde del tutto i servizi assenti, che sono il
  caso da rilevare.
