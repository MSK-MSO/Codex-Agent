#!/bin/sh
set -eu

if [ -n "${AZURE_VM_CREDENTIALS_FILE:-}" ]; then
  CONFIG_FILE="$AZURE_VM_CREDENTIALS_FILE"
  CONFIG_DIR="${AZURE_VM_CONFIG_DIR:-$(dirname "$CONFIG_FILE")}"
else
  CONFIG_DIR="${AZURE_VM_CONFIG_DIR:-$HOME/.config/mso-codex}"
  CONFIG_FILE="$CONFIG_DIR/azure-vm-run-command.json"
fi

if [ -z "${AZURE_TENANT_ID:-}" ] || \
   [ -z "${AZURE_CLIENT_ID:-}" ] || \
   [ -z "${AZURE_CLIENT_SECRET:-}" ] || \
   [ -z "${AZURE_SUBSCRIPTION_ID:-}" ]; then
  echo "Azure VM Run Command credentials were not provided; skipping credential file setup."
  exit 0
fi

mkdir -p "$CONFIG_DIR"
umask 077

python3 - "$CONFIG_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
data = {
    "tenantId": os.environ["AZURE_TENANT_ID"],
    "clientId": os.environ["AZURE_CLIENT_ID"],
    "clientSecret": os.environ["AZURE_CLIENT_SECRET"],
    "subscriptionId": os.environ["AZURE_SUBSCRIPTION_ID"],
}

optional = {
    "resourceGroup": os.environ.get("AZURE_RESOURCE_GROUP"),
    "vmName": os.environ.get("AZURE_VM_NAME"),
    "commandId": os.environ.get("AZURE_VM_COMMAND_ID"),
}
for key, value in optional.items():
    if value:
        data[key] = value

path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
print(f"Wrote Azure VM Run Command credential file to {path}")
PY
