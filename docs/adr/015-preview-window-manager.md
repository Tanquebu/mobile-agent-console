# ADR 015 — Window manager per le anteprime e preferiti

## Stato

Accettata. Gate prodotto approvato il 25/08/2026 (`GATE-PW-00` in
`docs/backlog.md`). Fase 1 (`IMP-PW-01`, window manager sollevato in
`App()`), Fase 2 (`IMP-PW-02`, tray e minimizzazione) e Fase 3
(`IMP-PW-03`, template di layout affiancati) consegnate e committate — il
trascinamento libero ("flottante") descritto più sotto è stato escluso
esplicitamente dalla Fase 3 (`GATE-PW-03` in `docs/backlog.md`), non solo
il ridimensionamento libero già rimandato dal testo originale dell'ADR.
Fase 4 (`IMP-PW-04-BACKEND`/`IMP-PW-04-FRONTEND`, Preferiti) consegnata e
committata — la distinzione `kind` fra file e directory descritta più
sotto è ristretta solo ai file (`GATE-PW-04`), coerentemente con l'unico
punto di ingresso (la stella in `PreviewModal`, che esiste solo per i
file); un preferito aperto da un artefatto non è mai stato ammesso, per lo
stesso motivo per cui l'apertura riusa sempre `_resolve_preview_file`
all'atto pratico e non un path legato a una sessione specifica. Con
questo il piano a fasi descritto in questo ADR è completo. Le finestre di
sessione restano solo un bullet di roadmap (M5), come deciso all'inizio —
non hanno avuto ulteriore lavoro.

## Contesto

La preview di un file (directory browser, artefatti, blocchi agente) è oggi
tre implementazioni indipendenti che condividono solo il componente di
rendering `PreviewModal` (`frontend/src/App.tsx`), non lo stato: `openFile` in
`DirectoryModal`, `previewItem` in `ArtifactsModal`, `blockPreview` in
`Console`. Ognuna monta `PreviewModal` come overlay `modal-backdrop` dentro se
stessa. Quando il componente che la ospita si smonta — si chiude il browser
directory, si torna alla dashboard, si cambia sessione (`Console` è
rimontata con `key={session.id}`) — l'anteprima aperta sparisce con esso.
Conseguenza pratica: non è possibile consultare più file contemporaneamente,
né file di directory diverse, né mantenere un'anteprima aperta mentre si
lavora su un'altra sessione o si torna alla dashboard.

Un vincolo che semplifica la soluzione: `/api/v1/sessions/{id}/file/preview`
(`backend/app/main.py`) risolve il path contro le allowlist globali
(`MAC_ALLOWED_ROOTS`/`MAC_PREVIEW_ROOTS`, ADR 014), non contro la cwd della
sessione — `session_id` nell'URL serve solo a soddisfare
`require_active_session` (una sessione viva qualsiasi). Un file aperto non è
quindi legato alla sessione da cui è stato aperto: può essere riappeso a
qualunque sessione attiva al momento della richiesta.

Un vincolo che complica la soluzione, già affrontato in questo repo per un
problema analogo (roadmap M4): l'app è mobile-first, e una vista con più
riquadri visibili contemporaneamente è stata valutata e scartata per
`Console` proprio per lo spazio ridotto su schermi stretti. La stessa
cautela si applica qui: l'affiancamento non può essere il comportamento di
base su mobile.

Verificato inoltre che `PreviewModal` non ha stato a livello di modulo (solo
`useState`/`useRef` per istanza): è già sicuro istanziarlo più volte in
parallelo, non serve riscriverlo per renderlo multi-istanza.

## Decisione

### Stato sollevato, un solo layer globale

Lo stato delle anteprime aperte si sposta da tre `useState` locali a un
unico "preview window manager": un hook con `useReducer` esposto tramite
`React.createContext` (niente libreria di stato — resta coerente con lo
stile a dipendenze minime del frontend). Un solo `<PreviewWindowsLayer>` è
montato dentro `App()` (`frontend/src/App.tsx`), fratello dello switch fra
`SessionList` e `Console`, non dentro nessuno dei tre punti che oggi aprono
un'anteprima. `DirectoryModal`, `ArtifactsModal` e `openBlockPreview`
chiamano `openPreviewWindow(source)` dal contesto invece di tenere lo stato
e renderizzare `PreviewModal` inline; il layer disegna le finestre altrove
nell'albero. Il layer sopravvive per costruzione a cambio sessione e ritorno
alla dashboard, non per un fix ad hoc sul ciclo di vita dei tre chiamanti.

Ogni finestra: `{ id, source: { kind, path, sessionId ultima nota, name,
mediaType }, siblings: string[] catturati al momento dell'apertura (per
prev/next), uiState: { mode: "minimized" | "floating" | "tiled", slot?,
rect? } }`. `siblings` è uno snapshot, non una vista live: se la directory
cambia dopo l'apertura, prev/next dentro quella finestra non lo riflette.
Accettato esplicitamente: la stessa navigazione oggi non ha nemmeno questo
concetto una volta chiuso il modal.

