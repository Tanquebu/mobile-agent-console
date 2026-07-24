# ADR 001: tmux come runtime delle sessioni

Stato: accettata.

## Contesto

Le sessioni devono sopravvivere a browser, rete e backend ed essere accessibili
anche con strumenti standard.

## Decisione

tmux è il runtime autorevole. L'app usa un socket dedicato, `capture-pane` per
lettura, buffer/paste per testo e `send-keys` solo per tasti tipizzati.

## Conseguenze

Otteniamo persistenza e interoperabilità senza daemon proprietario. Accettiamo
che capture-pane sia una rappresentazione imperfetta dei programmi fullscreen
e che backend e processi debbano condividere l'utente Linux.

