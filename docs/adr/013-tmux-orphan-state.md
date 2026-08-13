# ADR 013 — Rilevamento host degli scope tmux orfani

## Stato

Accettata.

## Contesto

Quando un pane tmux scompare in modo anomalo, lo scope systemd creato dal hook
di spawn può restare attivo insieme ai suoi discendenti. Una policy basata sul
nome del processo non distingue un server di sviluppo legittimo da uno
sopravvissuto alla sessione che lo possedeva; command line e working directory,
inoltre, non possono attraversare il boundary di osservabilità.

Il collector on-demand non può interrogare il bus systemd utente né il socket
tmux: il suo mount namespace e l'hardening documentato nell'ADR 009 ne impediscono
la `connect()`. Allentarlo allargherebbe il perimetro di ogni richiesta API.

## Decisione

Una unit host oneshot, `mobile-agent-console-tmux-orphan-state`, gira ogni 30
secondi. Con comandi argv fissi e `shell=False` confronta i PID dei pane restituiti
da `tmux list-panes -a` con i PID originari dichiarati dagli scope attivi
`tmux-spawn-*.scope`. Uno scope il cui pane non esiste più è un candidato orfano.

L'helper scrive atomicamente un file `0600` contenente solo PID del pane, età,
numero di task, memoria corrente, picco e swap aggregati. Non scrive UUID dello
scope, nomi di sessione, command line, environment o working directory. Il
collector applica una grace period privata (default 300 secondi), scarta lo
stato più vecchio di 120 secondi e pubblica il risultato nel contratto v3.

La presenza di un orfano è warning. Memoria corrente o swap oltre le soglie
private configurate rendono il componente critical. Il sistema è strettamente
osservativo: non invia segnali e non termina processi.

## Conseguenze

La dashboard può distinguere precisamente uno scope sopravvissuto dal semplice
numero elevato di processi omonimi. Il prezzo è una terza fonte periodica senza
storico, analoga a Docker e servizi supervisionati; timer fermo, file assente o
malformato sono sempre `unknown`, mai “nessun orfano”.

La unit helper omette le direttive che creano un mount namespace, ma conserva
`NoNewPrivileges`, argv fissi, timeout e output limitato. Il collector esposto
al backend mantiene integralmente il proprio hardening.

