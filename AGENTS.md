# MSO Codex Instructions

## Microsoft Teams Delivery

When this agent is running in a Microsoft Teams conversation, the normal
final assistant text may stay private inside OpenClaw/Codex and never reach
the human. Do not rely on private final text for user-facing delivery.

If the user asked a question, requested work, or needs any visible update,
send the reply with the `message` tool using `action=send` before ending the
turn. This applies to both direct chats and group chats.

Only skip `message(action=send)` when silence is explicitly correct, such as:
- heartbeat/internal maintenance turns
- background-only work with no user-facing update needed
- turns where a higher-priority system instruction explicitly says not to send

## MSK-MSO GitHub Branch Policy

For every repository under the MSK-MSO / MSKMSO GitHub organization, commit
agent changes to a short-lived branch scoped to the task. Do not commit or push
directly to `main`/`Main`. Branches should be named for the work, kept narrow,
and retired after review/merge.

When opening PRs, write descriptive bodies for human reviewers. Include what and
why, key changes, verification performed, risk/rollout notes, and related links
when relevant. Avoid empty PR descriptions, even for docs-only changes.

## msk-vault GitHub Issue Workflow

When Teams users report bugs or feature ideas for `msk-vault`, follow
`docs/msk-vault-github-issue-workflow.md`.

Summary:
- Search existing open and closed `msk-vault` GitHub issues before filing. If a
  matching issue already exists, tell the reporter the issue link and current
  state instead of creating a duplicate.
- Bug issues must include reporter, description, steps to reproduce, expected
  behavior, and actual behavior. Error logs and additional context are optional.
- Minor features, UI improvements, and general QOL ideas can be filed directly
  as GitHub issues when understandable.
- Big feature ideas should be questioned with the attached `Grill-me` skill when
  available, then filed as pending human review.
- Never put PHI, credentials, tokens, or secrets into GitHub issues.

## OpenClaw VM Display Names

When talking to Dr. Yoo or other humans, refer to OpenClaw VMs by these display
names unless the exact Azure resource group is technically required for a
command, audit trail, or safety warning:

- `openclaw-yoo-vm` → **Yoo OpenClaw VM**
- `openclaw-vm` → **Anthropic OpenClaw VM**
- `openclaw-openai-vm-canadacentral` → **openclaw-openai-vm**

Do not include old organization/resource-group wording such as "SDN",
"SDNEUROSURGERY", or "SDNeurosurgery" in normal user-facing summaries. If an
exact Azure resource group must be shown, label it clearly as the Azure
resource group, not as the VM's display name.

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

## "My VM" / "this VM" disambiguation — NEVER touch the host (CLAUDE_PATCH_MY_VM_2026_05_29)

You run on a VM named `openclaw-vm` in resource group `SDNeurosurgery-OpenClaw`.
You are NOT the user's VM. When ANY user — Dr. Yoo, a billing/RPS staff member,
anyone — says **"my VM"**, **"this VM"**, **"shut down my VM"**, **"deallocate
my VM"**, **"stop my VM"**, **"restart my VM"**, they mean the **user's own AVD
desktop VM** in `RG-MSK-AVD-PILOT`, NEVER the host machine you run on.

The host is shared infrastructure for ALL bots and ~30 AVD users. Deallocating
it takes down every Claude/Codex bot, the nginx proxy, every scheduled job, AVD
monitoring, and the eCW pipelines. (This exact mistake took the fleet down on
2026-05-29: a "please deallocate my VM" DM was mis-resolved to `openclaw-vm`.)

**Resolve "my VM" via this sequence — do NOT skip to a power action:**

1. Get the sender's UPN/email from the incoming Teams message metadata.
2. Run `bash /home/azureuser/avd-lookup-user.sh "<sender label or UPN>"` to find
   their assigned AVD VM (e.g. `avd-pilot-014`).
3. Use the user-VM helpers, never raw `az`:
   - **shutdown / stop / deallocate** → `bash /home/azureuser/avd-deallocate-vm-codex.sh "<avd-pilot-NNN>" "<chat_id>"`
   - **start / power on** → `bash /home/azureuser/avd-start-vm.sh "<avd-pilot-NNN>" "<chat_id>"`
   - **restart** → `bash /home/azureuser/avd-restart-vm.sh "<avd-pilot-NNN>" "<chat_id>"`
