# Sonda Codex per reset anticipati della quota

## Stato

Analisi e piano approvati per il passaggio a una nuova sessione di sviluppo.
Questo documento non implementa la sonda e non modifica lo scheduling corrente.

La funzionalità appartiene al boundary host-side che possiede credenziali,
telemetria e decisioni dell'orchestratore esterno. Il repository pubblico non
deve contenere nomi, URL, token, host, path o altri dettagli del deployment
privato. Prima di implementare, individuare il componente proprietario senza
codificarne qui l'identità.

## Obiettivo

Evitare che Codex resti escluso dal routing o che task in
`paused_provider` rimangano sospesi sulla base di una previsione
`resets_at` ormai superata dai fatti.

La soluzione deve generare il minimo traffico possibile verso il provider:
una sola valutazione giornaliera intorno alle 04:00 locali e una richiesta
fresh soltanto quando la cache indica quota fuori soglia e non esiste una
misura recente.

## Evidenza osservata

Gli eventi strutturati `event_msg/token_count` dei transcript Codex hanno
mostrato questa sequenza per la stessa identità locale, lo stesso piano, lo
stesso `limit_id`, lo stesso modello e la stessa versione CLI:

| Osservazione locale | Uso | `window_minutes` | Reset comunicato |
|---|---:|---:|---|
| 10/08/2026 19:27 | 90% | 10080 | 15/08/2026 22:45 |
| 12/08/2026 09:10 | 0% | 10080 | 19/08/2026 09:10 |
| 13/08/2026 06:20 | 0% | 10080 | 20/08/2026 06:20 |
| 15/08/2026 02:45 | 95% | 10080 | 20/08/2026 06:20 |

Il provider ha quindi azzerato o sostituito la finestra prima della scadenza
precedentemente comunicata. Il client non dispone di un contratto pubblico
che garantisca l'immutabilità di `resets_at`: quel campo va trattato come una
previsione revocabile, non come un lock temporale autorevole.

L'account locale non risultava cambiato e gli eventi coinvolti riportavano
`plan_type=plus`, `limit_id=codex`, modello `gpt-5.6-sol` e CLI `0.147.0`.
Non è quindi emersa una spiegazione client-side basata su cambio account,
modello o versione. La causa precisa del ricalcolo resta interna al provider.

## Difetto locale confermato

Quando un task viene sospeso, l'orchestratore salva
`next_attempt_at = resets_at + margine`. Nei cicli successivi controlla prima
quel timestamp e, se è ancora futuro, evita di leggere la nuova telemetria.

Questo comportamento ha già prodotto il caso da prevenire: una misura fresca
ha mostrato 0% prima della previsione memorizzata, mentre task precedenti sono
rimasti sospesi. Anche in assenza di task sospesi il rischio resta: una cache
vecchia sopra soglia può continuare a dichiarare Codex indisponibile e
orientare il routing verso altri provider.

La presenza di task `paused_provider` **non deve quindi essere una
precondizione della sonda**. I task sono consumatori dello stato del provider,
non la ragione per mantenerlo corretto.

## Vincoli e decisioni confermate

- Esecuzione giornaliera intorno alle **04:00 Europe/Rome**, prima dei flussi
  ricorrenti del mattino.
- Inattività richiesta: nessun evento Codex con un payload `rate_limits`
  valido osservato nei **60 minuti precedenti**.
- Il controllo riguarda l'età dell'ultima misura valida, non l'esistenza di un
  file sessione, di una sessione tmux o di un processo Codex.
- La sonda parte soltanto se la fotografia valida più recente indica budget
  fuori soglia.
- Non è richiesta la presenza di task sospesi.
- Una sola sonda automatica al giorno, con lock contro esecuzioni concorrenti.
- L'impatto già osservato di una richiesta fresh è inferiore a **3 punti
  percentuali**. È un dato empirico utile al dimensionamento, non una garanzia
  futura del provider.
- Timeout, output e frequenza devono rimanere limitati.
- `resets_at` non deve impedire una nuova osservazione: è un suggerimento di
  scheduling, non una fonte di verità immutabile.

## Definizione della soglia effettiva

La decisione non deve introdurre una nuova percentuale hard-coded.

- Se non esistono task Codex sospesi, usare la soglia canonica con cui lo stato
  dell'orchestratore dichiara Codex disponibile o indisponibile.
- Se esistono task Codex sospesi, considerare anche le rispettive soglie di
  classe o esplicite. La soglia effettiva del gate è la più restrittiva fra la
  soglia canonica e quelle dei task sospesi.

Questo evita due errori opposti: sondare quando Codex è già utilizzabile per
il routing generale oppure non sondare un task pesante che resta correttamente
bloccato a una soglia inferiore a quella generale.

