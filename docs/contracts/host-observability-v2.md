# Contratto host observability v2

Il contratto v2 evolve la fotografia v1 senza cambiare endpoint,
autenticazione, rate limit o formato dell'export. Durante il rollout backend e
frontend accettano `schema_version` `1` e `2`; ogni altra versione e ogni campo
extra vengono rifiutati. Il modello Pydantic autorevole è l'unione discriminata
`HostObservabilitySnapshot` in
`backend/app/services/host_observability_contract.py`.

Il collector installato può continuare a produrre v1 fino alla fase che abilita
lo scoring v2. L'API restituisce sempre, senza wrapper, la versione ricevuta e
validata. `JSON.stringify(snapshot, null, 2)` resta quindi l'export esatto
dell'ultima risposta valida.

## Differenze rispetto a v1

Envelope, timestamp UTC, limite `duration_ms`, componenti, cardinalità e dati
ammessi restano quelli del v1. Le differenze sono limitate a queste evidenze:

- `memory.swap_io_sample` dichiara `available`; un campione disponibile porta
  `duration_ms`, `pages_in_delta` e `pages_out_delta`, tutti non negativi. Se
  non è disponibile i tre risultati sono `null`, mai zero sintetici;
- ogni gruppo processo aggiunge `policy_status`, uno fra `not_configured`,
  `within_limits` e `violated`. Le soglie private non attraversano il boundary;
- processi e gruppi portano `swap_bytes`, e il componente processi aggiunge
  `top_swap` e `swap_attributed_bytes`. Sono tutti campi opzionali: uno snapshot
  v2 prodotto da un collector precedente resta valido e vale `null`/`[]`, cioè
  "non accertato", mai zero. La classifica `top_swap` è ordinata per swap
  decrescente ed è indipendente da `top`, perché un processo quasi interamente
  paginato ha per definizione poca memoria residente;
- il listener rinomina il fatto locale in `bind_scope`, mantiene porta e
  processo sanitizzato, e aggiunge `external_reachability`, che in v2 può
  essere soltanto `not_assessed`;
- `listeners.items[].policy_status` distingue `not_configured`, `allowed` e
  `violated`. Nessuna policy può cancellare il bind osservato o attestare che
  una porta sia chiusa da un firewall;
- il componente Docker aggiunge `containers` (label e `memory_bytes` dei soli
  container con una label configurata), `unmapped_count` e
  `state_age_seconds`. Anche questi sono opzionali e assenti valgono "non
  accertato". `memory_bytes` è `null` per un container fermo, mai zero.

I reason v2 sono enumerati separatamente. Lo scoring contestuale può usare
`swap_sample_unavailable`, `swap_activity_high`, `swap_pressure_critical`,
`process_policy_count_high`, `process_policy_count_critical`,
`process_policy_rss_high` e `process_policy_rss_critical`. Il reason v1
`swap_used_critical` e i limiti globali `process_group_count_*` non sono validi
nel v2. Reason sconosciuti falliscono chiuso.

## Scoring contestuale

Il collector emette v2 quando legge una configurazione v2; una configurazione
legacy continua a produrre v1 con la semantica storica. Nel v2:

- la percentuale di swap occupata oltre soglia produce al massimo `warning`
  con `swap_used_high`; non può da sola produrre `critical`;
- il delta di attività è la somma non negativa di `pswpin` e `pswpout` nel
  campione. Il livello `critical` richiede contemporaneamente memoria
  disponibile alla soglia critical o sotto e delta alla soglia critical o
  sopra, con `memory_available_critical` e `swap_pressure_critical`;
- memoria sotto la soglia warning, swap occupata o attività oltre la rispettiva
  soglia warning restano evidenze warning. Un campione mancante, parziale,
  resettato o fuori durata è `available=false`, con risultati `null` e
  `swap_sample_unavailable`, mai attività zero sintetica;
- i gruppi senza policy restano visibili e `not_configured`, senza contribuire
  alla severità. Le policy configurate valutano count e RSS aggregato alle
  soglie inclusive; warning o critical rendono il gruppo `violated`;
- un listener senza policy è warning, incluso un bind wildcard. Una porta
  configurata su uno scope non consentito è una violazione locale critical;
  questo non cambia `external_reachability=not_assessed`. Ownership mancante,
  lettura parziale e troncamento producono evidenza partial/unknown e mai, da
  soli, critical.

