# Frame TUI di OpenCode (spike `IMP-OC-00`)

Frame reali catturati con `tmux capture-pane -p` da una TUI OpenCode
`1.18.11` in un pane 80x24, il 03/08/2026. Servono a `OC-03`, dove il
classificatore di stato va costruito su output reali e non sui pattern
presi in prestito da Codex o Claude.

Sanitizzazione: l'unico dato variabile era il percorso del progetto,
sostituito ovunque con `/workspace/progetto`. Nessun nome utente, percorso
personale, host o credenziale è mai comparso in questi frame; il progetto di
prova conteneva un solo file di testo inventato.

Normalizzazione applicata, dichiarata perché questi file **non** sono più
byte-identici alla cattura: rimossi gli spazi in coda a ogni riga e le righe
vuote finali. Le righe vuote interne sono conservate — nel frame originale
ogni frame occupa 24 righe. Chi confronta questi file con un
`capture-pane` fresco deve applicare la stessa normalizzazione.

| File | Stato rappresentato |
|---|---|
| `01-idle.txt` | TUI pronta, nessun turno in corso |
| `02-prompt-inserito.txt` | testo incollato nell'input, **non** ancora inviato |
| `03-attivo.txt` | turno in corso (`esc interrupt` nella barra di stato) |
| `04-completato.txt` | turno concluso, con un comando di shell eseguito |
| `05-conferma-interrupt.txt` | dopo il primo `Escape` (`esc again to interrupt`) |
| `06-interrotto.txt` | dopo il secondo `Escape` (`interrupted`) |

## Cosa manca, e perché

**Non esiste un frame di richiesta di autorizzazione.** Non è un'omissione:
durante lo spike OpenCode non ne ha mai prodotta una. Con configurazione
vuota e senza `--auto` ha eseguito comandi di shell senza chiedere, quindi
lo stato `waiting_authorization` non è osservabile finché non si applica una
policy dei permessi esplicita. Quando `OC-01` la introdurrà, i frame
corrispondenti andranno aggiunti qui prima di scrivere il classificatore.

## Avvertenza per chi scriverà il classificatore

Questi frame provengono da una TUI in **schermo alternativo**: ogni frame
contiene il chrome completo dell'interfaccia, ripetuto identico, ed è la
stessa condizione che ha reso inaffidabili i pattern testuali per Antigravity.

Qui però la situazione è migliore di quanto temuto, ed è stato verificato sui
frame invece che assunto: `esc interrupt` compare **soltanto** in
`03-attivo.txt`, non nel chrome di `01-idle.txt`, e `interrupted` soltanto in
`06-interrotto.txt`. I due marcatori sono quindi discriminanti. Restano da
verificare su una casistica più ampia — sei frame di un solo turno non sono
una base sufficiente per un classificatore — e in particolare va controllato
se `esc interrupt` sopravviva nel frame anche dopo la fine del turno su round
più lunghi, che è esattamente il modo in cui il problema si è manifestato
altrove.
