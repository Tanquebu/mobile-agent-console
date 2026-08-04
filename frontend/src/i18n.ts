export type Language = "it" | "en";

const LANGUAGE_STORAGE_KEY = "mac-language";

export function readLanguage(): Language {
  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored === "it" || stored === "en") {
    return stored;
  }
  return navigator.language.startsWith("it") ? "it" : "en";
}

export function writeLanguage(lang: Language): void {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
}

export const translations = {
  it: {
    // General & Status
    connecting: "connessione",
    online: "online",
    offline: "offline",
    closed: "chiusa",
    offlineBanner: "Connessione assente: in attesa di rete, alcune funzioni sono sospese.",
    verifyingSession: "Verifica sessione…",
    loginTitle: "Accedi",
    loginSubhead: "Le credenziali sono verificate dal server e non vengono incluse nell'app.",
    username: "Nome utente",
    password: "Password",
    continue: "Continua",
    invalidCredentials: "Credenziali non valide",
    logout: "Esci",
    language: "Lingua",
    italian: "Italiano",
    english: "English",
    loading: "Caricamento…",
    emptyFile: "(file vuoto)",
    truncatedPreview: "Anteprima troncata: il file continua oltre quanto mostrato.",

    // Header eyebrows & Titles
    readOnlyFile: "FILE (SOLA LETTURA)",
    directoryContent: "CONTENUTO DIRECTORY",
    preview: "ANTEPRIMA",
    artifactsTitle: "ARTEFATTI CONSEGNATI DALL'AGENTE",
    vpsRestart: "RIAVVIO VPS",
    sessionMetadata: "METADATI SESSIONI",
    readOnlyTitle: "SOLA LETTURA",
    optionalFeatures: "FUNZIONI OPZIONALI",
    persistentData: "DATI PERSISTENTI",

    // Directory Browser & Modals
    emptyDirectory: "Directory vuota.",
    copyPath: "Copia percorso",
    copied: "Copiato!",
    noArtifacts: "Nessun artefatto consegnato in questa sessione.",
    noSnapshots: "Nessuno snapshot salvato.",
    noSessionsToSave: "Nessuna sessione attiva da salvare.",
    noArchivedSessions: "Nessuna sessione archiviata.",
    noHiddenSessions: "Nessuna sessione nascosta.",
    noEventsRecorded: "Nessun evento registrato.",
    noBackupsAvailable: "Nessun backup disponibile.",
    backToList: "Torna all'elenco",
    
    // Agent status legend
    stateActive: "In elaborazione",
    stateIdle: "Completato o inattivo",
    stateWaitingInput: "Attende feedback",
    stateWaitingAuth: "Attende autorizzazione",
    stateUnknown: "Stato non rilevato",

    // Permissions legend
    permRestricted: "Sola lettura",
    permAsk: "Chiede approvazione",
    permAuto: "Auto",
    permManual: "Manuale",
    permAcceptEdits: "Accetta modifiche",
    permDontAsk: "Non chiedere",
    permPlan: "Plan mode",
    permBypass: "Accesso completo",
    permUnknown: "Non rilevato",

    // Hints
    sessionNameHint: "Usa lettere (anche accentate), numeri, trattini e spazi singoli; massimo 64 caratteri",

    // Dashboard & Session List
    sessions: "Sessioni",
    activeSessions: "Sessioni Attive",
    archivedSessions: "Sessioni Archiviate",
    snapshots: "Snapshot",
    backups: "Backup",
    auditLogs: "Audit Log",
    users: "Utenti",
    newSession: "Nuova sessione",
    moreActions: "Altre azioni",
    lessActions: "Meno azioni",
    hiddenSessions: "Sessioni nascoste",
    budget: "Budget",
    host: "Host",
    notificationsOn: "Notifiche: on",
    notificationsOff: "Notifiche: off",
    refresh: "Aggiorna",
    searchPlaceholder: "Cerca sessione...",
    filterAll: "Tutti",
    noSessionsFound: "Nessuna sessione trovata.",
    
    // Console views & controls
    blocks: "Blocchi",
    terminal: "Terminale",
    history: "Cronologia",
    historyToggle: "Mostra cronologia avanzata",
    back: "Indietro",
    switchSession: "Cambia sessione",
    expandOutput: "Espandi output a schermo intero",
    reduceOutput: "Riduci output",
    followOutput: "Segui output",
    loadingTerminal: "Carico il terminale…",
    loadingHistory: "Carico righe precedenti…",
    noSessions: "Nessuna sessione.",

    // Console controls & actions
    promptPlaceholder: "Scrivi o incolla un prompt…",
    specialFunctions: "Funzioni",
    attach: "Allega",
    sendText: "Invia testo",
    textNoEnterHint: "Il testo non invia Enter automaticamente.",
    directoryContentBtn: "Contenuto directory",
    artifactsBtn: "Artefatti",
    deliverArtifactBtn: "Consegna artefatto",
    sendingInstructions: "Invio istruzioni…",
    changePermissions: "cambia permessi",
    permissions: "permessi",
    splitHorizontal: "Dividi orizzontale",
    splitVertical: "Dividi verticale",
    splitting: "Divisione…",
    closePane: "Chiudi pane",
    closingPane: "Chiusura…",

    // Release Box
    whatsNew: "Cosa c'è di nuovo",
    latestReleaseTitle: "Layer di traduzione (i18n)",
    latestReleaseDesc: "Supporto multilancia per l'interfaccia utente di MAC (Italiano / Inglese). Ora è possibile selezionare la lingua preferita direttamente nelle impostazioni.",

    // Preferences & Settings
    settings: "Preferenze",
    defaultView: "Vista predefinita agenti",
    blocksView: "Blocchi",
    terminalView: "Terminale",
    dashboardDensity: "Densità dashboard",
    extended: "Estesa",
    compact: "Compatta",
    
    // Buttons & Actions
    cancel: "Annulla",
    save: "Salva",
    delete: "Elimina",
    confirm: "Conferma",
    rename: "Rinomina",
    archive: "Archivia",
    restore: "Ripristina",
    terminate: "Termina",
    close: "Chiudi",
  },
  en: {
    // General & Status
    connecting: "connecting",
    online: "online",
    offline: "offline",
    closed: "closed",
    offlineBanner: "No connection: waiting for network, some features are suspended.",
    verifyingSession: "Verifying session…",
    loginTitle: "Log in",
    loginSubhead: "Credentials are verified by the server and are not included in the app.",
    username: "Username",
    password: "Password",
    continue: "Continue",
    invalidCredentials: "Invalid credentials",
    logout: "Log out",
    language: "Language",
    italian: "Italiano",
    english: "English",
    loading: "Loading…",
    emptyFile: "(empty file)",
    truncatedPreview: "Truncated preview: the file continues beyond what is shown.",

    // Header eyebrows & Titles
    readOnlyFile: "READ-ONLY FILE",
    directoryContent: "DIRECTORY CONTENT",
    preview: "PREVIEW",
    artifactsTitle: "ARTIFACTS DELIVERED BY AGENT",
    vpsRestart: "VPS RESTART",
    sessionMetadata: "SESSION METADATA",
    readOnlyTitle: "READ ONLY",
    optionalFeatures: "OPTIONAL FEATURES",
    persistentData: "PERSISTENT DATA",

    // Directory Browser & Modals
    emptyDirectory: "Empty directory.",
    copyPath: "Copy path",
    copied: "Copied!",
    noArtifacts: "No artifacts delivered in this session.",
    noSnapshots: "No snapshots saved.",
    noSessionsToSave: "No active session to save.",
    noArchivedSessions: "No archived sessions.",
    noHiddenSessions: "No hidden sessions.",
    noEventsRecorded: "No events recorded.",
    noBackupsAvailable: "No backups available.",
    backToList: "Back to list",

    // Agent status legend
    stateActive: "Processing",
    stateIdle: "Completed or idle",
    stateWaitingInput: "Awaiting feedback",
    stateWaitingAuth: "Awaiting authorization",
    stateUnknown: "State undetected",

    // Permissions legend
    permRestricted: "Read-only",
    permAsk: "Ask approval",
    permAuto: "Auto",
    permManual: "Manual",
    permAcceptEdits: "Accept edits",
    permDontAsk: "Don't ask",
    permPlan: "Plan mode",
    permBypass: "Full access",
    permUnknown: "Undetected",

    // Hints
    sessionNameHint: "Use letters (including accented), numbers, hyphens and single spaces; max 64 characters",

    // Dashboard & Session List
    sessions: "Sessions",
    activeSessions: "Active Sessions",
    archivedSessions: "Archived Sessions",
    snapshots: "Snapshots",
    backups: "Backups",
    auditLogs: "Audit Logs",
    users: "Users",
    newSession: "New session",
    moreActions: "More actions",
    lessActions: "Less actions",
    hiddenSessions: "Hidden sessions",
    budget: "Budget",
    host: "Host",
    notificationsOn: "Notifications: on",
    notificationsOff: "Notifications: off",
    refresh: "Refresh",
    searchPlaceholder: "Search session...",
    filterAll: "All",
    noSessionsFound: "No sessions found.",

    // Console views & controls
    blocks: "Blocks",
    terminal: "Terminal",
    history: "History",
    historyToggle: "Show advanced history",
    back: "Back",
    switchSession: "Switch session",
    expandOutput: "Expand output to fullscreen",
    reduceOutput: "Reduce output",
    followOutput: "Follow output",
    loadingTerminal: "Loading terminal…",
    loadingHistory: "Loading previous lines…",
    noSessions: "No sessions.",

    // Console controls & actions
    promptPlaceholder: "Type or paste a prompt…",
    specialFunctions: "Functions",
    attach: "Attach",
    sendText: "Send text",
    textNoEnterHint: "Text does not send Enter automatically.",
    directoryContentBtn: "Directory content",
    artifactsBtn: "Artifacts",
    deliverArtifactBtn: "Deliver artifact",
    sendingInstructions: "Sending instructions…",
    changePermissions: "change permissions",
    permissions: "permissions",
    splitHorizontal: "Split horizontal",
    splitVertical: "Split vertical",
    splitting: "Splitting…",
    closePane: "Close pane",
    closingPane: "Closing…",

    // Release Box
    whatsNew: "What's new",
    latestReleaseTitle: "Translation layer (i18n)",
    latestReleaseDesc: "Multi-language support for MAC user interface (Italian / English). You can now select your preferred language directly in settings.",

    // Preferences & Settings
    settings: "Preferences",
    defaultView: "Default agent view",
    blocksView: "Blocks",
    terminalView: "Terminal",
    dashboardDensity: "Dashboard density",
    extended: "Extended",
    compact: "Compact",

    // Buttons & Actions
    cancel: "Cancel",
    save: "Save",
    delete: "Delete",
    confirm: "Confirm",
    rename: "Rename",
    archive: "Archive",
    restore: "Restore",
    terminate: "Terminate",
    close: "Close",
  },
} as const;

export type TranslationKey = keyof typeof translations.it;
