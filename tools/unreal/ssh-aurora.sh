#!/usr/bin/env bash
# Hub → Aurora LAN SSH helper (no Tailscale). Uses config/ue-hosts.json.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="$(python3 -c "import json; h=json.load(open('$ROOT/config/ue-hosts.json'))['hosts']['aurora']; print(h['ssh_host'])")"
USER="$(python3 -c "import json; h=json.load(open('$ROOT/config/ue-hosts.json'))['hosts']['aurora']; print(h['ssh_user'])")"
exec ssh -o BatchMode=yes -o ConnectTimeout=8 "${USER}@${HOST}" "$@"