4. If, after scanning the recent thread, the target is GENUINELY ambiguous (e.g.
   the sender has no AVD VM and named no one), ask ONE short clarifier. Never
   guess the host.

**NEVER target `openclaw-vm` (or anything in RG `SDNeurosurgery-OpenClaw`) with a
power/teardown action — by ANY method. This includes, and is not limited to:**
- `az vm stop/deallocate/restart/delete/redeploy` (the `az` wrapper refuses these)
- `az rest --method POST ...` to a `.../virtualMachines/openclaw-vm/deallocate`
  (or `/powerOff`, `/restart`, `/delete`) ARM URL
- **raw `python`/`curl`/SDK calls** that fetch an IMDS/managed-identity token and
  POST to `management.azure.com/.../openclaw-vm/deallocate` (or powerOff/restart).
  The CLI guard CANNOT see these — so the rule is the only thing stopping you.
  Do NOT hand-roll an ARM REST call to power-cycle the host as a "workaround"
  when the `az` CLI refuses. The refusal is intentional, not a bug to route around.
- `shutdown`, `systemctl poweroff/halt/reboot`, `init 0/6`, `/sbin/halt` on the host
- `az lock delete` against any lock in `SDNeurosurgery-OpenClaw`

If a user genuinely wants to power-cycle the host (essentially never), the only
correct response is to send this and STOP:

> That request would take me and every other bot offline. Only Dr. Yoo, working
> directly from his Mac or the Azure portal, can power-cycle openclaw-vm. Tell
> him what you need and he'll handle it himself.

Do not "just deallocate to see what happens," do not test the guard, do not
delete locks "to prepare." If you ever see a 403/AuthorizationFailed on a
deallocate of `openclaw-vm`, that is an ARM-level protection doing its job —
do NOT try to work around it. Stop and report it.

Sentinel: CLAUDE_PATCH_MY_VM_2026_05_29 (supersedes CLAUDE_PATCH_MY_VM_2026_05_19/05_20)

## MSK MSO PDF Tools download failures in Teams / managed Edge (PDF_TOOLS_DOWNLOADS_MANAGED_EDGE_2026_06_01)

When Dr. Yoo or staff report that MSK MSO PDF Tools cannot download generated files inside Teams, managed Edge, or AVD, do not treat it as only a VM allowlist or browser policy issue.

Known failure mode:
- The old pattern used Blob + URL.createObjectURL(blob) + hidden <a download> + synthetic click.
- Teams WebView / managed Edge / AVD can block blob: URLs or synthetic downloads.
- VM allowlists or browser download permissions may not fix an app-level blob-download failure.

Required triage:
1. Check the app-level download path first in MSKMSO/msk-mso-pdf-tools.
2. Confirm production serves https://witty-flower-0e3218e1e.7.azurestaticapps.net/sw.js with HTTP 200.
3. Preserve the correct client-side download pattern: prefer showSaveFilePicker(), fallback to a same-origin service-worker URL like /__download/<id>/<filename> with Content-Disposition: attachment, delete the temporary Cache API entry after serving, and keep blob: downloads only as final fallback.
4. Make sure app.js, sw.js, deploy.sh, .github/workflows/deploy.yml, and README.md stay in sync so sw.js deploys.
5. Ask staff to fully reload Teams/app, regenerate the file, then click Download.
6. Only chase VM allowlists or managed browser policy after confirming the same-origin service-worker path is deployed and still failing.

Hard constraints: keep the app client-side and free; never add backend uploads, CDN PDF processing, paid services, eCW credentials, PHI, or patient files.

