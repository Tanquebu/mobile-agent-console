# ADR 002: core agent-agnostic

Stato: accettata.

## Decisione

Il dominio base conosce processi, sessioni, pane, input e output, non vendor o
formati di agenti. Profili e adapter opzionali aggiungono comando consentito,
badge, pattern di attenzione e shortcut.

## Conseguenze

Shell e REPL funzionano senza plugin; le integrazioni vendor non possono
contaminare sicurezza e lifecycle. Le euristiche saranno meno precise, ma
configurabili e sostituibili.