## Flusso proposto

```text
timer giornaliero, circa 04:00 Europe/Rome
  |
  +-- acquisisci lock non bloccante
  |     +-- lock occupato -> esci con skipped_locked
  |
  +-- leggi l'ultimo snapshot Codex valido
  |     +-- assente/malformato -> esci senza inventare disponibilità
  |
  +-- calcola la soglia effettiva
  |
  +-- nessuna finestra >= soglia -> esci con skipped_budget_available
  |
  +-- ultimo rate_limits valido < 60 minuti -> esci con skipped_recent_sample
  |
  +-- esegui una sonda fresh Codex minima
        |
        +-- quota al 100%, errore, timeout o payload invalido
        |     -> conserva lo snapshot precedente
        |     -> non mutare i task
        |     -> termina e attende l'intero process group della sonda
        |     -> registra probe_failed con dettaglio sanitizzato
        |
        +-- payload valido
              -> persisti atomicamente lo snapshot canonico
              -> appendi il campione allo storico con source=fresh
              -> riconcilia la disponibilità del provider
              -> riconcilia tutti gli eventuali task sospesi
```

### Riconciliazione dopo una sonda valida

Per ogni task Codex in `paused_provider`:

- se nessuna finestra corrente supera la soglia specifica del task, impostare
  `status=new` e cancellare `pause_reason` e `next_attempt_at`;
- se la quota è ancora fuori soglia e il reset corrente è noto, aggiornare
  `next_attempt_at` a `resets_at + margine`;
- se la quota è ancora fuori soglia ma il reset è ignoto, mantenere la pausa
  senza inventare una data;
- una riconciliazione parziale o fallita non deve marcare il provider come
  disponibile né riattivare task alla cieca.

L'aggiornamento dello snapshot deve avvenire anche quando non esistono task
sospesi, così routing, fallback e dashboard partono dallo stesso stato
canonico.

## Sonda fresh reale

Lo script Codex attualmente installato legge l'ultimo evento persistito nei
transcript. Accetta o ignora argomenti non riconosciuti e, allo stato
osservato, `--fresh` non produce una richiesta remota. Il collector one-shot
può quindi dichiarare un percorso fresh senza aver aggiornato Codex.

L'implementazione deve prima rendere questo comportamento esplicito e
testabile. Non basta invocare il collector esistente con `--fresh`.

La CLI installata non espone un comando quota-only documentato. La soluzione
minima prevista è una singola esecuzione non interattiva che produca eventi
JSONL:

- modello esplicito uguale a quello governato dalla soglia;
- modalità `--ephemeral`, per non conservare una sessione;
- output `--json`, da cui accettare soltanto eventi strutturati
  `payload.rate_limits`;
- prompt costante e minimo;
- sandbox read-only, strumenti e rete del modello non necessari;
- directory di lavoro costante e non sensibile;
- timeout rigido, processo terminato e atteso in caso di scadenza;
- limite di byte applicato durante la lettura di stdout/stderr;
- argv fisso e `shell=False` nel chiamante Python;
- nessun prompt, risposta o output grezzo nei log o nei file condivisi.

Poiché `--ephemeral` non crea un transcript persistente, il chiamante deve
estrarre la misura dallo stdout della sonda e aggiornare esplicitamente lo
snapshot canonico. Non deve aspettarsi che il collector periodico la scopra
in seguito sul filesystem.

La sessione incaricata dell'implementazione deve verificare con la CLI
effettivamente installata che un evento `rate_limits` venga emesso sia in caso
di capacità disponibile sia in caso di limite raggiunto. Se uno dei due casi
non produce telemetria utilizzabile, il ramo deve fallire chiuso e conservare
la cache precedente.

### Chiusura garantita al 100% della quota

Il caso in cui Codex abbia davvero raggiunto il 100% è un esito normale della
sonda, non un motivo per lasciare un processo in attesa. La CLI potrebbe
rispondere con errore, non produrre alcun evento utile oppure restare in attesa
di una risposta del provider. Tutti e tre i casi devono terminare entro un
tempo limitato.

Il runner non deve affidarsi soltanto al timeout di una `subprocess.run`: deve
avviare Codex in un process group dedicato e applicare questa sequenza in un
blocco `finally`:

1. alla scadenza inviare `SIGTERM` all'intero process group;
2. attendere un breve grace period;
3. se esistono ancora processi, inviare `SIGKILL` all'intero gruppo;
4. eseguire sempre `wait`/reap del processo padre;
5. chiudere pipe e file descriptor e rilasciare il lock anche su eccezione.

