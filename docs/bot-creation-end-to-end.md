# Creating a new personal AI bot — end-to-end playbook (Claude or Codex)

This is the canonical sequence for "Dr. Yoo wants a new bot for <user>." Follow it top-to-bottom. **Don't reorder, don't skip preflight, don't improvise.** Every step has a verify gate; if a gate fails, stop and escalate — do not retry.

The 2026-05-11 incident (Jose / Axel / Lia / Afrah Claude bots stuck for hours behind Microsoft's tenant policy gate, with MSO Claude making the problem worse by repeatedly retrying) is the failure mode this playbook prevents.

This playbook covers BOTH variants — a **Claude-based** bot (Anthropic-backed, runs on `openclaw-vm`) and a **Codex-based** bot (OpenAI-backed, runs on `openclaw-openai-vm` post-migration). The preflight, manifest, catalog publish, and install phases are identical. The Entra app credentials, VM placement, model account, and responder code diverge starting in Phase 1.

---

## ASK FIRST — five required decisions

**Before doing any work, capture all five decisions in writing. Do not guess unresolved fields.** If Dr. Yoo's request already explicitly answers one or more of them, **do not re-ask those answered fields**; record them and only ask for the remaining unresolved decisions. A wrong assumption on any unresolved field costs hours of rework and can leave orphan Azure resources / catalog entries that have to be cleaned up by hand.

1. **Variant**: **Claude-based** or **Codex-based**?
   - If Dr. Yoo explicitly says `make a Codex bot` or `make a Claude bot`, treat that as the decision. Do **not** ask the Codex-or-Claude question again.
   - Claude-based → runs on `openclaw-vm`, backed by Anthropic. Display-name convention: `<Firstname> Claude` (e.g. `Zahid Claude`, `Cameron Claude`, `Ashley Claude`).
   - Codex-based → runs on `openclaw-openai-vm` (per the 2026-05-20 migration), backed by OpenAI. Display-name convention: **`<Firstname> Codex`** (e.g. `Zahid Codex`) — mirrors the Claude pattern. Use this for every new Codex bot. Older bots named `<Firstname>'s Open AI Agent` (Yoo, Neil) are legacy naming kept for back-compat; **do not** use that pattern for new bots.

2. **Which model account / credentials** should back the bot?
   - **For Codex: ALWAYS the MSO OpenAI account.** This is the standard for every new Codex bot. The MSO account is signed in at `/home/azureuser/.codex/auth.json` on `openclaw-openai-vm` and is shared across every Codex bot that runs as `azureuser` (yooopenai, neil, etc.). Only ask Dr. Yoo about this if he explicitly says he wants a different account — otherwise default to MSO, no question needed.
   - For Claude: which Claude OAuth account / `/etc/claude-tokens/<short>.env` entry? Each per-user bot gets its own token file. Reuse-from-existing is allowed but track it — quota is per account.

3. **Which VM** hosts the new bot?
   - Default for Claude: `openclaw-vm` (resource group `SDNeurosurgery-OpenClaw`).
   - Default for Codex / OpenAI: `openclaw-openai-vm` (per the 2026-05-20 migration; 16 Codex crons + the OpenAI bots moved there).
   - If Dr. Yoo wants the bot on a non-default VM (e.g., a fresh per-bot VM, or alongside another Codex bot), confirm explicitly — don't guess.

4. **Does the user already have a bot of the same variant?**
   - Check Teams app catalog AND systemd services on the chosen VM. If yes, ask: keep both side-by-side, or rename the existing one. **Do NOT propose tearing it down** — see the hard rule below.
   - Do not silently build a duplicate — it pollutes the catalog and confuses installation.

> **HARD RULE — never tear down an existing bot unless Dr. Yoo explicitly tells you to.**
> Even if a bot looks idle, broken, half-built, abandoned, deprecated, duplicate, or "obviously" superseded — leave it running. Dr. Yoo may be using it, someone on staff may be using it, or it may be load-bearing for a workflow you can't see from here. Building a new variant next to it is the default. Tearing down is a separate decision that requires an explicit verbal order from Dr. Yoo for that specific bot. Renames count as destructive too — they trigger a fresh catalog upload and can quarantine the entry.

5. **Display name** (the Teams catalog name — **picked once, never renamed**).
   - **Convention is fixed: `<Firstname> Claude` for Claude-based, `<Firstname> Codex` for Codex-based.** Examples: Zahid Claude / Zahid Codex, Cameron Claude / Cameron Codex. Do not invent variants — keep both bot families on the same `<Firstname> <Variant>` pattern so the fleet stays readable.
   - The older `<Firstname>'s Open AI Agent` form (Yoo, Neil) is legacy; do not extend it to new bots.
   - Renames force a fresh manifest upload, which triggers Microsoft anti-abuse and can quarantine the entry — see RECOVERY at the bottom of this doc.

Capture the answers in writing before starting Phase 0. If Dr. Yoo doesn't give a definitive answer on any still-unresolved item, **STOP and re-ask only that item**. Building a bot on a guess is the fastest way to create work for everyone.

---

## Inputs you need before starting

(These derive from the five decisions above plus a couple of routine fields.)

- **Variant**: `claude` or `codex` (from decision 1).
- **Target VM**: `openclaw-vm` (Claude default) or `openclaw-openai-vm` (Codex default), or whatever Dr. Yoo specified (decision 3).
- **Model account / credentials**: see decision 2.
- **Bot short-name**: `<name>` (lowercase, used for service names, dir names, file prefixes — e.g. `<existing-healthy-bot>`, `ashley`, `jesus-reyes`).
- **Bot display name**: the Teams catalog name (e.g. `<existing-healthy-bot-display-name>`, `Neil's Open AI Agent`). **Pick ONCE. Never change it.** Renames force re-upload which triggers anti-abuse.
- **Target user UPN**: e.g. `<firstname>@musculoskeletalmso.com`.
- **Target user AAD object id**: look up via `GET /v1.0/users/{upn}?$select=id`.
- **Bot description** (≤80 chars): goes in the manifest.

---

## PHASE 0 — Preflight (≤2 minutes, mandatory)

Before doing anything that creates state, run these checks. If any fails, **stop** and escalate to Dr. Yoo. Do not proceed in the hope it'll work anyway.

### 0.1 — Is the Teams app permission policy actually open right now?

The single biggest cause of "bot built but can't install" today is the tenant Teams app permission policy quietly blocking `AppType: Private` (custom uploaded apps). Microsoft sometimes flips this default; admins sometimes flip it too. **Check before you upload.**

Probe: do a dry-run install of an EXISTING working bot to a test user who already has it (Dr. Yoo). If that returns 200 OK or "already installed" (409 with `Conflict` body containing `installationId`), the gate is open. If it returns 403 `App is blocked by app permission policy`, the gate is closed — stop, escalate, do not build the new bot today. The whole pipeline is broken.

```bash
# pseudo:
curl -X POST /v1.0/users/{yoo-id}/teamwork/installedApps \
  -d '{"teamsApp@odata.bind":"https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{any-working-claude-app-id}"}'
# 200/409 → policy open. 403 → policy closed, ABORT.
```

### 0.2 — Has the AppPublisher identity been used recently?

Check that `SDN-YooVault/yoomd-graph-refresh-token-appcatalog` mints cleanly:

```bash
RT=$(az keyvault secret show --vault-name SDN-YooVault --name yoomd-graph-refresh-token-appcatalog --query value -o tsv)
curl -X POST .../token -d "client_id=9f4cd925-fcc7-4f42-8dc2-ae98bcad28a6&grant_type=refresh_token&refresh_token=$RT&scope=AppCatalog.ReadWrite.All offline_access"
# expect: 200 with access_token
```

If 401/403, the refresh token has expired (90-day idle) and Dr. Yoo needs to re-consent. Escalate.

### 0.3 — Is the VM healthy?

Run `scripts/bot-health-check.sh` against an existing bot on the **target VM** (e.g., `<existing-healthy-bot>` on `openclaw-vm` for Claude; one of the existing OpenAI bots on `openclaw-openai-vm` for Codex). The goal of this step is to confirm **VM-level infrastructure** (systemd, network, vault, Bot Framework auth) is working — NOT to confirm every existing bot is healthy. Use this decision tree:

1. **Reference bot reports `healthy: true`** → VM is fine. Proceed to 0.4.
2. **Reference bot reports `healthy: false` but a single-bot reason** (e.g., services `inactive (dead)` with `bf_auth: pass` and `creds_readable: pass` — i.e., somebody just stopped that bot) → **Do NOT block the new build on this.** Note the unhealthy bot as a separate fix-up task and pick a DIFFERENT existing bot on the same VM as your VM-health reference. Common case: a bot got `systemctl stop`-ed manually and never re-enabled. Confirm by running `bot-health-check.sh` against another bot on the same VM — if that one is `healthy: true`, the VM is fine and the first failure is a per-bot issue.
3. **Two or more existing bots on the same VM report `healthy: false` with infra-level failures** (e.g., `bf_auth: fail`, `creds_readable: fail`, `dir_owner: fail`, multi-bot crash loop) → that's a real VM-level problem. Fix VM infra first; don't pile a new bot on top of a broken base.

In short: **one offline bot ≠ broken VM.** Only block on the new build if you can't find a single healthy reference bot on the target VM after trying at least two.

### 0.4 — Does the model account / API credential work right now?

- **Claude**: confirm the chosen `/etc/claude-tokens/<short>.env` mints (use any working bot's token to sanity-check the Anthropic API is reachable from the target VM).
- **Codex**: confirm the MSO OpenAI account is signed in at `/home/azureuser/.codex/auth.json` on the target VM (default `openclaw-openai-vm`). Read `account_id` out of that file and verify it matches the MSO OpenAI account identifier. Then run `sudo -u azureuser codex --print "hello"` as a smoke test — if it returns text, the account is alive. A dead/expired account produces "Had trouble generating a reply" downstream, which is then mistaken for a publishing problem; fix it with a fresh Codex CLI login (Dr. Yoo signs in once via device code) before continuing.

---

## PHASE 1 — Microsoft Entra app + Bot Service registration

### 1.1 — Create the Entra app registration

```bash
# Using VM managed identity for Graph (has Application.ReadWrite.All):
APP_RESP=$(az rest --method POST \
  --url "https://graph.microsoft.com/v1.0/applications" \
  --headers "Content-Type=application/json" \
  --body '{"displayName":"<Bot Display Name>","signInAudience":"AzureADMyOrg"}')
APP_ID=$(echo "$APP_RESP" | jq -r .appId)
APP_OBJ=$(echo "$APP_RESP" | jq -r .id)
```

### 1.2 — Mint the client secret

**CRITICAL: save `secretText`, not `keyId`.** This trapped the 2026-05-07 fix.

```bash
SECRET_RESP=$(az rest --method POST \
  --url "https://graph.microsoft.com/v1.0/applications/$APP_OBJ/addPassword" \
  --headers "Content-Type=application/json" \
  --body '{"passwordCredential":{"displayName":"v1","endDateTime":"<now+1yr ISO>"}}')
SECRET_VALUE=$(echo "$SECRET_RESP" | jq -r .secretText)  # NOT .keyId. NEVER .keyId.
[ -n "$SECRET_VALUE" ] && [ "$SECRET_VALUE" != "null" ] || { echo "FAIL: no secretText"; exit 1; }
```

### 1.3 — Create the SP for the app

```bash
az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals" \
  --body "{\"appId\":\"$APP_ID\"}"
```

### 1.4 — Create the Azure Bot Service resource

```bash
az bot create -g SDNeurosurgery-OpenClaw \
  -n "OpenClaw-<NameClaude>" \
  --app-type SingleTenant \
  --appid "$APP_ID" \
  --tenant-id 50186224-2255-444a-b321-60a84114115c \
  --endpoint "https://openclaw-sdneuro.westus2.cloudapp.azure.com/<name>/api/messages" \
  --sku F0 \
  --display-name "<Bot Display Name>"
```

### 1.5 — Enable the Teams channel

```bash
az bot msteams create -g SDNeurosurgery-OpenClaw -n "OpenClaw-<NameClaude>"
```

### 1.6 — Verify-after-create

```bash
az bot show -g SDNeurosurgery-OpenClaw -n "OpenClaw-<NameClaude>" --query properties.endpoint
az bot msteams show -g SDNeurosurgery-OpenClaw -n "OpenClaw-<NameClaude>" --query properties.isEnabled
# Both should return non-null / true. If not, STOP.
```

---

## PHASE 2 — VM service files

### 2.1 — Drop the bot code on the VM as `azureuser`, not root

**This is the bug from 2026-05-09.** Provisioning scripts that run `sudo` and forget to `chown` back leave files owned by `root`, and the bot service (running as `azureuser`) can't read its own creds. The service then crash-loops every 5 seconds while `systemctl is-active` lies that it's running.

```bash
# Run the deploy as azureuser, NOT as root:
sudo -u azureuser bash -lc '
  mkdir -p /home/azureuser/.<name>-bot
  cat > /home/azureuser/.<name>-bot/creds.json <<JSON
{"app_id":"<APP_ID>","client_secret":"<SECRET_VALUE>","tenant":"<TENANT_ID>"}
JSON
  chmod 600 /home/azureuser/.<name>-bot/creds.json
'
```

If you must do part of it as root, end every block with `sudo chown -R azureuser:azureuser /home/azureuser/.<name>-bot /home/azureuser/<name>-*`.

### 2.2 — Generate bot.py and responder.py from a template

Use the latest WORKING bot's source as the template. Examples: the latest working bot under the chosen variant — e.g. for Claude pick any healthy `<short>-bot.py` / `<short>-responder.py` pair off openclaw-vm; for Codex pick one off openclaw-openai-vm. **Read them first, don't write fresh.**

Substitute:
- `USER_AAD_ID = "<target user's AAD object id>"`
- Bot name strings
- Port (allocate a fresh one — check `ss -tlnp` for what's in use)

**Critical**: after substitution, `diff` the new responder against the template. Confirm only the substituted fields differ. **No duplicate function definitions** — the 2026-05-07 recursion bug was a copy-paste that doubled `_post_reply_orig_protect`.

### 2.3 — systemd units

Create `/etc/systemd/system/<name>-bot.service` and `<name>-responder.service`. Use existing working bot's unit as template. Common gotcha: the unit's `User=` line must be `azureuser`, not root.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now <name>-bot.service <name>-responder.service
```

### 2.4 — nginx route

Add the location block to `/etc/nginx/sites-enabled/openclaw-sdneuro`:

```
location /<name>/api/messages { proxy_pass http://127.0.0.1:<port>/api/messages; ... }
```

`sudo nginx -t && sudo systemctl reload nginx`.

### 2.5 — Verify-after-deploy

**Run `bash /home/azureuser/bot-health-check.sh <name>`. All 7 gates must pass.** If any fail, fix before continuing. See `docs/multi-bot-debugging.md` for the gate-by-gate fix list.

---

## PHASE 3 — Build the manifest zip (catalog publish is OPTIONAL for per-user bots)

**Standing rule (2026-05-29, Dr. Yoo):** for per-user bots — the default case — you build the zip but do **NOT** upload it to the tenant catalog. The user sideloads the zip themselves in Phase 4. Skip 3.2 and 3.3 below in that case.

Only do the catalog upload (3.2 + 3.3) if Dr. Yoo explicitly asks for a tenant-wide install or the bot needs to live in the org-wide app catalog. The default for every personal bot is **build zip → hand to user → user sideloads**.

### 3.1 — Generate manifest

Build the manifest zip with a **fresh externalId UUID** (never reuse one — duplicates cause publish conflicts). Use an existing working bot's manifest as the template.

### 3.2 — Upload — ONCE — via AppPublisher identity

**Not the YooMD chat token.** Per `docs/teams-app-publishing.md` Rule 0:

```bash
RT=$(az keyvault secret show --vault-name SDN-YooVault --name yoomd-graph-refresh-token-appcatalog --query value -o tsv)
APPCAT_TOKEN=$(curl -X POST .../token \
  -d "client_id=9f4cd925-fcc7-4f42-8dc2-ae98bcad28a6&grant_type=refresh_token&refresh_token=$RT&scope=AppCatalog.ReadWrite.All offline_access" \
  | jq -r .access_token)

UPLOAD=$(curl -X POST "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps" \
  -H "Authorization: Bearer $APPCAT_TOKEN" \
  -H "Content-Type: application/zip" \
  --data-binary @manifest.zip)
TEAMS_APP_ID=$(echo "$UPLOAD" | jq -r .id)
```

### 3.3 — Verify publish (mandatory poll)

```bash
for i in {1..30}; do
  STATUS=$(curl -sS -o /tmp/r -w '%{http_code}' \
    -H "Authorization: Bearer $APPCAT_TOKEN" \
    "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/$TEAMS_APP_ID")
  [ "$STATUS" = "200" ] && { echo "published"; break; }
  sleep 10
done
[ "$STATUS" = "200" ] || { echo "QUARANTINED — STOP — DO NOT RETRY"; exit 1; }
```

If verify fails after 5 minutes, the app got quarantined by Microsoft. **Stop. Don't re-upload.** Each new upload deepens the cooldown. Write a handoff, escalate.

---

## PHASE 4 — Hand the zip to the user for self-upload

**New standing rule (2026-05-29, Dr. Yoo):** do NOT install the app yourself via Graph. Do NOT push the zip into the tenant catalog. Instead, **send the manifest zip to the user in Teams chat with step-by-step sideload instructions, and let them upload it themselves.**

Why this changed:
- Every programmatic upload risks tripping Microsoft's anti-abuse cooldown (~24h silent quarantine). User-driven sideload via "Upload a custom app" sidesteps it entirely.
- The user ends up owning the install, so removal/reinstall is in their hands — no Graph token plumbing needed when something goes wrong.
- The tenant Teams App Permission Policy gate (the 2026-05-11 wall) doesn't apply to a user uploading a custom app into their own personal scope.

### 4.1 — Deliver the manifest zip to the user in Teams

Use the bot's own send-helper (or `mskmso-anthropic-upload-to.sh` for the MSKAI bot) to post `manifest.zip` directly into the user's 1:1 chat with the appropriate sending bot. **Do not email it. Do not link a SharePoint URL.** The zip must arrive as a Teams attachment so the user can download it with one tap.

```bash
bash /home/azureuser/<sender-bot>-upload-to.sh "<user-upn-or-chat-id>" manifest.zip "Your <Firstname> Claude bot — upload instructions below"
```

### 4.2 — Post the upload instructions in the SAME chat, right after the zip

Paste the following verbatim (substitute `<Firstname> Claude` / `<Firstname> Codex` as appropriate). Keep it as one message so the user has the zip and the steps side-by-side.

> **How to install your `<Firstname> Claude` bot (one-time, ~30 seconds):**
>
> 1. **Download the zip** above to your computer (or phone — works on both).
> 2. In Teams, click **Apps** in the left sidebar (the grid icon).
> 3. Click **Manage your apps** at the bottom of the Apps panel.
> 4. Click **Upload an app**.
> 5. Click **Upload a custom app** (it may say *Upload for me* on some tenants).
> 6. Select the **zip file** you just downloaded.
> 7. When Teams asks, click **Add** to install it for yourself.
>
> You'll see a new chat appear with `<Firstname> Claude`. Send it a message to confirm it's working — it should reply within a few seconds.
>
> If you get an error like *"This app could not be added"* or *"blocked by app permission policy,"* reply here and I'll look into it.

### 4.3 — Wait for the user to confirm, then verify

Do NOT claim success until the user reports back that the bot replied to them. Once they confirm:

```bash
# Verify the install record landed (read-only — no install action). Uses YooMD chat token, which has TeamsAppInstallation.ReadForUser.All.
RT=$(az keyvault secret show --vault-name SDN-YooVault --name yoomd-graph-refresh-token --query value -o tsv)
CHAT_TOKEN=$(curl -X POST .../token \
  -d "client_id=14d82eec-204b-4c2f-b7e8-296a70dab67e&grant_type=refresh_token&refresh_token=$RT&scope=TeamsAppInstallation.ReadForUser.All offline_access" \
  | jq -r .access_token)

curl -G "https://graph.microsoft.com/v1.0/users/$TARGET_AAD_ID/teamwork/installedApps" \
  -H "Authorization: Bearer $CHAT_TOKEN" \
  --data-urlencode '$expand=teamsApp' \
  | jq ".value[] | select(.teamsApp.displayName == \"<Bot Display Name>\") | .teamsApp.displayName"
# Expect: prints the bot's display name. If empty, the user hasn't completed the sideload yet — wait, don't re-prompt.
```

### 4.4 — If the user hits the policy 403

If the user reports *"App is blocked by app permission policy,"* that's the tenant gate (covered in Phase 0.1). Don't try to work around it by switching to a programmatic install — that re-introduces the failure mode this whole phase was rewritten to avoid. Escalate to Dr. Yoo so he can open the gate, then have the user retry the same sideload steps.

---

## PHASE 5 — End-to-end health check

Final gate before you report success:

1. **`bot-health-check.sh`** returns `healthy: true` for the new bot
2. **Test message via `<name>-send-to.sh`** to the target user (the bot's own send-helper) — expect HTTP 201
3. **Read activities log** after the user sends a `hello` — `tail /home/azureuser/.<name>-bot/activities.jsonl` should show the inbound message within 30s

If steps 1+2+3 all pass, the bot is live. Report 4-field summary to Dr. Yoo.

If step 3 fails (no inbound message logged), the user didn't actually message yet OR there's a Microsoft → bot delivery problem. Don't claim success. Wait for confirmation.

---

## PHASE 6 — Wire Dr. Yoo's identifier access (Tier 1 vs Tier 2)

Every bot in the fleet gets access to Dr. Yoo's professional identifiers (NPI, CA medical license, practice address, mailing address, office phone, work email, practice org). This lets bots pre-fill vendor consulting agreements, hospital credentialing forms, Sunshine Act / Open Payments forms, insurance provider sections, CME registration, etc. — without re-asking Dr. Yoo every time.

The single source of truth is `SDN-YooVault` → secret `dr-yoo-identifiers` (JSON). Edit the repo file `MSKMSO/Virtual-Machines/scripts/dr-yoo-identifiers.json`, then run workflow `kv-set-dr-yoo-identifiers.yml` to push the new value into the vault.

### Tier decision tree

| Bot belongs to | Tier | Where the identifiers live |
|---|---|---|
| Dr. Frank Kevin Yoo or Dr. Heather Yoo (personal agents) | **Tier 1** | Hardcoded in the responder source via marker `DR_YOO_IDENTIFIERS_V1` |
| Anyone else — staff, organizational, persona, or third-party bot | **Tier 2** | Fetched from Key Vault on service startup via marker `DR_YOO_IDENTIFIERS_V2_VAULT` |

There are only three Tier 1 bots and there will never be more: Dr. Yoo's Anthropic Agent (`yooanthropic-responder`), Dr. Yoo's OpenAI Agent (`yooopenai-responder`), Dr. Heather's AI Agent (`heather-responder`). Every new bot you create is Tier 2.

### Tier 1 wiring (for the rare case of building Dr. Yoo's or Dr. Heather's next personal agent)

Use `MSKMSO/Virtual-Machines/scripts/tier1-embed-identifiers.py` via workflow `tier1-embed-identifiers.yml`. It:

1. Reads the JSON from `/home/azureuser/dr-yoo-identifiers.json` on the VM (a legacy artifact still present for Tier 1 — do not remove).
2. For each service in `SERVICES`, finds the responder `.py` via `systemctl show … -p ExecStart`.
3. Locates the first system-prompt-style variable (`SYSTEM_BASE`, `SYSTEM_PROMPT`, etc.) and appends the identifier block via a rebinding statement at end of file.
4. py_compile-checks the new file, backs up `.bak-<ts>`, atomic-replaces, `systemctl restart`.

Add the new service name to `SERVICES` in `tier1-embed-identifiers.py`. Dispatch the workflow. It is idempotent (marker `DR_YOO_IDENTIFIERS_V1` prevents re-injection).

**Tradeoff:** Tier 1 needs a code redeploy + restart to pick up a new identifier value. Acceptable because NPI / license / addresses change rarely.

### Tier 2 wiring (the default — every new bot)

#### 2a. For Python responders (the templated bots — Ashley, Cameron, all staff bots, etc.)

Use `MSKMSO/Virtual-Machines/scripts/tier2-wire-vault-fetch.py` via workflow `tier2-wire-vault-fetch.yml`. It:

1. Confirms the VM managed identity can read `SDN-YooVault → dr-yoo-identifiers` (it has Key Vault Administrator).
2. For each service in `SERVICES`, finds the responder `.py` via `systemctl show`.
3. Injects two pieces:
   - After the last `import` line: a `_dr_yoo_block()` helper that shells out to `az keyvault secret show … dr-yoo-identifiers` at module load, caches via `lru_cache`, returns the formatted identifier block. Returns `""` on any failure so the bot keeps working.
   - At end of file: `<varname> = <varname> + "\n\n" + _dr_yoo_block()`.
4. py_compile + atomic replace + `systemctl restart`.

Add the new bot's responder service name (e.g. `<name>-responder`) to the `SERVICES` list. Dispatch the workflow. Marker `DR_YOO_IDENTIFIERS_V2_VAULT` makes it idempotent.

**Per-user account note:** if the bot runs as its own Linux user (the per-user bot pattern — Jose, Axel, Lia, Afrah, etc.), that user must have `az login --identity` configured. The provisioning script for per-user bots already does this. The VM MI has Key Vault Administrator regardless of which Linux user calls `az`.

#### 2b. For openclaw runtime bots (Codex specifically — and any future openclaw-based bot)

These don't have a Python responder file to patch. The behavioral policy is in workspace policy files (`IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`) that bootstrap reads at session start. The pattern is:

1. Install a fetcher script at `/home/azureuser/.<bot>-fetch-identifiers.sh` that runs `az keyvault secret show` and writes `<workspace-dir>/DR_YOO_IDENTIFIERS.md` from the JSON.
2. Add `ExecStartPre=/home/azureuser/.<bot>-fetch-identifiers.sh` to the bot's systemd unit (idempotent — only insert once).
3. Run the fetcher once to populate the workspace file.
4. `systemctl daemon-reload && systemctl restart <bot>`.

Reference implementation: `MSKMSO/Codex-Agent/scripts/wire-tier2-dr-yoo-identifiers.sh` (used to wire `openclaw-codex.service`).

**Common gotcha:** if you run the fetcher manually as root the first time, the workspace file is owned by root and the service (running as `azureuser`) can't overwrite it on its next restart — ExecStartPre fails and the bot crash-loops. Always `chown azureuser:azureuser <workspace-dir>/DR_YOO_IDENTIFIERS.md` after the first manual run.

### What the identifier block says (always, every bot)

The block embedded/fetched into the system prompt includes:

- Legal name, preferred name, specialty
- NPI, CA medical license
- Practice address, mailing address
- Office phone, work email, practice org

And it includes an explicit refusal list — every bot must refuse to fill: bank routing/account numbers, credit card numbers, SSN, EIN/tax IDs, DEA registration, date of birth, driver's license, passwords, signatures.

### Verifying after wiring

Send the bot a test message in Teams: *"What's Dr. Yoo's NPI?"* — it should answer `1295774545` without prompting. If it asks Dr. Yoo for the number, the wiring didn't apply — check:

1. `systemctl is-active <name>-responder` — service running?
2. `grep DR_YOO_IDENTIFIERS_V2_VAULT <path-to-responder.py>` — marker present?
3. For Tier 2: `sudo -u <user> az keyvault secret show --vault-name SDN-YooVault --name dr-yoo-identifiers --query id -o tsv` — vault reachable from that user account?

### When you update the identifier values

1. Edit `MSKMSO/Virtual-Machines/scripts/dr-yoo-identifiers.json`, commit, push.
2. Run workflow `kv-set-dr-yoo-identifiers.yml` to push to the vault.
3. **Tier 2 bots:** restart each service — `systemctl restart <name>-responder`. The lru_cache forces a fresh fetch on next launch.
4. **Tier 1 bots:** run `tier1-embed-identifiers.yml`. The marker check skips already-embedded files unless you bump the marker version. To force a refresh, either bump the marker (`V1` → `V2`) in the script or hand-remove the marker block from each Tier 1 responder first.

### Bots that get NEITHER tier

None, currently. Tier 2 covers every authorized bot in the fleet. If you ever want to wall a bot off from Dr. Yoo's identifiers, the way to enforce that is to NOT add its responder service to `tier2-wire-vault-fetch.py`'s `SERVICES` list — the vault is open to any Linux account on the VM that has `az login --identity`, so scope is enforced by which responder code contains the fetcher.

---

## Failure-mode map (what each error code actually means)

| Symptom | Cause | Fix |
|---|---|---|
| Upload returns 201, GET returns 404 | Microsoft anti-abuse quarantine (you've uploaded too many times today) | STOP. Wait 24h. Do not retry. |
| Upload returns 409 Conflict | Same externalId already in catalog. The conflict body has the existing app id | Use the returned id; don't re-upload |
| Install returns 403 `blocked by app permission policy / AppType: Private` | Tenant Teams app permission policy blocks Private apps | Drive Teams Admin Center UI via EdgeBridge (see `reference_teams_app_install_admin_ui.md` in user memory) |
| Install returns 403 with NO message body | Token missing `TeamsAppInstallation.ReadWriteForUser.All` scope | Use the YooMD chat token, not AppPublisher |
| `bot-health-check.sh` shows `dir_owner: fail:root` | Provisioning ran as root | `chown -R azureuser:azureuser ~/.bot-dir ~/bot-files-*` |
| `bot-health-check.sh` shows `bf_auth: fail:HTTP-401` | `creds.json` has the secret ID instead of the secret value | Rotate per `docs/runbook-rotate-bot-secret.md` |
| `bot-health-check.sh` shows `uptime_bot: fail:Ns<30s` and `restarts_bot: fail:N/2min` | Bot is in crash loop | `journalctl -u <name>-bot.service -n 30` for the actual exception |

---

## Anti-patterns to never do

- **Tear down an existing bot to "make room" for a new variant.** Never. See the hard rule in "ASK FIRST" — leave existing bots running unless Dr. Yoo explicitly orders that specific bot torn down. The default for "user already has a bot of this variant" is keep-both-side-by-side (same pattern as Neil with Neil Claude + Neil Codex).
- **Delete-and-reupload to fix a manifest bug.** Use `POST /teamsApps/{id}/appDefinitions` for version bumps.
- **Retry an install that returned 403.** First verify the app exists with `GET /teamsApps/{id}`.
- **Trust `systemctl is-active`.** It's true ~30-50% of the time during crash loops. Use `bot-health-check.sh`.
- **Use the YooMD chat token for catalog uploads.** Use AppPublisher.
- **Skip the preflight policy check.** Build-then-install when the gate is closed wastes hours and leaves orphan state.
- **Mint a new client_secret without saving it to the vault as a backup first.** Lost secrets can't be recovered, only rotated.

---

## RECOVERY — When a previous publish got quarantined

When Phase 3.3's verify poll returns 404 and you've confirmed the upload was silently quarantined, the original externalId is now poisoned. Microsoft remembers it well enough to reject re-uploads (409) but won't surface it for use (404). The cooldown clears in roughly 24 hours, but you can publish a working bot **today** by giving the user a **new Teams app** that has nothing to do with the quarantined one.

The cooldown is keyed on **externalId**, NOT on displayName, NOT on botId, NOT on the Linux service. So:

- Generate a **fresh externalId UUID** (`uuidgen | tr 'A-Z' 'a-z'`). Microsoft has no record of it; the new upload sails through.
- **Keep the same `displayName`** (e.g. "Kaye Claude"). Microsoft does not deduplicate by displayName.
- **Keep the same `botId`** (the existing Entra appId). The bot service, the Linux user, and the responder don't change at all — this is purely a catalog-side recovery.

```bash
# Generate fresh externalId for the recovery manifest
NEW_EXT=$(uuidgen | tr 'A-Z' 'a-z')

# Build manifest.zip with NEW externalId, same displayName, same botId
python3 - <<PY
import json
m = json.load(open('manifest.json'))
m['id'] = "$NEW_EXT"      # fresh externalId
# All other fields unchanged: name, description, botId, accentColor, icons...
json.dump(m, open('manifest.json','w'), indent=2)
PY
zip -j recovery.zip manifest.json color.png outline.png

# Upload once via AppPublisher (Phase 3.2 rules still apply)
APP_PUBLISHER_TOK=$(...)
RESP=$(curl -sS -X POST https://graph.microsoft.com/v1.0/appCatalogs/teamsApps \
  -H "Authorization: Bearer $APP_PUBLISHER_TOK" \
  -H "Content-Type: application/zip" \
  --data-binary @recovery.zip)
RECOVERY_ID=$(jq -r .id <<< "$RESP")

# Verify (Phase 3.3 verify gate STILL applies — the new externalId could
# also fail if MSO is in a tenant-wide cooldown, but that's rare)
for i in $(seq 1 30); do
  STATUS=$(curl -sS -o /dev/null -w '%{http_code}' \
    "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/$RECOVERY_ID" \
    -H "Authorization: Bearer $APP_PUBLISHER_TOK")
  [ "$STATUS" = "200" ] && { echo "recovered"; break; }
  sleep 10
done
```

**DO NOT** delete the quarantined original. Leaving it alone causes no harm — without an active Entra app behind it, it does nothing. **Deleting it adds to Microsoft's anti-abuse counter and can deepen the cooldown for the entire tenant.** The orphan will eventually clear on Microsoft's side; we ignore it.

**DO NOT** reuse the quarantined externalId for any future re-upload of any bot. That UUID is dead forever from Microsoft's deduplication perspective.

After the recovery upload is verified (200 from GET), proceed to Phase 4 (Install) and Phase 5 (Health check) as normal, using `RECOVERY_ID` everywhere a teamsApp.id is needed.

---

## Identifier glossary (so you don't confuse them)

Microsoft uses the same field name `"id"` in different POST responses to mean different things. Confusion here is what trapped the Kaye recovery on 2026-05-14.

| Term | Where it lives | Shape | What it identifies |
|---|---|---|---|
| **Entra appId** / Microsoft App ID | Entra app registration | UUID | The bot's auth identity (Bot Framework JWT) |
| **botId** | Manifest's `bots[0].botId` | UUID | Same value as Entra appId, prefixed in conversations as `28:<appId>` |
| **teamsApp.id** | `GET /v1.0/appCatalogs/teamsApps/{id}` | UUID | The catalog-side identifier. Generated by Microsoft when the manifest is POSTed. **Different** from Entra appId. |
| **externalId** | `manifest.json`'s top-level `id` field | UUID | The identifier YOU put in the manifest. Microsoft deduplicates uploads on this. Locked forever after first successful publish. |
| **entitlementId** | `GET /v1.0/users/{aad}/teamwork/installedApps[].id` | base64 string | An install record. The `"id"` in install-side POST responses confusingly returns this, not the teamsApp.id. |
| **AAD Object ID** | Entra user object | UUID | A user's directory id. Goes in `ALLOWED_AAD_OIDS` on the per-bot env file. |

**Quick disambiguation:** if a UUID 404s on `GET /v1.0/appCatalogs/teamsApps/{id}` and resolves on `GET /v1.0/users/{aad}/teamwork/installedApps/{id}`, it's an entitlementId, not a teamsApp.id. The recovery procedure above won't work against an entitlementId — you need the actual teamsApp.id (often surfaced in a 409 Conflict body when a duplicate upload is attempted).

---

## Bot returns "Had trouble generating a reply"

Different problem from anything above. The bot publish succeeded and the user CAN reach it, but every reply is an error. See [`bot-empty-reply-diagnosis.md`](bot-empty-reply-diagnosis.md) — it walks through the three patterns (rate limit, broken `run_codex` from code injection, Graph 404 red herring) and exactly which logs distinguish them.

---

## Variant 3 — Foundry-backed bot (Fleet Architect pattern, added 2026-06-10)

A third variant exists alongside Claude- and Codex-based bots: the bot's brain is an **Azure AI Foundry agent** (project `agent-platform` on resource `mskmso-foundry`, rg `rg-mskmso-ai`, East US 2). First instance: **Fleet Architect** (appId `15472e97-43e5-46f8-9776-9ff0e6aafb19`, Bot resource `OpenClaw-FleetArchitect`, port 4005 on openclaw-vm).

Use this variant when the bot should run on metered Azure billing (no consumer Claude/Codex seat, no weekly caps, no OAuth-token expiry) and/or needs Foundry features (model router, per-agent token caps, Foundry observability, BAA-covered Azure OpenAI models for future PHI workloads).

**What's identical to the other variants:** Phase 0 preflight, Phase 1 (Entra app + Bot Service + Teams channel), systemd/nginx layout, manifest build, Phase 4 sideload flow, az-guard refresh, the never-tear-down rule.

**What diverges:**
- **No model account onboarding (decision 2 is moot).** The responder talks to the Foundry project's Responses API with the resource API key. Env file `/etc/claude-tokens/<short>.env` carries `FOUNDRY_API_KEY=<key1 of mskmso-foundry>` + `ALLOWED_AAD_OIDS=...` (empty value = org-wide; Bot Framework JWT still enforced).
- **Responder is plumbing only** (`fleet-architect-responder.py` is the template): poll activities.jsonl → POST `{project-endpoint}/openai/v1/responses` with `{"agent_reference":{"type":"agent_reference","name":"<agent>"}, "input":..., "previous_response_id": <per-conversation, state.json>}` → reply via Bot Connector (`https://api.botframework.com/.default` client-credentials with the bot's own appId/secret; activity posted to the incoming serviceUrl). On HTTP error with a previous_response_id, retry once without it (stale thread).
- **Behavior tuning happens in Foundry, not on the VM.** To change instructions/tools: POST a new agent version to `{project-endpoint}/agents/<agent>/versions?api-version=v1` (body needs `name` + `definition{kind:"prompt", model, instructions, tools}`). Do NOT edit responder prompts — there are none.
- **Two Graph/API gotchas hit on 2026-06-10:** (a) directory replication race — `addPassword` right after app creation can 404 (`Request_ResourceNotFound`); retry with ~12s backoff. (b) `POST /agents` with an existing name returns `conflict` — new versions go to `/agents/<name>/versions`.

**Catalog-publish slow-ingestion incident (2026-06-10/11), read before declaring quarantine:** the AppPublisher delegated upload (`POST /v1.0/appCatalogs/teamsApps`) returned an app id, then the app was invisible for HOURS — GET by id 404, absent from `externalId` and `displayName` filters for well past the playbook's 5-minute poll. It looked exactly like the silent anti-abuse quarantine. It wasn't: by the next morning the app sat in the catalog as `publishingState: published`, `distributionMethod: organization`, under the same id the upload returned. Lessons now baked into this playbook:
1. The 5-minute poll in 3.3 can produce a FALSE quarantine verdict. Before declaring quarantine, re-run the read-only catalog checks (by id AND `$filter=externalId eq '<manifest uuid>'`) after a few hours — and the next morning — before writing the upload off.
2. Do still honor the no-retry rule while waiting: a second programmatic upload of the same manifest while the first is mid-ingestion is what actually creates conflicts.
3. A manual admin-center upload attempted during/after ingestion fails with "there's already an app in the catalog with the same app ID" — that duplicate error is itself proof the original upload landed. Treat it as success, find the app in Manage apps, and verify its status there.
4. True quarantine (per the 2026-05 era incidents) still exists; the discriminator is time. Invisible after 24h = quarantined. Invisible after 10 minutes = probably just slow.


### Variant 3 standard capability: screenshot / image vision (added 2026-06-11)

Every Foundry-backed agent is built WITH image vision by default. The responder template (`/home/azureuser/agent-templates/_template-responder.py`, marker `IMAGE_SUPPORT_V1`) pulls image attachments from inbound Teams activities (pasted screenshots = `smba.trafficmanager.net/.../v3/attachments/...` fetched with the bot connector token; rich-card images = Graph `hostedContents` fetched with the app token), base64-encodes them, and sends them to the Responses API as `input_image` content parts. Caps: 4 images/message, 5 MB each. The router/GPT-5.x models are multimodal, so no model change is needed.

**Always on for every agent — including PHI agents** (images go to Azure OpenAI / Microsoft-hosted models inside the Microsoft BAA-covered boundary, so screenshots are HIPAA-compliant; no screenshot guardrail). **Provisioning inherits it automatically** — new agents are cloned from the canonical templates in `/home/azureuser/agent-templates/`, which already contain `IMAGE_SUPPORT_V1`. Do NOT strip it. Also add the agent-instruction line: "You CAN see images/screenshots that staff attach; only say you can't if none was provided."


---

## UNIVERSAL REQUIREMENTS — every agent, no exceptions

Every MSK MSO Foundry-backed agent (current and future) MUST have all of the following. New builds inherit them from the canonical templates in `/home/azureuser/agent-templates/`; do not strip any.

1. **Foundry-backed, Microsoft BAA boundary.** Brain is a Foundry agent on a direct GA Azure OpenAI deployment (default gpt-5-4-mini — reliable tool-calling + multimodal). Do NOT use model-router for tool-using agents (it intermittently 400s on tool calls — see note below). PHI agents use a pinned GA deployment. Everything stays inside the Microsoft HIPAA/BAA-covered ecosystem — no consumer AI, no non-Microsoft processors for PHI.
2. **Screenshot / image vision — ALWAYS ON, no guardrail.** Marker `IMAGE_SUPPORT_V1` in the responder. Applies to ALL agents including PHI/Prep agents. Screenshots are processed inside the Microsoft BAA-covered Azure OpenAI boundary, so they are HIPAA-compliant. There is NO `IMG_PRELAUNCH` gate — do not add one.
3. **Exact token + cost metering.** Per-call `usage.jsonl` logging input/output/total tokens; `build_usage_context()` computes exact dollars from the published Azure price table (incl. router markup). Agents answer cost/usage questions with real numbers, never "tell me which model," never invented figures.
4. **Transient-error retry.** `ask_foundry` retries on 400/408/429/5xx (3 attempts, backoff) so a momentary Foundry slowdown never surfaces "I had trouble reaching the Foundry agent."
5. **Table rendering.** Markdown pipe tables are converted to Adaptive Card tables before sending (reports/VM lists render as real grids, never collapsed text).
6. **@mention / tag individuals — REQUIRED.** Responder marker `MENTION_SUPPORT_V1`: it fetches the conversation roster (connector `/v3/conversations/{id}/members`), resolves any `<at>Name</at>` the model writes into real Teams mention entities (so the person is tagged AND notified), strips unresolved tags, and injects the taggable-name list into group-chat input. Agent instructions tell the model to tag the relevant person (asker, hand-off target) by default. Without this, an agent writing "@John" notifies no one.
7. **Group-chat support.** Manifest carries `groupChat` scope + `webApplicationInfo` + `authorization.resourceSpecific` (RSC) so the bot can be added to and respond in group chats (when @mentioned).
8. **Conversation continuity.** `previous_response_id` per conversation in `state.json`.
9. **Access gate.** `ALLOWED_AAD_OIDS` in the env file (empty = org-wide; JWT bot-framework auth always enforced regardless).
10. **Identity protection.** Bot AAD identity registered in `/etc/az-guard/protected-bot-ids` (`sudo /usr/local/sbin/az-guard-refresh-bot-ids` after creating).
11. **Distinct icon.** A meaningful color + outline icon in the practice palette (navy bg, cyan-blue elements, lime accent) — never the default "C".
12. **Plain-language style + standard report format** baked into the agent instructions; usage/VM reports follow the canonical `# | Name | VM | VM Size | Runtime | Sessions | Est. $/hr | Est. Cost` table.

PHI agents add: pinned GA Azure OpenAI model (not router), web search off, and a launch gate on the abuse-monitoring exemption for going hands-on with patient *workflows* — but screenshots/images are NOT gated (see item 2).


### ⚠️ Model choice: use gpt-5.4-mini for tool-using agents, NOT model-router (2026-06-12)

Discovered 2026-06-12: the Foundry **model-router deployment intermittently 400s on tool/function calls** ("There was an issue with your request") while plain chat works. The identical OpenAPI tool succeeds on a direct **gpt-5-4-mini** deployment. IT Helpdesk and Fleet Architect (both tool-using) were moved off the router to gpt-5-4-mini and tool calls became reliable. 

**Rule:** create the Foundry agent on a direct GA deployment (default **gpt-5-4-mini** — cheap, multimodal, reliable tools). Reserve model-router only for chat-only agents with no tools, and re-test tool-calling on the router before trusting it. PHI agents already use a pinned GA model, so they were unaffected.
