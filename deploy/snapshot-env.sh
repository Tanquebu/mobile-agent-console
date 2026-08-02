#!/bin/bash
# Conserva una copia datata del .env del deployment.
#
# Il .env non e' e non deve essere versionato: contiene token, percorsi e
# preset propri dell'installazione. Senza pero' alcuna copia storica, una
# modifica accidentale non lascia traccia — e' successo il 02/08/2026 con un
# overlay sparito da COMPOSE_FILE, che ha fatto scomparire in silenzio una
# voce dell'interfaccia senza alcun errore ne' modo di ricostruire quando
# fosse cambiata.
#
# Le copie vivono in customizations/, ignorata da git come il .env stesso.
# Uso: deploy/snapshot-env.sh [motivo]

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_file="$root/.env"
target_dir="$root/customizations/env-snapshots"

if [ ! -f "$source_file" ]; then
  echo "Nessun .env in $root" >&2
  exit 1
fi

reason="${1:-}"
suffix=""
if [ -n "$reason" ]; then
  # Solo caratteri innocui nel nome file.
  suffix="-$(printf '%s' "$reason" | tr -c 'A-Za-z0-9_-' '-' | cut -c1-40)"
fi

mkdir -p "$target_dir"
chmod 700 "$target_dir"
# Senza il punto iniziale: un archivio che `ls` non mostra e' un archivio che
# ci si dimentica di avere.
target="$target_dir/env.$(date +%Y%m%dT%H%M%S)$suffix"

cp "$source_file" "$target"
chmod 600 "$target"

previous="$(ls -1 "$target_dir"/env.* 2>/dev/null | grep -v "^$target$" | tail -1 || true)"
echo "Copia creata: ${target#"$root"/}"
if [ -n "$previous" ]; then
  if diff -q "$previous" "$target" >/dev/null; then
    echo "Nessuna differenza rispetto a ${previous##*/}"
  else
    echo "Differenze rispetto a ${previous##*/}:"
    diff "$previous" "$target" | sed 's/^/  /' || true
  fi
fi