Stdout e stderr devono essere drenati con un limite applicato mentre il
processo gira, così un figlio non può rimanere bloccato su una pipe piena. La
user unit deve aggiungere una seconda barriera indipendente con
`RuntimeMaxSec`, `TimeoutStopSec` breve e `KillMode=control-group`. Non sono
previsti retry nella stessa esecuzione: dopo timeout o quota piena il prossimo
tentativo automatico resta quello del giorno successivo.

Se prima del timeout arriva un evento `rate_limits` valido che conferma il
100%, il runner può terminare normalmente e aggiornare la cache con quella
misura. Se non arriva alcuna misura valida, conserva il budget precedente e
registra soltanto `probe_failed=timeout` o un codice equivalente; non crea una
sessione persistente grazie a `--ephemeral` e non modifica i task.

## Proprietà di sicurezza

- La sonda vive sull'host; credenziali e transcript non entrano nel backend o
  nelle immagini container.
- I file di stato e storico restano `0600` e vengono sostituiti atomicamente.
- Nel boundary condiviso passano soltanto provider, percentuali, finestre,
  reset, timestamp, provenienza ed errori sanitizzati.
- Non serializzare token, header, prompt, risposta, cwd, path dei transcript o
  configurazione privata.
- Il timer deve essere una user unit senza privilegi, con hardening coerente
  con il collector fresh esistente e accesso di rete limitato alla necessità
  della sonda.
- Il lock deve stare in un path runtime privato e non nel repository.
- Nessun endpoint browser deve diventare necessario per il funzionamento del
  timer.
- Un errore della sonda non deve modificare lo stato dei task né trasformare
  un dato sconosciuto in disponibilità.

## Osservabilità minima

Registrare soltanto eventi tipizzati e privi di contenuto:

- `skipped_locked`;
- `skipped_budget_available`;
- `skipped_recent_sample`;
- `probe_started`;
- `probe_failed` con codice stabile e dettaglio troncato/sanitizzato;
- `probe_still_exhausted`;
- `probe_provider_available`;
- `probe_tasks_resumed` con solo conteggio;
- `probe_tasks_rescheduled` con solo conteggio.

Per il campione storico usare `source=fresh` e conservare l'`observed_at`
restituito dalla sonda. Non falsare l'istante di osservazione con quello di
scrittura.

## Piano di implementazione

### 1. Isolare le funzioni pure

Estrarre o aggiungere funzioni testabili per:

- selezionare l'ultima misura Codex valida;
- calcolare età e soglia effettiva;
- decidere `skip` oppure `probe`;
- estrarre `rate_limits` da JSONL con limite di input;
- confrontare vecchia e nuova finestra;
- produrre le mutazioni di riconciliazione senza applicarle.

### 2. Implementare il runner della sonda

Creare un solo entrypoint host-side. Deve supportare almeno una modalità
`--dry-run` che esegua tutti i gate ma non contatti Codex e non muti task o
file. La modalità reale deve eseguire al massimo una richiesta e pubblicare la
misura soltanto dopo validazione completa.

### 3. Integrare lo stato canonico

Evitare cache concorrenti non sincronizzate. La misura fresh deve alimentare
la stessa sorgente letta dalle decisioni di routing e dallo stato sanitizzato
raccolto dalla console. Se restano più proiezioni su file, aggiornarle da una
singola misura validata e documentarne l'ordine atomico e il comportamento in
caso di errore intermedio.

### 4. Riconciliare i task

Correggere il percorso che oggi restituisce anticipatamente quando
`next_attempt_at` è futuro. La sonda giornaliera deve poter applicare una
misura più recente del `capacity_snapshot` del task senza attendere la vecchia
data. Il normale ciclo frequente può conservare il gate temporale per evitare
sonde ripetute.

### 5. Aggiungere timer e lock

Usare una user timer unit con calendario `04:00` in timezone locale e una
oneshot dedicata. Verificare sovrapposizioni con i timer reali. Il timeout
della unit deve essere poco superiore a quello del subprocess e il lock deve
rendere innocui avvii doppi o `Persistent=true` dopo un boot tardivo.

### 6. Aggiornare contratti e documentazione

Se cambia il comportamento dello script `--fresh`, aggiornare il contratto
quote e il gate dello storico. Se la modifica rende visibile una nuova
funzionalità nella console, aggiornare `LATEST_RELEASE` nello stesso round,
come richiesto dalle regole del repository.

## Verifiche automatiche richieste

### Gate decisionale

- snapshot sotto soglia: nessuna sonda;
- snapshot esattamente alla soglia: sonda ammessa;
- snapshot sopra soglia ma più recente di 60 minuti: nessuna sonda;
- boundary temporale a 59:59 e 60:00;
- nessun task sospeso: la sonda resta ammessa;
- task con soglia più restrittiva della soglia canonica;
- snapshot assente, malformato, senza finestre o senza percentuale;
- doppia invocazione concorrente: una sola acquisisce il lock;
- seconda invocazione nello stesso giorno: nessuna seconda richiesta.

