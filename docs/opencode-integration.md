# Valutazione dell'integrazione OpenCode

**Stato:** roadmap approvata dall'utente il 3 agosto 2026 e presa in carico
dalla coda in `docs/backlog.md` (sezione "Integrazione OpenCode",
`GATE-OC-00` `PASSED`). L'autorizzazione copre il percorso incrementale fino
a `OC-03`; `OC-04` (adapter sull'API nativa) e `OC-05` (runtime Docker)
restano dietro gate propri e non sono autorizzati.

**Data della valutazione:** 3 agosto 2026.

## Obiettivo

Valutare se [OpenCode](https://opencode.ai/) possa essere eseguito, osservato
e controllato da Mobile Agent Console senza indebolire gli invarianti di
sicurezza e senza trasformare il core agent-agnostic in un'integrazione
strettamente dipendente da un singolo agente.

L'approvazione non è un permesso generico di toccare runtime e deployment:
autorizza le fasi nell'ordine in cui sono scritte qui, ciascuna dietro il
proprio gate di uscita. In particolare nessuna fase deve interferire con i
round funzionali già programmati né causare la ricreazione di `tmux-runtime`
e la perdita delle sessioni attive — l'unica fase che lo richiederebbe è
`OC-05`, che per questo resta non autorizzata e vincolata a una finestra di
manutenzione esplicita.

## Sintesi

OpenCode è integrabile. La prima integrazione dovrebbe essere un nuovo profilo
TUI eseguito dentro una sessione tmux, allo stesso livello di Codex, Claude e
Antigravity. Questo percorso riusa il trasporto, la sicurezza e la semantica
già presenti:

- tmux resta autorevole per le sessioni vive;
- il browser invia soltanto operazioni tipizzate;
- il comando di avvio è una costante server-side;
- testo libero, multilinea e riferimenti agli allegati passano attraverso
  `load-buffer -` e `paste-buffer`;
- Enter e gli altri tasti restano operazioni separate;
- output e ANSI continuano a essere catturati dal pane tmux.

L'API HTTP nativa di OpenCode è interessante per una futura integrazione
strutturata di stati, messaggi e richieste di autorizzazione, ma non è il punto
di partenza consigliato: introdurrebbe un secondo runtime di sessione accanto
a tmux e richiederebbe un nuovo boundary di rete, autenticazione e ciclo di
vita.

## Compatibilità con l'architettura corrente

### Aspetti già compatibili

Il gateway tmux risolve i profili tramite argv controllati in
`backend/app/services/tmux_service.py`. OpenCode avvia la propria TUI con il
comando `opencode`, quindi il profilo minimo sarebbe concettualmente:

```python
"opencode": ("bash", "-l", "-c", "exec opencode")
```

Il comando non proverrebbe mai dal client. La directory continuerebbe a essere
risolta con `Path.resolve()` e verificata contro `MAC_ALLOWED_ROOTS` prima
della creazione della sessione.

Il modello di input esistente è adatto a una TUI conversazionale. Non è
necessario dare al browser accesso a una shell né trasformare l'input in un
comando remoto arbitrario. Anche gli allegati attuali sono compatibili: Mobile
Agent Console prepara un percorso controllato e inserisce nel prompt soltanto
il riferimento al file.

OpenCode supporta ufficialmente:

- TUI interattiva avviata con `opencode`;
- ripresa dell'ultima sessione con `--continue`;
- ripresa per identificatore con `--session`;
- elenco delle sessioni tramite `opencode session list`;
- esecuzione non interattiva tramite `opencode run`;
- server headless e stream di eventi per integrazioni programmatiche.

Riferimenti ufficiali:

- [CLI OpenCode](https://opencode.ai/docs/it/cli/)
- [TUI OpenCode](https://opencode.ai/docs/tui/)
- [Server OpenCode](https://opencode.ai/docs/server/)

### Superfici da estendere

Il profilo è oggi un'unione chiusa `shell | codex | claude | antigravity` in
più livelli. Un'integrazione completa deve aggiornare in modo coerente:

- `PROFILE_ARGV` e `RESUME_PROFILE_ARGV` nel gateway tmux;
- gli schemi Pydantic di creazione, archivio e snapshot;
- `ArchiveService` e `SnapshotService`;
- il riconoscimento del profilo dal comando corrente;
- il selettore di creazione nel frontend e i relativi tipi TypeScript;
- fake e test backend/frontend;
- documentazione architetturale, requisiti e release note soltanto dopo un
  rilascio realmente verificato.

L'aggiunta non deve trasformarsi in un profilo configurabile dal client. Il
comando OpenCode deve restare una costante server-side, come gli altri profili.

## Resume, archivio e snapshot

OpenCode conserva autenticazione e dati applicativi sul filesystem. Su Linux i
dati risiedono normalmente sotto `~/.local/share/opencode/`, mentre la
configurazione globale è sotto `~/.config/opencode/`.

Riferimenti ufficiali:

- [Storage e troubleshooting](https://opencode.ai/docs/troubleshooting/)
- [Configurazione OpenCode](https://opencode.ai/v2/docs/config)

Sono possibili tre strategie di ripristino.

### A. `opencode --continue`

È la soluzione minima, ma può selezionare una conversazione diversa da quella
associata alla sessione tmux archiviata quando nello stesso progetto esistono
più sessioni OpenCode. È accettabile per uno spike, non è la semantica più
affidabile per archivio e restore definitivi.

### B. Avvio della TUI e selettore delle sessioni

Il restore può avviare `opencode` e lasciare all'utente la scelta tramite il
selettore nativo `/sessions`. È coerente con il comportamento prudente già
adottato per i resume picker e non richiede di persistere un identificatore
OpenCode. È la scelta consigliata per il primo rilascio.

### C. Persistenza dell'ID OpenCode

Salvare l'identificatore e rilanciare `opencode --session ID` fornirebbe
l'associazione più precisa. Richiede però un'estensione consapevole del modello
di snapshot/archivio, una sorgente affidabile dell'ID e validazione severa del
valore. L'ID deve restare un dato separato dal target tmux e non deve mai
diventare input shell. Questa strategia va valutata solo dopo lo spike TUI.

La persistenza OpenCode non deve essere inclusa automaticamente nei backup di
Mobile Agent Console: può contenere conversazioni, messaggi, credenziali o
altri dati fuori dall'attuale contratto minimizzato dei backup.

## Stati, permessi e notifiche

L'attuale `AgentStatusService` riconosce soltanto Codex e Claude e classifica lo
stato osservando una finestra limitata del pane. OpenCode potrebbe essere
aggiunto con un classificatore euristico dedicato, ma i pattern devono essere
raccolti da output reali e coperti da fixture. Non è corretto riutilizzare alla
cieca i pattern di Codex o Claude.

OpenCode espone un modello di permessi con azioni `allow`, `ask` e `deny`; le
richieste interattive possono ricevere risposte equivalenti ad approvazione
singola, approvazione persistente o rifiuto. Per la prima versione Mobile Agent
Console può controllare la TUI tramite i tasti già permessi, dopo una verifica
empirica del flusso. In una fase successiva il server OpenCode offre endpoint
strutturati per rispondere alle richieste di autorizzazione.

Riferimento ufficiale:

- [Permessi OpenCode](https://opencode.ai/docs/permissions/)

Il flag `--auto` non deve diventare il default del profilo: approverebbe
automaticamente le richieste non negate e cambierebbe materialmente il modello
di rischio. Le policy OpenCode dovrebbero essere esplicite, versionate solo se
prive di segreti e conservative per le operazioni mutative o esterne.

Le Web Push si attivano per OpenCode appena il classificatore produce
`waiting_input`/`waiting_authorization` (il poller condivide `provider_for`).
La classificazione è stata validata sui falsi positivi/negativi su istanza
pubblica il 08/08/2026 (vedi `IMP-OC-03` in `docs/backlog.md`); resta lo
stress-test su turni lunghi e sul caso `waiting_input` da feedback. Il
principio resta: un falso negativo nasconde una richiesta importante; un
falso positivo genera rumore e riduce la fiducia nelle notifiche.

## Distinzione tra agente e provider

OpenCode è un runtime agente capace di usare provider e modelli differenti.
Nel dominio corrente il termine `provider` spesso coincide con `codex` o
`claude`. L'integrazione mette in evidenza la necessità futura di distinguere:

```text
agent_kind: codex | claude | opencode | ...
model_provider: openai | anthropic | google | ...
model: identificatore del modello, quando disponibile
```

Questa separazione non è necessaria per il profilo TUI minimo e non dovrebbe
essere introdotta incidentalmente nello stesso round. Diventa però necessaria
prima di attribuire quote, consumo o modello a una sessione OpenCode: una
sessione OpenCode non equivale automaticamente a un provider specifico.

## Host mode

La modalità host è il percorso raccomandato per il primo spike:

- OpenCode viene installato per lo stesso utente che possiede il server tmux;
- configurazione, sessioni e credenziali restano nelle directory normali
  dell'utente host;
- il backend non deve montare `~/.config/opencode` o
  `~/.local/share/opencode`;
- il server tmux deve vedere il binario nel proprio `PATH`.

Poiché il profilo usa una login shell, va verificato il `PATH` effettivo del
processo avviato da tmux, non soltanto quello di una shell SSH interattiva.
L'installazione dovrebbe essere pinning a una versione nota e l'upgrade dovrebbe
essere separato dal deploy ordinario di web/backend.

Al momento di questa valutazione il comando `opencode` non è installato nella
macchina di lavoro, quindi non è stata ancora eseguita una prova TUI reale.

## Docker mode

La modalità Docker è tecnicamente possibile ma più costosa e rischiosa:

- `deploy/tmux-runtime/Dockerfile` contiene attualmente tmux, non OpenCode;
- il filesystem del container è read-only;
- il solo mount persistente applicativo è il workspace;
- autenticazione, configurazione e storage OpenCode richiederebbero volumi o
  secret boundary dedicati;
- modificare l'immagine obbliga a ricreare `tmux-runtime`, terminando tutte le
  sessioni vive.

Non si deve quindi aggiungere OpenCode al container durante un deploy ordinario.
Un eventuale rollout Docker richiede una finestra di manutenzione esplicita,
backup dei soli metadati previsti, comunicazione della perdita dei processi
attivi e un gate separato. Il binario deve essere installato con versione e
checksum pinning, senza usare un installer remoto non verificato durante il
normale avvio del container.

Il progetto OpenCode è distribuito con licenza MIT e offre binari/installazioni
per Linux:

- [repository ufficiale OpenCode](https://github.com/anomalyco/opencode)
- [licenza MIT](https://github.com/anomalyco/opencode/blob/dev/LICENSE)

## Perché non partire dal server OpenCode

`opencode serve` espone API per sessioni, messaggi, stato, diff, abort,
permessi e stream SSE. `opencode web` aggiunge inoltre un'interfaccia web già
completa. Queste capacità rendono possibile un adapter strutturato, ma
introdurle subito comporterebbe:

- due identità di sessione, tmux e OpenCode, da correlare;
- un nuovo servizio persistente con lifecycle proprio;
- un nuovo protocollo upstream e gestione della compatibilità di versione;
- autenticazione Basic e gestione di un ulteriore secret;
- possibili sovrapposizioni tra la PWA di Mobile Agent Console e OpenCode Web;
- il rischio di aggirare l'API tipizzata e l'audit di Mobile Agent Console.

Se in futuro si usa il server, deve ascoltare esclusivamente su loopback o su
un socket locale, mai su `0.0.0.0`. Il browser non dovrebbe collegarsi
direttamente: FastAPI dovrebbe agire da adapter minimizzato, con endpoint
tipizzati, autorizzazione Mobile Agent Console, CSRF sulle mutazioni e nessuna
esposizione delle credenziali OpenCode. La documentazione OpenCode avverte che
il server senza password non è protetto:

- [OpenCode Web](https://opencode.ai/docs/web/)
- [OpenCode Server](https://opencode.ai/docs/server/)

## Rischi e verifiche necessarie

Prima di dichiarare il supporto disponibile devono essere verificati almeno:

1. `pane_current_command` osservato realmente durante l'esecuzione; wrapper o
   runtime possono esporre un nome diverso da `opencode`.
2. Resa ANSI con `capture-pane -e` e xterm.js.
3. Comportamento su schermo alternativo e disponibilità dello scrollback.
4. Reazione della TUI ai resize del pane, specialmente su viewport mobile.
5. Paste di prompt brevi e multilinea, seguito da Enter separato.
6. Navigazione e risposta a ciascun tipo di richiesta di autorizzazione.
7. Interruzione con Escape e Ctrl-C senza lasciare processi orfani.
8. Avvio in directory consentite con path lunghi e caratteri Unicode.
9. Resume con più sessioni OpenCode nello stesso repository.
10. Persistenza dopo riavvio dell'host e comportamento con configurazione o
    autenticazione mancanti.
11. Assenza di segreti, prompt e output in audit, log, snapshot e backup.
12. Compatibilità con sessioni tmux preesistenti e con client desktop
    collegati allo stesso server.

## Roadmap proposta

La roadmap seguente è una sequenza tecnica suggerita, non un impegno di
calendario. Ogni fase richiede un round funzionale completo secondo
`AGENTS.md`: implementazione, test automatici, deploy mirato, test
sull'istanza pubblicata, aggiornamento di `LATEST_RELEASE` e commit.

### OC-00 — Spike host TUI

**Scopo:** dimostrare che la TUI è controllabile con il protocollo corrente,
senza modificare il prodotto.

- installare una versione pinning di OpenCode sull'host;
- configurare un provider senza esporre credenziali al backend;
- avviare manualmente `opencode` in una sessione tmux;
- eseguire la matrice di verifiche su output, input, resize, autorizzazioni,
  interrupt e resume;
- acquisire fixture TUI sanitizzate per classificazione e parsing futuri;
- documentare versione, installazione, rollback e problemi osservati.

**Gate:** nessuna regressione per tmux, nessun segreto nei dati acquisiti e
flusso base usabile da mobile.

### OC-01 — Profilo TUI di base

**Scopo:** creare e controllare sessioni OpenCode dalla PWA come terminali
generici.

- aggiungere `opencode` alle union backend/frontend;
- aggiungere argv costante server-side;
- aggiornare creazione, fake e test;
- mostrare il profilo nel selettore;
- mantenere inizialmente la sola vista Terminale se “Blocchi” non è ancora
  affidabile;
- documentare il prerequisito host e l'errore quando il binario manca.

**Gate:** creazione, prompt, output, tasti speciali e terminazione verificati
sull'istanza pubblicata.

### OC-02 — Archivio e snapshot

**Scopo:** preservare la semantica operativa già offerta agli altri profili.

- estendere archivio, snapshot e restore;
- usare inizialmente il selettore nativo delle sessioni;
- testare il caso con più conversazioni nello stesso progetto;
- decidere, con ADR se necessario, se persistere l'ID OpenCode;
- mantenere conversazioni e credenziali fuori dai backup MAC.

**Gate:** restore non ambiguo o esplicitamente mediato dall'utente, senza
comandi arbitrari persistiti.

### OC-03 — Stato agente e notifiche

**Stato:** rilasciato con il round del 08/08/2026. **Scopo:** badge e stato
affidabili per le sessioni OpenCode.

- introdotto `opencode` come tipo agente senza provider modello fittizio:
  `AgentProvider` include `"opencode"` e la vista non espone quote provider;
- classificatore dedicato su fixture reali della TUI (attività, inattività,
  autorizzazione), con `permission_state "ask"` e fallback `unknown`;
- rumore di chrome della TUI OpenCode filtrato dal summary (`SUMMARY_NOISE_*`);
- frontend: `agenticStatus = agentic || opencode` abilita badge, info-bar e
  Compact/Clear; `/permissions` resta Codex-only;
- Web Push si attiva automaticamente appena il classificatore produce
  `waiting_input`/`waiting_authorization`. Validazione FP/FN del 08/08/2026 su
  istanza pubblicata: nessun falso negativo (box autorizzazione sempre rilevata
  nei frame osservati) e nessun falso positivo (nessun `esc interrupt` residuo
  in idle, transizioni `active`↔`waiting_authorization` coerenti coi frame).
  Resta uno stress-test su turni lunghi e sul caso `waiting_input` da feedback
  prima di dichiararla del tutto affidabile.

**Gate:** classificazione conservativa, fallback `unknown` e nessuna
persistenza dell'output. **Follow-up:** stress-test del classificatore su turni
lunghi e validazione del caso `waiting_input` da feedback prima di dichiarare
le Web Push OpenCode del tutto affidabili.

### OC-04 — Adapter strutturato opzionale

**Scopo:** usare API/eventi OpenCode soltanto dove migliorano materialmente
affidabilità o UX.

- redigere un ADR sul secondo runtime e sulla correlazione degli ID;
- eseguire server OpenCode su loopback/socket con autenticazione;
- creare un collector o adapter minimizzato, non accesso browser diretto;
- mappare stato e richieste di permesso in contratti tipizzati MAC;
- applicare ruoli, CSRF, rate limit, Origin policy e audit minimizzato;
- garantire fallback completo al terminale tmux quando l'adapter non è
  disponibile.

**Gate:** tmux resta autorevole per il live terminale; indisponibilità o
rollback dell'adapter non interrompono le sessioni.

### OC-05 — Supporto Docker opzionale

**Scopo:** rendere disponibile OpenCode nel runtime isolato.

- progettare storage, secret e rete del runtime;
- pinning del binario e verifica checksum/SBOM;
- definire installazione dei provider senza inserire segreti nell'immagine;
- aggiungere test di build e un gate di manutenzione;
- eseguire il rollout soltanto in una finestra che autorizzi esplicitamente la
  ricreazione di `tmux-runtime`.

**Gate:** persistenza verificata, filesystem read-only preservato, container
non-root e nessuna perdita inattesa di sessioni.

## Considerazioni finali

La compatibilità fondamentale è alta perché OpenCode è prima di tutto una TUI
interattiva e Mobile Agent Console è progettato per terminali generici. Il
profilo di base appare una modifica contenuta; la parte complessa non è
l'avvio, ma offrire la stessa qualità già raggiunta per Codex e Claude su
resume, stato, permessi, notifiche e consumo.

La scelta raccomandata è quindi incrementale:

1. spike reale in host mode;
2. profilo TUI generico;
3. resume e classificazione specifici soltanto con evidenze raccolte;
4. API strutturata solo se il vantaggio giustifica un nuovo boundary;
5. Docker per ultimo, con manutenzione pianificata.

Non è consigliato incorporare OpenCode Web o esporre direttamente il suo
server come scorciatoia. Mobile Agent Console ha controlli di sicurezza,
sessione e audit più specifici del proprio threat model; un adapter futuro
deve preservare questi confini anziché aggirarli.
