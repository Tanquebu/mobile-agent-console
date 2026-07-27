# Backlog delle feature

Elementi valutati ma non ancora pianificati in una milestone. Ogni voce
documenta il problema e i vincoli noti, senza implicare un impegno di
implementazione immediato.

## Euristica "Attende feedback" troppo stretta

**Stato:** non prioritario, da riprendere.

`AgentStatusService.classify` (`backend/app/services/agent_status_service.py`)
richiede una riga terminata letteralmente con `?` entro le 4 righe precedenti
un prompt vuoto per classificare `waiting_input`. Frasi come "fammi sapere
se..."/"dimmi quando..." senza punto interrogativo restano `idle`, quindi le
notifiche locali (che leggono questo stesso stato) non scattano per quei
turni. Verificato dal vivo confrontando il pane tmux reale con la
classificazione. Possibile direzione: riconoscere anche pattern di richiesta
senza `?` esplicito, ma va valutato l'impatto sulle altre viste che già
usano questo stato (badge lista sessioni, euristiche di attenzione M3).

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
drift dello scroll live è differito.

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
il fallback live. La soluzione generica resta il terminal mode o un adapter
separato con le stesse proprietà di isolamento.

## Notifiche locali attive solo con la lista sessioni montata

**Stato:** limite noto, accettato per ora.

Le notifiche locali si basano sul polling di `/api/v1/agent-statuses` già
presente in `SessionList`; il rilevamento delle transizioni verso "attende
feedback"/"attende autorizzazione" gira quindi solo mentre quella vista è
montata (app in background o schermo bloccato mentre si è sulla lista), non
mentre si è dentro la console di un'altra sessione. Spostare il polling a
livello di `App` risolverebbe il limite ma richiede sollevare anche lo stato
`sessions`, usato pervasivamente in `SessionList`: rimandato finché non
emerge un bisogno concreto.