### Parsing e processo

- JSONL con eventi non pertinenti prima/dopo `rate_limits`;
- più misure: selezione dell'ultima valida;
- percentuale e reset fuori dominio;
- output oltre limite;
- timeout con terminate/kill/reap;
- quota al 100% con CLI che non produce output e non termina: scadenza del
  timeout, `SIGTERM`, eventuale `SIGKILL`, reap e nessun processo figlio
  residuo;
- pipe stdout/stderr satura: nessun deadlock e limite di byte rispettato;
- eccezione durante parsing o persistenza: lock e file descriptor sempre
  rilasciati;
- exit non-zero con e senza telemetria valida;
- nessuna esecuzione tramite shell;
- nessuna persistenza del prompt o della risposta.

### Riconciliazione

- provider tornato sotto soglia senza task sospesi: snapshot aggiornato;
- task sotto la propria soglia: ritorno a `new` e pulizia campi pausa;
- task ancora sopra soglia con reset cambiato: nuova pianificazione;
- reset ignoto: pausa senza data inventata;
- errore di persistenza o aggiornamento remoto: nessuna disponibilità falsa;
- più task dello stesso provider aggiornati dalla stessa misura, senza una
  sonda per task.

### Regressione del prodotto pubblico

Se vengono modificati file di questo repository, eseguire almeno:

```bash
docker compose run --rm backend-test
docker compose run --rm frontend-build
docker compose config --quiet
```

Aggiungere i test mirati del collector e delle unit systemd eventualmente
toccati. Nessun test deve effettuare richieste reali al provider.

## Deploy e validazione reale

1. Verificare che il working tree non contenga modifiche altrui da includere.
2. Costruire da un export isolato del commit se il tree non è pulito, secondo
   le regole di questo repository.
3. Installare entrypoint e user unit dal repository che ne è proprietario.
4. Eseguire `systemd-analyze --user verify` sulle unit.
5. Eseguire la modalità `--dry-run` con casi sotto/sopra soglia e misura
   recente/stantia.
6. Autorizzare una sola sonda reale controllata, verificando evento
   `rate_limits`, consumo entro l'ordine di grandezza già osservato e assenza
   di output sensibile nei log.
7. Simulare un task sospeso con vecchio `next_attempt_at` e una misura fresh
   sotto soglia; verificare la riattivazione automatica.
8. Verificare anche il caso senza task sospesi: lo stato provider deve passare
   a disponibile ed essere visibile alla successiva raccolta read-only.
9. Abilitare il timer e verificare il prossimo trigger intorno alle 04:00.
10. Se il round coinvolge servizi della console, ricreare soltanto i servizi
    stateless interessati e preservare sempre `tmux-runtime`.
11. Aggiornare `LATEST_RELEASE` soltanto dopo rilascio e validazione effettivi,
    quindi includerlo nello stesso commit funzionale.

## Criteri di accettazione

- Una cache Codex sopra soglia e vecchia di almeno un'ora genera al massimo
  una sonda giornaliera, anche con zero task sospesi.
- Una misura valida più recente di un'ora impedisce la sonda.
- Una cache sotto soglia impedisce la sonda.
- Una nuova misura sotto soglia aggiorna immediatamente la disponibilità del
  provider e riattiva gli eventuali task compatibili.
- Una nuova misura ancora sopra soglia aggiorna le previsioni dei task senza
  duplicare richieste.
- Errori, timeout e payload invalidi preservano snapshot e task precedenti.
- Al 100% della quota la sonda termina entro il limite configurato; dopo la
  oneshot non restano processi Codex o figli della sonda.
- Il backend resta privo di credenziali e accesso ai transcript.
- Nessun segreto, prompt, risposta o dettaglio privato entra nei file
  versionati, condivisi o di log.
- Il timer non tocca né ricrea `tmux-runtime`.

## Rollback

Disabilitare e fermare soltanto il nuovo timer/servizio host-side. Ripristinare
l'entrypoint precedente e lasciare intatti snapshot e storico validi: la
raccolta cache-only ogni minuto continua a funzionare. Non ricreare
`tmux-runtime`. Se sono stati ricreati servizi stateless della console,
eseguire il rollback dalla directory stabile del repository.

## Fuori scope

- Spiegare con certezza il motivo interno per cui il provider sostituisce una
  finestra prima di `resets_at`.
- Aumentare la frequenza della sonda oltre una volta al giorno.
- Esporre credenziali o transcript al backend.
- Rendere `resets_at` nuovamente un blocco temporale autorevole.
- Introdurre polling browser o un endpoint pubblico non necessario.
- Modificare soglie di capacità esistenti senza una decisione separata.
