# Backlog delle feature

Elementi valutati ma non ancora pianificati in una milestone. Ogni voce
documenta il problema e i vincoli noti, senza implicare un impegno di
implementazione immediato.

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
