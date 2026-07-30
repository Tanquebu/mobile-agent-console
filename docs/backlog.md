# Backlog delle feature

Elementi valutati ma non ancora pianificati in una milestone. Ogni voce
documenta il problema e i vincoli noti, senza implicare un impegno di
implementazione immediato.

## Vista con più pane tmux visibili contemporaneamente

**Stato:** scartata deliberatamente, non da riprendere senza un motivo nuovo.

Valutata come possibile completamento di "Supporto multi-pane esteso" (M4):
invece del selettore a tendina attuale (un pane alla volta), mostrare 2+
output di pane contemporaneamente. Scartata perché l'app è mobile-first e
uno split reale sarebbe scomodo su schermi stretti — motivo per cui anche lo
split orizzontale/verticale scelto in MAC ha effetto visibile solo
collegandosi direttamente con `tmux attach`, non nella vista MAC stessa.
Richiederebbe comunque catturare anche la posizione dei pane da tmux
(`pane_left`/`pane_top`), non fatto oggi. Riconsiderare solo se emerge un
uso desktop-first per cui valga la pena la complessità.

## Toolbar terminali complete su viewport mobile

**Stato:** differita; impatto attuale basso.

Codex, Claude e altri programmi TUI possono abbreviare con un'ellissi le
toolbar o status line quando il pane tmux ha poche colonne. L'abbreviazione
avviene nel processo terminale prima di `capture-pane`: il frontend riceve
quindi già testo come `A…` e non può recuperare tramite CSS la parte omessa.

La sessione osservata durante la diagnosi misurava 80×24 celle. Allargare
automaticamente la finestra tmux è considerato fragile perché:

- altera anche la visualizzazione di eventuali client tmux desktop collegati;
- può cambiare il layout di finestre con più pane;
- applicazioni fullscreen e TUI reagiscono diversamente al resize;
- una larghezza adatta a una toolbar non coincide necessariamente con quella
  migliore per il resto dell'output.

Possibili direzioni future:

- controllo esplicito per sessione tra larghezza normale ed estesa;
- resize basato sulla viewport, con ripristino e gestione dei client collegati;
- terminal mode xterm.js con protocollo di resize completo;
- adapter opzionali specifici dell'agente per mostrare lo stato fuori dal
  terminale, mantenendo agent-agnostic il core.

Prima dell'implementazione vanno definiti comportamento multi-pane,
interazione con client tmux già collegati e semantica di ripristino. La
soluzione dovrebbe confluire nel lavoro M1 su pane selection/resize o nel
terminal mode previsto in M3.

## Drift dello scroll in pausa e storico delle app a schermo alternato

**Stato:** parzialmente risolta. La cronologia Claude è disponibile tramite
adapter opzionale validato; il limite resta per altre TUI fullscreen e il
drift dello scroll live è differito. Il terminal mode xterm.js (vista
Terminale) non risolve né peggiora questo punto: renderizza meglio i colori
ANSI, ma eredita lo stesso comportamento "reset del buffer a ogni snapshot"
perché il protocollo resta a snapshot autorevole, non byte-stream
incrementale (scelta deliberata, vedi `docs/architecture.md` sezione
Streaming). Lo scrollback delle app a schermo alternato resta comunque un
limite di `tmux capture-pane`, non risolvibile da nessuna libreria di
rendering frontend.

Bug osservato: con "autoscroll intelligente" in pausa (utente risalito
nell'output), il contenuto del pane continua comunque a essere sostituito
nel DOM ad ogni snapshot WebSocket. Poiché `capture-pane` restituisce una
finestra scorrevole delle ultime righe (non un log append-only), a parità di
`scrollTop` il testo mostrato slitta gradualmente verso le righe più recenti
mentre l'agente produce output — un piccolo "glitch" visivo, non un vero
salto in fondo.

Primo tentativo di fix: congelare il contenuto renderizzato mentre non si
segue l'output (bufferizzare gli snapshot in un ref e riapplicarli solo alla
ripresa). Elimina il drift, ma introduce un problema più serio per le
sessioni che eseguono programmi TUI a schermo alternato (vim, htop, Claude
Code CLI stesso): tmux non mantiene scrollback per lo schermo alternato,
quindi `capture-pane` può restituire al massimo l'altezza corrente del pane,
a prescindere da qualunque `lines` richiesto. Verificato empiricamente su
una sessione reale:

```
80x24 alt=1 history=0/2000
```

Prima del fix, il drift dava l'illusione di uno storico più ampio (ogni
snapshot rivelava contenuto leggermente diverso durante lo scroll, facendo
sembrare che ci fosse sempre "un po' di più" da trovare risalendo). Con il
contenuto congelato quel tetto reale (poche decine di righe) diventa
evidente e stabile, rendendo di fatto impossibile leggere output storico più
lungo di una schermata per queste sessioni — un regresso peggiore del
glitch che il fix risolveva. Commit revertito.

Possibili direzioni future, nessuna banale:

- compensazione precisa dello scroll invece del congelamento: diff tra
  contenuto precedente e nuovo per individuare quante righe sono state
  espulse dall'inizio della finestra, misurarne l'altezza renderizzata (il
  wrapping dipende dal font e dalla larghezza del pane) e traslare
  `scrollTop` di conseguenza — corregge il drift senza bloccare
  l'aggiornamento, ma è sensibile a wrapping/robustezza del diff;
- pane più alto per le sessioni TUI, con gli stessi trade-off di resize già
  discussi sopra (client collegati, layout multi-pane, reazione delle app
  fullscreen);
- accettare il drift residuo come limite noto e minore, documentandolo in
  UI (es. tooltip sul pulsante "Segui output").

Per Claude non tentare nuovamente di ricavare la cronologia da
`capture-pane`: ADR 007 definisce il collector normalizzato, il feature flag e
il fallback live. Il terminal mode xterm.js è stato implementato ma, come
previsto, non risolve lo scrollback delle app a schermo alternato (limite
tmux); la soluzione generica resta un adapter separato con le stesse
proprietà di isolamento, sul modello di ADR 007.

---

## Modulo di osservabilità dell'host

**Stato: da validare, non avviato.** Discusso il 30/07/2026, nato da un
incidente reale: nove dev server Astro lasciati vivi da riavvii ripetuti,
~258 MB l'uno, 2,3 GB su una macchina da 3,7. Nessuno se n'è accorto finché
la RAM non è andata in sofferenza.

L'idea è aggiungere a MAC una vista sullo stato dell'host invece di far
partire l'ennesimo servizio dedicato. Prima di scrivere codice vanno chiuse
tre questioni, e la prima non è quella che sembra.

### 1. Il repo pubblico non è il rischio che sembra

MAC è già un accesso shell remoto: crea sessioni, manda input, termina
processi, dal telefono. Il raggio d'azione pericoloso esiste già, e un modulo
di osservabilità non lo allarga in modo sostanziale.

**Il problema non è il codice pubblico, è la configurazione.** Nel repo non
devono entrare: inventario degli host, nomi dei servizi, mappa delle porte,
soglie legate all'infrastruttura reale, credenziali. Il modulo legge *cosa*
sorvegliare da configurazione e non lo sa per conto suo.

Il codice che dice «leggi la memoria disponibile» è banale e pubblicabile. Il
file che dice «su forge girano questi servizi su queste porte» è una mappa
per chi volesse provarci. Nel repo va solo l'esempio con valori finti.

### 2. Non costruirlo attorno a Docker

Trappola concreta, perché è la direzione naturale: i comandi già messi nel
bashrc sono su Docker, ma **l'incidente del 30/07 non riguardava Docker**.
Erano processi node nudi, fuori da qualunque container. Una dashboard centrata
sui container non avrebbe mostrato nulla, e mancherebbe il prossimo incidente
allo stesso modo.

Il livello giusto è il processo e la memoria, con i container come una delle
viste e non come l'impianto.

### 3. Istantanea o tendenze: decide la forma, e il costo

MAC è costruito attorno alla sessione terminale con il suo flusso di output.
Il monitoraggio è un'altra forma, dati strutturati campionati nel tempo.

- **Tendenze** → serve un campionatore che gira e una memoria dove scrivere.
  A quel punto il servizio nuovo lo hai fatto partire comunque, che è
  esattamente ciò che si voleva evitare.
- **Stato adesso** → una chiamata su richiesta che restituisce un'istantanea.
  Niente campionamento, niente base dati, niente processo aggiuntivo.

**Raccomandazione: partire dall'istantanea.** Copre la gran parte del bisogno,
e dopo qualche settimana d'uso si sa quali metriche vale la pena conservare
invece di indovinarlo adesso.

### Contenuto minimo della schermata

Deve rispondere a una domanda sola: *c'è qualcosa che non va in questo
momento?*

- memoria disponibile e swap;
- primi dieci processi per RSS, con età del processo (avrebbe fatto vedere i
  nove Astro dev in un colpo d'occhio);
- porte in ascolto, con evidenza di quelle non attese (un dev server che
  slitta di porta in porta è il sintomo);
- container non sani;
- spazio disco;
- carico.

### Vincoli da rispettare

- La postura di sicurezza della VPS è documentata in
  `handbooks/vps-security.md` del workspace di crescita professionale:
  port binding su `BIND_HOST` e mai `0.0.0.0`, firewall solo inbound. Qualsiasi
  endpoint nuovo la rispetta.
- Azioni distruttive (kill, restart) vanno trattate diversamente dalla sola
  lettura: la lettura può stare dietro l'autenticazione esistente, l'azione
  merita una conferma esplicita come già avviene per interrupt e terminazione
  di sessione.

### Prossimo passo

Far passare l'idea dalla skill `valida-progetto` del workspace di crescita
professionale, prima di scrivere codice: verifica fit col posizionamento,
rischio di dispersione e valenza dual-use. Il dual-use qui c'è (MAC è già nel
portfolio, e un modulo di osservabilità è materiale spendibile in colloquio da
IT Manager), ma la validazione va fatta prima e non dopo.

**Rimandato al 2 agosto 2026**, dopo il reset del budget mensile.