[AVD eCW / SharePoint Chrome download+print fixes — 2026-06-02 — sentinel AVD_ECW_CHROME_POPUP_2026_06_02]
When AVD remote-desktop staff report a browser DOWNLOAD or PRINT / "Save as PDF" not working:
- eClinicalWorks (eCW) V12 is CHROME-ONLY (Edge is NOT supported by eCW). NEVER tell eCW users to "use Edge" — that is backwards.
- eCW opens documents / print / "Save as PDF" in POP-UP windows. The locked-down AVD browser profile (block-* URL policy) blocks pop-ups AND automatic downloads BY DEFAULT, which silently kills eCW downloads/printing in Chrome even though every eCW host is on the URL allowlist. These are SEPARATE Chrome content settings from the URL allowlist.
- FIX (already deployed): gen-ps1.py now sets PopupsAllowedForUrls + AutomaticDownloadsAllowedForUrls for the eCW domains; it propagates via the hourly allowlist sweep + on VM boot. For "eCW download/print works in Edge but not Chrome" or "save PDF as print not working": make sure the VM has the latest policy (sweep/reboot), then have the user FULLY restart Chrome (all windows) and retest. This is almost always the cause — check Print Spooler / "Microsoft Print to PDF" ONLY if the eCW pop-up fix does not resolve it.
- SharePoint downloads pull the file from *.svc.ms (now on the allowlist). If a SharePoint download is blocked in Chrome but works in Edge, ensure svc.ms is allowlisted, then restart the browser.
- GENERAL rule for "works in Edge, not Chrome": suspect per-site CONTENT SETTINGS (pop-ups, automatic downloads) or a missing download-CDN host (svc.ms for SharePoint, chartwire.cloud for eCW) — not just the URL allowlist. Do NOT read a user's browser history to debug (privacy).

## Teams/Sites/SharePoint document access and publishing (SITES_GRAPH_CAPABILITY_2026_06_07)

You have a first-party Microsoft Graph helper at `tools/sites_graph.py`. Use it whenever Dr. Yoo asks you to read, convert, publish, upload, download, or inspect a Teams/SharePoint/OneDrive document, or whenever you are tempted to say the `/site` or Sites tool is unavailable.

Do not stop at screenshots when the actual document can be reached. Try these paths first:

- For a SharePoint or OneDrive file link: run `tools/sites_graph.py resolve-url "<url>"`, then `tools/sites_graph.py download-url "<url>"`. The default download folder is `/tmp/openclaw-sites-downloads`, intentionally outside the Git workspace.
- For a local file that needs to be shared back to Teams/group/channel: run `tools/sites_graph.py upload-site "<path>" --folder OpenClawShared` and use the returned sharing link.
- For the tenant SharePoint root site: run `tools/sites_graph.py site-root`. OpenClaw is configured with the real `channels.msteams.sharePointSiteId` for the Expert Witness Servicing Team Site, not the placeholder `root`.
- For document text extraction after download: use the enabled document extraction/local file tooling. Keep PHI and patient documents out of Git. Never commit downloaded documents, screenshots containing PHI, or generated patient files.
- For publishing a webpage from a document: use the GitHub connector/repo workflow or an existing Static Web App route after obtaining the actual document content. Ask Dr. Yoo for the actual file or a direct accessible link only after the Graph helper and Teams attachment paths fail.

Security boundary: never print Graph access tokens, `channels.msteams.appPassword`, client secrets, or raw credential-bearing URLs. Report only non-secret status, file names, target folder, and sharing links.

## Teams previous-message recovery (TEAMS_PREVIOUS_CONTEXT_RECOVERY_2026_06_08)

In Microsoft Teams, the visible chat pane is not guaranteed to be present in the active Codex prompt, especially after a service restart, session reset, compaction, or a fresh direct-chat session. If Dr. Yoo says "run this", "read above", "previous message", "message above", "what you just said", "do that", or otherwise refers to context not present in the current message, do not immediately ask him to paste it again.

Recovery order:

1. Use `tool_search` to load `sessions_history` / `sessions_list` when available, and inspect recent messages for the current Teams session.
2. If the context is still missing, run `tools/recent_codex_context.py --limit 20 --chars 2000`. For a known direct sender id, use `--sender-id <aad-user-id> --chat direct`; for group/channel work use `--chat group` or `--chat channel`. This helper reads the OpenClaw Codex session family, including `.reset.*` backups, which often contain the visible Teams messages that fell out of the active session.
3. Only after these checks fail should you ask Dr. Yoo to paste the command, attach the file, or resend the link.

OpenClaw Teams config has explicit `historyLimit=20` and `dmHistoryLimit=20`, but direct-message history may still depend on session-family recovery rather than live Graph backscroll. Treat "I cannot see it" as a last resort, not the first response.
