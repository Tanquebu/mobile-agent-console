#!/usr/bin/env bash
# Cattura il payload JSON che AGY invia allo script statusline.
# Uso temporaneo: configurare in settings.json, poi leggere il file di log.
#
# Ogni invocazione riceve un oggetto JSON su stdin; lo script lo salva
# in append nel file di log e stampa una riga sulla statusline.

LOGFILE="${HOME}/.gemini/antigravity-cli/statusline-capture.jsonl"

# Leggi tutto lo stdin (AGY chiude il pipe dopo ogni tick)
INPUT=$(cat)

# Salva il payload in append
echo "$INPUT" >> "$LOGFILE"

# Stampa la statusline di default (modello + permessi) come fallback
echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    parts = []
    model = data.get('model', '')
    if model:
        parts.append(model)
    mode = data.get('permission_mode', '') or data.get('mode', '')
    if mode:
        parts.append(mode)
    print(' · '.join(parts) if parts else '…')
except Exception:
    print('…')
" 2>/dev/null || echo "…"
