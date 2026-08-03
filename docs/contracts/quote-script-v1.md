# Contratto script quota v1

Descrive cosa `deploy/rate-limit-collector.py` si aspetta da uno script quota
invocato per un provider (`claude`, `codex`). Lo script vive fuori da questo
repository: è un artefatto installato dal componente esterno che possiede lo
strato quote (backlog, voce BH-03), non una sorgente di questo prodotto. Qui è
documentato soltanto il contratto di formato che il collector applica, non
un'implementazione né una provenienza specifica — nessun nome di componente
esterno, nessun percorso assunto.

## Invocazione

Il collector invoca lo script al percorso configurato (`--claude-script`/
`--codex-script` del collector), mai una posizione assunta o versionata nel
repository. La prima invocazione aggiunge `--json`, opzionalmente preceduto
da `--fresh` quando il collector richiede un campione forzato invece che una
lettura di cache. Uno script che non riconosce `--json` può ignorarlo e
stampare comunque la propria forma testuale storica, oppure rifiutare
l'argomento con un codice di uscita diverso da zero: in quest'ultimo caso il
collector ripete l'invocazione senza alcun argomento (il `--fresh` non viene
ripetuto: l'eventuale prima esecuzione ha già aggiornato la cache che la
forma testuale rilegge).

## Forma strutturata (stdout, `--json`)

Un oggetto JSON singolo su stdout:

```json
{"updated_at":"2026-08-02T12:56:13.758Z","source":"cache","reached_type":null,
 "windows":[{"label":"5h","used_percent":91,"resets_at":1785679200,
             "detail":"reset 8/2/2026, 4:00:00 PM"}]}
```

- `windows` è una lista di oggetti; ogni oggetto privo di un campo `label`
  stringa viene scartato. `used_percent` è numerico o assente (il collector
  lo vincola a `0..100`); un valore assente pubblica una finestra senza
  percentuale, non uno zero. `resets_at` è un epoch intero non negativo,
  oppure assente quando lo script non conosce l'istante di reset della
  finestra. `detail` è testo libero opzionale.
- `updated_at` è l'istante che la sorgente dichiara come proprio; il
  collector lo interpreta come stringa e lo propaga così com'è.
- `source` è testo libero: il collector normalizza a `"fresh"` quando
  contiene la sottostringa `fresh` (case-insensitive), altrimenti a
  `"cache"`.
- `reached_type` è testo libero opzionale, o assente.
- Un payload senza `windows` come lista, o con lista vuota dopo il filtro sui
  singoli oggetti, non è considerato valido: il collector degrada alla forma
  testuale invece di pubblicare una riga strutturata vuota.

## Degradazione ammessa: forma testuale

Quando lo script non offre (o rifiuta) la forma strutturata, il collector
legge lo stesso output — o una seconda invocazione senza `--json` — come
testo riga per riga, con tre pattern:

```
Aggiornato: 2026-08-02T12:56:13.758Z [cache statusline]
5h: 91% (reset 8/2/2026, 4:00:00 PM)
7d: n/d
rate_limit_reached_type: 5h
```

- La riga `Aggiornato: <istante> [<sorgente>]` imposta `observed_at` e
  `source`; la parte fra parentesi quadre è opzionale, in sua assenza la
  sorgente resta `cache`.
- Ogni riga `<label>: <percentuale>%` oppure `<label>: n/d`, con `label` uno
  fra `5h`, `7d`, `primaria`, `secondaria`, seguita opzionalmente da un
  dettaglio fra parentesi, diventa una finestra. La forma testuale non porta
  mai un epoch di reset: `resets_at` è sempre assente in questo ramo, per
  costruzione — è proprio questa assenza strutturale, non un difetto del
  collector, che l'ADR 010 accetta come limite noto del fallback.
- La riga `rate_limit_reached_type: <valore>` imposta il campo omonimo.
- Righe che non corrispondono a nessuno dei tre pattern sono ignorate senza
  errore.

## Conseguenza pubblicata della degradazione

Quale delle due forme ha prodotto la riga è un fatto pubblicato sulla serie
storica, non solo una scelta interna del collector: ogni riga di
`provider-rate-limits-history.jsonl` porta `parse_mode`, `"structured"`
quando la forma JSON è stata letta con successo, `"text"` quando il
collector è degradato al parsing testuale. Le righe scritte prima
dell'introduzione di questo campo non lo portano: un consumatore deve
trattare la sua assenza come "non noto", mai come equivalente a `"text"`.
Questo è il meccanismo con cui il prodotto smette di degradare in silenzio
quando la sorgente strutturata smette di essere disponibile — vedi
`docs/contracts/budget-history-v1.md` (sezione "Serie storica della quota")
e la voce BH-03 del backlog.

## Cosa non è garantito

Il collector non versiona, non installa e non assume l'esistenza dello
script: un percorso configurato che non esiste o non è eseguibile produce una
riga `available: false` con un `error` troncato, mai un'eccezione propagata
né un `parse_mode` inventato (in questo caso il campo resta assente: nessun
parsing è stato tentato). Nessuna parte di questo contratto implica un nome,
una versione o un'origine specifica per lo script: qualunque eseguibile che
rispetti l'invocazione e almeno una delle due forme di output la soddisfa.
