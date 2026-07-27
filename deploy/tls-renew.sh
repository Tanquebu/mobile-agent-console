#!/bin/sh
# Refresh the Tailscale-issued TLS certificate nginx terminates with (see
# docs/adr/008-tailscale-cert-tls.md) and restart only the stateless `web`
# service, and only if the certificate actually changed.
set -eu

: "${MAC_INSTALL_DIR:?set MAC_INSTALL_DIR}"
: "${MAC_TAILNET_HOSTNAME:?set MAC_TAILNET_HOSTNAME}"

cert_dir="$MAC_INSTALL_DIR/.secrets/tls"
cert_file="$cert_dir/tailscale.crt"
key_file="$cert_dir/tailscale.key"
mkdir -p "$cert_dir"

before=""
[ -f "$cert_file" ] && before=$(sha256sum "$cert_file")

tailscale cert --cert-file "$cert_file" --key-file "$key_file" "$MAC_TAILNET_HOSTNAME"

after=$(sha256sum "$cert_file")
if [ "$before" != "$after" ]; then
  cd "$MAC_INSTALL_DIR"
  docker compose up -d web
fi
