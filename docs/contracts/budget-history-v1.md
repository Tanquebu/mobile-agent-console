# Contratto storico budget v1

Copre i due file JSONL prodotti dai collector host-side e letti in sola lettura
dal backend:

- `provider-rate-limits-history.jsonl` — serie storica della quota per-account;
- `session-usage-history.jsonl` — consumo di token attribuito per sessione.

Lo snapshot istantaneo `provider-rate-limits.json` resta separato dallo storico
ma condivide ora `windows[].resets_at`: l'estensione compatibile ripristina nel
pannello la data di reset che il passaggio alla sorgente strutturata aveva
involontariamente nascosto. Il campo può mancare negli snapshot precedenti e
viene allora normalizzato a `null`. Il suo contratto API è in
`docs/api-contract.md`; i modelli Pydantic autorevoli dello storico sono in
`backend/app/services/rate_limit_history_service.py` e
`backend/app/services/session_usage_service.py`.

## Forma comune

Ogni file è una sequenza di oggetti JSON, uno per riga, in ordine di scrittura
non decrescente. L'append è atomico per riga; il backend legge la coda del file
entro un tetto di byte e scarta le righe non decodificabili o non valide senza
fallire, perché una riga troncata da una rotazione concorrente è un evento
atteso e non un errore. I file hanno permessi `0600` e vivono nella directory
`0700` già usata dagli altri file di stato.

I timestamp sono ISO 8601 UTC. Le percentuali sono in `0..100`. I conteggi sono
interi non negativi. Nessun campo può contenere percorsi assoluti, contenuti di
conversazione o identificativi di processo.

## Serie storica della quota

Una riga per provider e per campione osservato.

```json
{"sampled_at":"2026-08-02T09:34:50Z","provider":"claude","source":"cache",
 "observed_at":"2026-08-02T09:34:41Z","stale":false,"parse_mode":"structured",
 "windows":[{"label":"5h","used_percent":58.0,"resets_at":1785679200},
            {"label":"7d","used_percent":5.0,"resets_at":1786266000}]}
```

- `sampled_at` è l'istante in cui il collector ha eseguito la rilevazione;
  `observed_at` è l'istante a cui la sorgente dichiara che il dato si riferisce.
  I due valori sono distinti proprio perché possono divergere.
- `source` è `cache` oppure `fresh`. È `fresh` soltanto quando la rilevazione ha
  interrogato il provider in quel momento.
- `stale` è vero quando `sampled_at - observed_at` supera la soglia configurata.
  Un campione stantio è un campione valido che descrive un'osservazione vecchia:
  il consumatore deve rappresentarlo come intervallo non osservato e non deve
  interpolarlo.
- `resets_at` è l'epoch di reset della finestra, oppure `null`. Serve a
  segmentare la serie: la finestra di cinque ore è scorrevole e senza
  segmentazione la sua discesa fisiologica si legge erroneamente come un calo di
  consumo.
- `label` è l'etichetta di finestra pubblicata dal provider (`5h`, `7d`,
  `primaria`, `secondaria`). `used_percent` è `null` quando la sorgente non ha
  fornito un valore.
- `parse_mode` dichiara quale forma di output dello script quote ha prodotto
  la riga: `"structured"` quando il collector ha letto la forma `--json`
  descritta in `docs/contracts/quote-script-v1.md`, `"text"` quando è
  degradato al parsing testuale storico (fallback ammesso da ADR 010, ma non
  più silenzioso). `null` copre sia le righe scritte prima dell'introduzione
  di questo campo sia i casi in cui nessun parsing è stato tentato (script
  non eseguibile): in entrambi va letto come "non noto", mai come equivalente
  a `"text"`. Una sorgente in modalità testuale non porta mai `resets_at`
  (vedi sopra): il consumatore usa `parse_mode` per segnalarlo come fatto
  invece di dedurlo dall'assenza dell'epoch.

Un provider non disponibile produce una riga con `windows` vuoto e `error`
troncato, senza mai riportare l'ultimo valore noto come se fosse attuale.

