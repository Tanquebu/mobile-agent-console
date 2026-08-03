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
| `07-autorizzazione.txt` | richiesta di autorizzazione (`Permission required`, azioni `Allow once` / `Allow always` / `Reject`) |

## Cosa manca, e perché

**Il frame di autorizzazione ora esiste** (`07-autorizzazione.txt`), ed è
stato ottenuto **provocandolo**, non aspettandolo: avviando OpenCode con una
policy `{"permission":{"bash":"ask","edit":"ask"}}` e chiedendo un comando di
shell. Il marcatore `Permission required` non compare in nessuno degli altri
frame, quindi è discriminante.

Il resto di questa sezione è la storia di come ci si è arrivati, e vale la
pena conservarla perché è un errore che si può rifare.

La prima versione di questo file affermava che OpenCode "non ne ha mai
prodotta una". **È falso.** La verifica indipendente (`TEST-OC-00`) ne ha
osservata una reale, con azioni selezionabili `Allow once` / `Allow always` /
`Reject` su un pattern di percorsi. Non è stata riprodotta in modo
deterministico — né da chi l'ha vista né in un tentativo successivo — e
sembra dipendere dalla decisione del modello in quel turno, non da un comando
fisso.

Quindi la formulazione corretta è: con configurazione vuota e senza `--auto`
l'agente esegue comandi di shell **di norma** senza chiedere, ma **esiste** un
percorso di autorizzazione che si attiva in modo non ancora caratterizzato per
un sottoinsieme di azioni. Per il classificatore questo è il caso peggiore:
uno stato che compare di rado non verrà mai coperto per caso, e un falso
negativo su `waiting_authorization` nasconde all'utente una richiesta che
blocca il turno.

Anche quella formulazione, però, era ancora imprecisa. La documentazione
ufficiale dei permessi chiarisce che il comportamento **non è casuale**:
quasi tutti i permessi predefiniscono ad `allow`, tranne `external_directory`
e `doom_loop` che predefiniscono ad `ask`. La richiesta osservata "una volta
sola" riguardava un accesso fuori dalla directory di progetto, quindi era
deterministica — mancava la conoscenza della regola, non la riproducibilità.

Morale, buona per il classificatore di `OC-03`: due round hanno definito
quello stato prima "inesistente" e poi "non deterministico", e in entrambi i
casi la causa era che nessuno aveva letto la regola che lo governa. Prima di
dedurre il comportamento di un agente dall'osservazione, conviene cercare se
è documentato.

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
