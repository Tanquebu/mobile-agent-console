# ADR 010 — Storico del consumo di budget e attribuzione per sessione

## Stato

Accettata. Copre la fase A (serie storica della quota provider) e la fase B
(attribuzione del consumo per sessione). Il drill-down sul contenuto dei turni
resta fuori decisione: sarà una fase C separata.

## Contesto

La quota provider è oggi una fotografia istantanea. Il collector a timer
sovrascrive `provider-rate-limits.json` ogni 60 secondi, il backend lo rilegge
su richiesta e la dashboard mostra un solo punto nel tempo. Un amministratore
che rilegge la percentuale dopo venti minuti osserva un valore più alto senza
alcun modo di stabilire quando la crescita sia avvenuta né quale attività
l'abbia prodotta.

Tre proprietà del sistema rendono il fenomeno strutturale, non accidentale.

Il consumo dominante non è visibile. I subagent scrivono transcript propri sotto
`<progetto>/<uuid>/subagents/` e possono superare di parecchie volte il volume
della sessione che li ha generati; nessuna schermata li rappresenta.

Il consumo non passa necessariamente da MAC. Le sessioni avviate senza pane tmux
— run headless di un orchestratore esterno, esecuzioni pianificate — consumano
la stessa quota per-account. Tutti i collector esistenti scoprono i transcript
partendo dai pane tmux, quindi ciò che non ha un pane non compare.

La fonte della percentuale può congelarsi. Il collector invoca lo script quote
senza forzare un aggiornamento remoto e legge una cache aggiornata dallo
statusline a ogni turno. Quando nessuna sessione lavora il valore resta fermo e
poi si sposta di scatto: una serie costruita ingenuamente su quella fonte
mostrerebbe plateau e gradini che non corrispondono al consumo reale.

Esiste inoltre una tensione dichiarata con l'osservabilità host. ADR 009 scarta
esplicitamente i collector a timer perché «raccolgono senza richiesta e aprono
implicitamente alla persistenza temporale», e il gate di prodotto del modulo ne
ha approvato i confini «senza serie storiche».

## Decisione

### La persistenza temporale è ammessa per le quote provider e resta esclusa per l'osservabilità host

I due domini hanno costi e superfici diverse, e questa ADR li separa in modo
esplicito.

L'osservabilità host descrive lo stato di una macchina: memoria, processi,
listener, filesystem. È informazione ad alta risoluzione e ad alta sensibilità,
il cui valore è quasi interamente nel presente, e conservarla significherebbe
costruire un archivio di ricognizione dell'host. Resta on-demand, senza storia,
senza log e senza polling.

La quota provider descrive il consumo di una risorsa contrattuale che si accumula
in finestre di cinque ore e sette giorni. Il suo valore è quasi interamente nella
differenza fra due istanti: senza serie storica il dato non risponde alla domanda
per cui viene raccolto. È inoltre già persistito su file dal collector esistente e
già letto dal backend; ciò che cambia è la conservazione dei campioni passati, non
l'esistenza della raccolta né l'ampiezza del boundary.

Questa distinzione non riapre i confini del modulo host observability, che
restano quelli di ADR 009 e del relativo gate.

### Lo storico è un file JSONL append-only scritto host-side

I campioni sono scritti dai collector host-side in
`.mobile-agent-console/*.jsonl`, con permessi `0600`, e letti dal backend in sola
lettura con validazione Pydantic, esattamente come i quattro file di stato già
esistenti. Il backend continua a non scrivere e a non fare polling dei collector.

La tabella SQLite è scartata. Il produttore dei campioni è un timer systemd che
vive fuori dal container, mentre `app.db` è posseduto dal backend attraverso le
migrazioni Alembic: due scrittori indipendenti sullo stesso database, con lo
schema di proprietà di uno solo, sarebbe la disposizione peggiore. L'alternativa
— far campionare il backend — introdurrebbe nel container uno scheduler e uno
stato che oggi non ha.

La crescita è limitata alla sorgente. I campioni identici consecutivi non vengono
appesi, i file ruotano su una soglia di byte e la retention predefinita è di
quattordici giorni, sufficiente a coprire la finestra di sette giorni con margine.

### La freschezza è dichiarata, non simulata

Ogni campione porta sia l'istante di raccolta sia l'istante di aggiornamento
della sorgente. Quando la distanza supera la soglia il campione è marcato
stantio, e il grafico rappresenta l'intervallo come non osservato invece di
interpolare una curva dove il dato era congelato.