### Deduplica e ritenzione

Il collector appende soltanto se `observed_at`, l'insieme delle percentuali o
`parse_mode` differiscono dall'ultima riga dello stesso provider: una
transizione da forma strutturata a testuale (o viceversa) è un fatto nuovo da
pubblicare anche quando osservazione e percentuali restano identiche, non un
duplicato da scartare. Una sorgente ferma non produce righe: l'assenza di
campioni è essa stessa l'informazione che nulla è stato osservato. La
rotazione riscrive il file conservando la coda entro la ritenzione
configurata quando la dimensione supera la soglia.

## Consumo attribuito per sessione

Una riga per combinazione di intervallo, sessione, modello e natura subagent.
Gli intervalli sono allineati a cinque minuti.

```json
{"bucket_start":"2026-08-02T09:30:00Z","provider":"claude",
 "session_uuid":"5b84b3fa-a26f-4642-abf3-851fc35abf3f","tmux_session_id":"162",
 "origin":"mac","project":"mobile-agent-console","model":"claude-opus-5",
 "is_subagent":false,"turns":7,
 "input_tokens":14,"cache_creation_input_tokens":103047,
 "cache_read_input_tokens":89075,"output_tokens":10514}
```

- `session_uuid` è l'identificativo di sessione del provider ed è la chiave di
  attribuzione. L'identificativo di sessione tmux non è una chiave: tmux può
  riassegnarlo a una sessione futura scollegata.
- `tmux_session_id` è presente solo quando la sessione è mappata a un pane vivo,
  ed è l'aggancio verso il resto dell'API.
- `origin` è `mac` quando esiste quella mappatura, altrimenti `headless`. Le
  esecuzioni senza pane consumano la stessa quota per-account e devono restare
  visibili.
- `project` è l'ultimo segmento del percorso di progetto, mai il percorso
  completo.
- `is_subagent` distingue i transcript dei subagent. Sono attribuiti al
  `session_uuid` della sessione che li ha generati, così il consumo indotto dal
  fan-out risulta sotto la sessione responsabile invece di sparire.
- `turns` è il numero di risposte del modello deduplicate nell'intervallo.
- I quattro contatori di token restano separati e grezzi. Non esiste un campo
  che stimi la percentuale di quota consumata dalla sessione: l'utilizzo
  unificato è una composizione pesata non ricostruibile da questi valori, e
  pubblicarne una stima darebbe una precisione apparente non supportata dalla
  sorgente.

### Deduplica delle risposte

Le partial di streaming ripetono lo stesso blocco di utilizzo su timestamp
diversi. Le risposte sono deduplicate per identificativo di richiesta tenendo
l'ultima occorrenza. Senza questa regola il consumo risulterebbe moltiplicato
per il numero di partial, quindi la deduplica è parte del contratto.

### Lettura incrementale

Il collector mantiene fuori dal workspace un file di cursori per percorso,
inode e offset, e legge soltanto i byte aggiunti dal ciclo precedente. Un inode
diverso o un file rimpicciolito azzerano il cursore per quel percorso. Il file
dei cursori è stato interno del collector e non attraversa il boundary.

## Residuo

La somma del consumo attribuito in un intervallo non copre necessariamente la
crescita della quota nello stesso intervallo. La differenza è pubblicata come
residuo e va rappresentata come tale: consumo proveniente da altre macchine
sullo stesso account, o da client non osservati, è correttamente non
attribuibile. Un residuo diverso da zero non è un difetto del collector.

## Privacy e failure mode

Non attraversano il boundary prompt, risposte, ragionamenti, nomi e argomenti
degli strumenti, percorsi dei transcript, PID, working directory completa,
hostname, username, credenziali e header HTTP.

Righe malformate, campi extra, versioni non riconosciute, timestamp non UTC,
percentuali fuori intervallo e conteggi negativi vengono scartati riga per riga.
L'assenza dei file, un file vuoto o interamente invalido producono una risposta
vuota, mai un errore del backend e mai un valore inventato.