### Chrome responsivo sugli stessi breakpoint esistenti

Nessun window manager desktop calato su mobile. Si riusano i breakpoint già
in `styles.css` (720px, 980px):

- **Sotto 720px:** una sola finestra visibile alla volta, fullscreen, come
  oggi. Le altre finestre aperte non spariscono: collassano in un tray
  persistente (chip icona+nome) da cui si riapre o si chiude ciascuna senza
  perdere le altre.
- **Da 720px in su:** il tray offre un selettore di layout con 4 template
  fissi (1×1, 2 verticali, 2 orizzontali, 4 miste) implementati come CSS
  Grid ad aree nominate; le finestre non minimizzate occupano gli slot in
  ordine. Una finestra può restare "flottante" (trascinabile dalla title
  bar, non agganciata a un template) invece che in uno slot. Ridimensionare
  liberamente uno slot (divider trascinabili) resta esplicitamente fuori
  da questa ADR: i 4 template fissi coprono l'affiancamento richiesto senza
  costruire un resize engine.
- Cap a 8 finestre aperte contemporaneamente, con eviction della più vecchia
  minimizzata quando si supera il limite — dichiarato qui, non da scoprire
  in produzione.

### Preferiti, backend per utente

Un preferito è `{ id, path, label?, kind, addedAt }`, senza `sessionId` per
la ragione di contesto sopra: all'apertura si aggancia alla sessione
corrente (quella della console attiva, o l'ultima attiva se si apre da
dashboard; senza sessioni vive l'azione resta disabilitata con messaggio
esplicito, perché l'endpoint di preview richiede una sessione attiva).

Persistenza in una tabella `favorites` (SQLite/Alembic, stesso schema
applicativo di `attachments`/`push_subscriptions`), non `localStorage`:
l'app ha già account per utente (`User.username`/`role` in
`backend/app/models.py`, che supera quanto descritto nella sezione "Modello
di autenticazione" di `CLAUDE.md`, rimasta alla password condivisa
iniziale — da correggere separatamente) e già persiste risorse minori
per-utente in tabelle dedicate con lo stesso pattern. `GET/POST/DELETE
/api/v1/favorites`; il path viene ri-validato contro le allowlist
all'apertura, mai fidandosi del valore salvato — stessa postura dell'ADR
014 per i path citati nei blocchi.

UI: icona stella accanto al pulsante "copia path" già presente in
`PreviewModal` (`c86f5a9`); voce "Preferiti" in dashboard (stesso
trattamento di Archivio/Audit/Backup) e scorciatoia nel menu sessione,
entrambe aprono il preferito come nuova finestra tramite lo stesso manager.

### Esplicitamente fuori scope

Le finestre di sessione (switch rapido fra due `Console` affiancate) restano
solo un bullet in `docs/roadmap.md` (M5), non scaffolding qui: ogni riquadro
aprirebbe una propria connessione WebSocket/poll, la stessa moltiplicazione
di carico per cui la vista multi-pane simultanea era già stata scartata per
`Console` in M4.

## Conseguenze

Il refactor tocca tre punti di chiamata esistenti (`DirectoryModal`,
`ArtifactsModal`, `Console`), che perdono uno `useState` locale e un render
inline di `PreviewModal` a favore di una chiamata al contesto — cambiamento
meccanico, senza toccare la logica di fetch/rendering di `PreviewModal`
stesso. Il rischio maggiore è di regressione sullo stile di navigazione
odierno (indice `N / total` fra file), che va preservato per-finestra tramite
lo snapshot `siblings` descritto sopra.

Il tray minimizzato e i template di layout sono nuova superficie CSS/JS che
non esisteva prima; vanno testati sugli stessi breakpoint già usati altrove
in `frontend/tests/`. Nessun cambiamento al backend è necessario per le
finestre in sé (usano gli stessi endpoint di preview esistenti); i
Preferiti sono l'unica parte che richiede migrazione DB e nuovi endpoint.

## Alternative scartate

- Context/hook sostituito da una libreria di gestione finestre (es. una
  libreria di docking/tiling React): introdurrebbe una dipendenza esterna
  per un bisogno coperto da 4 template CSS Grid fissi, contro lo stile a
  dipendenze minime del frontend.
- Preferiti in `localStorage`: soddisferebbe "raggiungibile da dashboard e
  sessione" solo entro lo stesso browser; con account per utente già
  esistenti e un database già usato per risorse equivalenti, la persistenza
  lato server è lo stesso sforzo e copre anche un secondo dispositivo o
  browser.
- Ridimensionamento libero delle finestre (drag dei bordi) invece di
  template fissi: risolverebbe lo stesso bisogno con più superficie di
  stato (geometria per finestra, persistenza del layout) per un guadagno
  marginale rispetto a 4 layout predefiniti; rimandato a un'iterazione
  successiva se richiesto esplicitamente.