## Attribuzione della swap

`swap_bytes` per processo viene da `VmSwap` in `/proc/<pid>/status`, letto solo
sotto configurazione v2. Un file non leggibile lascia `null`; un processo senza
spazio di indirizzi (thread di kernel) non ha `VmSwap` e vale 0 accertato. Un
gruppo somma i soli membri letti e resta `null` se nessun membro era leggibile.

`swap_attributed_bytes` è la somma dei valori accertati e va confrontata con
`memory.swap_used_bytes`: la differenza appartiene a processi terminati o non
leggibili e non è attribuibile. Il collector non la ripartisce e la vista non la
presenta come se lo fosse.

## Evidenza Docker fuori banda

Con `docker.state_file` configurato l'evidenza Docker arriva dal file scritto
dalla unit `mobile-agent-console-docker-state`, non da un subprocess del
collector: il perché è in ADR 011. È l'unico componente della fotografia che non
è istantaneo, e la sua età viaggia in `state_age_seconds`.

File assente, scaduto oltre `docker.max_age_seconds`, malformato, con
`schema_version` diverso da 1, con timestamp non UTC-aware o con un nome di
container non sanificato producono `available=false` con reason esplicito —
`docker_unavailable`, `docker_state_stale` o `docker_output_invalid` — e mai un
elenco vuoto presentato come "nessun problema". `docker_state_stale` non è
valido nel v1, dove la modalità a file non esiste.

In v2 solo i container con una label configurata concorrono alla severità; gli
altri restano conteggiati in `unmapped_count` e, se problematici, in
`unmapped_problematic_count`. È la stessa regola dei gruppi di processi senza
policy: ciò che non è sotto sorveglianza è visibile ma non giudicato. Nel v1 la
semantica storica resta invariata e ogni container problematico pesa.

## Coerenza del campione swap

`swap_io_sample.available=true` richiede tutti e tre i risultati. Con
`available=false` tutti devono essere `null`. La durata ammessa dal contratto
output è `1..1000` ms; la configurazione privata applica il limite più stretto
`10..500` ms per preservare il budget one-shot. La disponibilità del campione
non implica da sola uno stato positivo o negativo: stato e reason sono sempre
espliciti nel componente memoria.

## Configurazione privata compatibile

Il collector legge sia la configurazione legacy `schema_version: 1` sia la v2
esplicita. Le forme non possono essere mescolate: campi sconosciuti o propri
dell'altra versione causano errore.

La v1 conserva `expected_tcp_listeners`, `process_labels`, soglie globali dei
gruppi e soglie swap storiche. La v2 usa:

- `swap_io_sample`: `duration_ms`, `warning_pages_delta` e
  `critical_pages_delta`; warning non può superare critical;
- `tcp_listener_policies`: massimo 128 record univoci con `port` e
  `allowed_scopes`; non esistono campi firewall, raggiungibilità o rete esterna;
- `docker.state_file`: path assoluto del file di stato, e `max_age_seconds`
  fra 1 e 3600 (default 120). Entrambi esistono solo nella v2; il periodo del
  timer deve stare abbondantemente dentro `max_age_seconds`, così un giro perso
  non fa lampeggiare la dashboard;
- `process_policies`: massimo 128 chiavi `comm` sanificate. Ogni policy può
  avere una label e soglie warning/critical per `count` e/o `rss_bytes`, ma deve
  definire almeno un limite. Una soglia warning non può superare la critical.

I count sono limitati a `1..4096`, gli RSS a `1..2^63-1`; durata, delta, porte,
scope, label, path, cardinalità, dimensione e proprietà `0600` restano validati
in modo stretto. Il file di esempio usa esclusivamente nomi, porte e path
fittizi. La configurazione non può dichiarare firewall, eseguire sonde, fornire
credenziali o aggiungere dipendenze di rete.

## Privacy e failure mode

Restano vietati hostname, username, cmdline, environment, working directory,
IP grezzi, inode, identificativi e nomi reali Docker non mappati, path e soglie
private. Backend e frontend non aggiungono polling, persistenza o log del
payload. Payload misti v1/v2, versioni future, campioni incoerenti, limiti fuori
range, reason sconosciuti e campi extra producono risposta invalida fail-closed.
