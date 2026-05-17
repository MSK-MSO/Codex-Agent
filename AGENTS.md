# MSO Codex Instructions

## Azure VM Run Command

When asked to inspect, repair, or verify an Azure VM from this repository in Codex Cloud, do not install Azure CLI and do not ask the user to paste `az` output. The cloud container may not be able to install `az`.

Use the repo-local Azure REST helper instead:

```sh
python3 scripts/azure_vm_run_command.py config
python3 scripts/azure_vm_run_command.py show
python3 scripts/azure_vm_run_command.py invoke --command-id RunShellScript --script 'hostname && whoami'
```

Use `RunShellScript` for Linux VMs and `RunPowerShellScript` for Windows VMs. Pass `--resource-group` and `--vm-name` when they are not configured by environment or credential file.

Azure can temporarily reject overlapping VM Run Command calls with a 409 “execution is in progress” lock. The helper retries that lock by default; tune it with `--conflict-retries` and `--conflict-delay-seconds` when needed.

The helper reads configuration from either environment variables or `~/.config/mso-codex/azure-vm-run-command.json`. Required values are:

- `AZURE_TENANT_ID`
- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `AZURE_SUBSCRIPTION_ID`

Optional defaults:

- `AZURE_RESOURCE_GROUP`
- `AZURE_VM_NAME`
- `AZURE_VM_COMMAND_ID`

For Codex Cloud setup, `scripts/codex_setup_azure_vm_env.sh` can write the credential file from setup-time environment variables or secrets. If Azure calls fail with a network error, the Codex Cloud environment likely needs agent internet access to `login.microsoftonline.com` and `management.azure.com` with `POST` allowed.

Treat VM Run Command as production remote execution. Run read-only diagnostics first, avoid printing secrets, and ask for confirmation before destructive changes, restarts, package installs, firewall changes, or anything that could interrupt business systems.