L'aggiornamento forzato, che costa una chiamata remota, non diventa periodico:
resta un'azione su richiesta esposta con lo stesso meccanismo di ADR 009 — socket
Unix con socket activation, collector one-shot, nessun demone e nessuna porta di
rete — protetta da autenticazione amministrativa e da un rate limit dedicato.

### L'attribuzione scopre i transcript per tempo di modifica, non per pane tmux

Il collector del consumo per sessione enumera i transcript modificati nella
finestra recente, inclusi quelli dei subagent, e non parte dai pane tmux. È
questa singola scelta a rendere osservabile il consumo headless, che è oggi la
parte invisibile del problema.

L'origine diventa un fatto pubblicato: una sessione è attribuita a MAC quando il
suo identificativo corrisponde a un pane vivo, altrimenti è headless. I subagent
sono arrotolati sotto la sessione che li ha generati, ricavata dal percorso.

I quattro contatori di token restano separati e grezzi. L'utilizzo unificato
delle finestre è una composizione pesata che il client non può ricostruire;
pubblicare un peso sintetico produrrebbe numeri plausibili e falsi. La differenza
fra la curva globale e la somma attribuita è pubblicata come residuo, che è essa
stessa un'informazione.

### Il boundary non si allarga

Attraversano il confine soltanto identificativi di sessione, nome del progetto
come ultimo segmento del percorso, modello, origine, marcatore di subagent e
conteggi aggregati per intervallo. Non lo attraversano prompt, risposte, nomi di
strumenti, percorsi dei transcript, PID, working directory completa, credenziali
o header HTTP. Il backend continua a non vedere `/proc`, il socket Docker, le
home dei provider e le loro credenziali.

## Conseguenze e limiti

- La lettura dei transcript deve essere incrementale, con cursori per percorso,
  inode e offset. Esistono transcript di decine di megabyte e una rilettura
  integrale a ogni ciclo sarebbe insostenibile.
- Le partial di streaming ripetono lo stesso blocco di utilizzo su timestamp
  diversi. Senza deduplica per identificativo di richiesta il consumo risulterebbe
  moltiplicato: la deduplica è parte del contratto, non un'ottimizzazione.
- L'attribuzione è per sessione e per intervallo, mai al singolo turno. È
  sufficiente a rispondere alla domanda «chi ha consumato» e non richiede di
  pubblicare il contenuto dei turni.
- L'identificativo tmux è riusabile e non è la chiave: la chiave è
  l'identificativo di sessione del provider, stabile e già presente nei
  transcript.
- Il residuo non è zero e non deve esserlo. Consumo da altre macchine sullo stesso
  account, o da client non osservati, resta correttamente non attribuito.
- Un aggiornamento forzato consuma una quantità trascurabile di quota per
  misurarla. Il rate limit dedicato è ciò che impedisce che l'osservazione diventi
  essa stessa consumo rilevante.
- La sorgente strutturata delle percentuali vive fuori dal repository, negli
  script quote dell'utente. Il collector deve degradare al parsing testuale
  esistente quando lo script non offre la forma strutturata.

## Alternative scartate

- Tabella SQLite alimentata dal collector: due scrittori sullo stesso database
  con schema posseduto dal backend.
- Campionamento eseguito dal backend: introduce scheduler e stato nel container e
  contraddice il modello per cui i collector scrivono e il backend legge.
- Aggiornamento remoto periodico ad alta cadenza: rende la curva sempre veritiera
  al prezzo di centinaia di chiamate al giorno e di un uso molto più frequente
  delle credenziali.
- Attribuzione a partire dai pane tmux, riusando i collector esistenti: più
  semplice, ma cieca proprio sulla parte headless che motiva l'intervento.
- Peso sintetico dei token per stimare la percentuale per sessione: darebbe una
  precisione apparente non supportata dalla sorgente.
- Estensione del modulo host observability: contraddirebbe ADR 009 e il gate che
  ne ha approvato i confini.

## Rollback

Disabilitare i timer dei collector, rimuovere le voci di ambiente dei nuovi
percorsi e ricreare soltanto `web` e `backend`; `tmux-runtime` non va ricreato.
I due file JSONL possono essere eliminati senza conseguenze: nessun'altra
funzione vi dipende e lo snapshot istantaneo delle quote continua a funzionare
con il contratto invariato.
