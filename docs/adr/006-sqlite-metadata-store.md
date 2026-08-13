# ADR 006 — SQLite come metadata store locale

## Stato

Accettata.

## Contesto

tmux resta l'autorità per processi e terminali attivi, ma account, audit,
archivio e preferenze richiedono persistenza strutturata. Il deployment
corrente è single-host e single-backend; un database di rete aggiungerebbe
complessità senza un requisito operativo.

## Decisione

Usare SQLite tramite SQLAlchemy 2 e migrazioni Alembic versionate. Il file
predefinito è `.mobile-agent-console/app.db` nella root persistente del
workspace. Il processo di avvio applica `alembic upgrade head` tramite API
Python prima di avviare Uvicorn.

Il database conserva soltanto metadati applicativi. Output terminale, prompt,
contenuto degli allegati, environment e segreti non vi entrano. tmux e il
filesystem restano autorità rispettivamente per sessioni attive e file.

## Conseguenze

- deploy e restart del backend non perdono i metadati;
- il file SQLite può essere incluso in backup consistenti;
- un solo processo backend scrive il database in questa fase;
- un futuro multi-host richiederà rivalutare il metadata store;
- ogni modifica allo schema richiede una nuova revisione Alembic, senza
  modificare retroattivamente revisioni già distribuite.

La revisione `0002` introduce gli utenti persistenti. Se la tabella è vuota,
l'avvio crea un solo amministratore usando username configurabile e la password
secret già prevista dal deployment; viene memorizzato esclusivamente l'hash
Argon2id. Dopo il bootstrap il secret non viene più letto per autenticare.

La revisione `0003` introduce l'archivio delle sessioni concluse. Conserva
soltanto nome, directory, profilo, autore e timestamp; non conserva output,
prompt, environment o contenuti degli allegati.

La revisione `0009` estende l'archivio con nome agentico e breve riepilogo
opzionali. Il riepilogo non è acquisito automaticamente da una trascrizione:
può essere precompilato da un file artefatto riservato, ma viene sempre
mostrato e reso modificabile prima della conferma. È quindi metadato deliberato
dell'archivio, soggetto anche ai backup SQLite, e resta limitato a 2.000
caratteri.

La revisione `0004` introduce l'audit append-only. Ogni record contiene soltanto
attore, operazione tipizzata, target, status HTTP e timestamp. La vista è
limitata agli amministratori e restituisce al massimo 500 eventi per richiesta.
