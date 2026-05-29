# Creating a new Codex bot — end-to-end playbook

This is the canonical sequence for "Dr. Yoo wants a new Codex-style bot for `<user>`." Companion to `bot-creation-end-to-end.md` (which covers Claude/Anthropic bots).

A **Codex bot** = a Teams bot whose LLM backend is the OpenAI Codex CLI (signed into the MSO ChatGPT subscription). It is implemented as a **separate openclaw process** with its own profile, port, config, systemd unit, and Bot Framework registration. It is NOT a clone of a Claude bot (those use `claude --print`).

Why separate processes per bot: openclaw's Teams channel config only supports ONE `appId`/`appPassword` per instance. To host multiple Codex-named bots that all use the same MSO ChatGPT subscription, you run multiple openclaw processes with different Teams configs.

---

## Inputs you need before starting

- **Bot short-name**: `<short>` lowercase, e.g. `zahid-codex`, `neil-codex`
- **Bot display name**: e.g. "Zahid Codex", "Neil Codex" (Bot Framework displayName + Teams catalog name)
- **Target user UPN**: e.g. `zahidh@musculoskeletalmso.com`
- **Target user AAD object id**: `az ad user show --id <UPN> --query id -o tsv`
- **Bot Framework registration**: must already exist (or be created via Phase 1 of the Claude handbook). Capture:
  - `msaAppId` (the Bot Framework registration's appId)
  - `appPassword` (client secret; mint via `az ad app credential reset --id $APP_ID --years 2 --query password -o tsv`)
- **Next free internal port**: start at 4015 + N where N = count of existing openclaw-codex* services
- **Next free gateway port**: gateway uses two consecutive ports per instance; default 18793/18795. Use 18793+offset.

---

## PHASE 0 — Preflight

### 0.1 — Confirm canadacentral VM has capacity

```bash
ssh azureuser@20.63.0.12 'free -h && nproc'
```
Each openclaw process uses ~150 MB RSS. Confirm at least 200 MB free + 1 free CPU before adding another. (B2s = 4 GB / 2 vCPU; idle baseline ~1 GB / 5%.)

### 0.2 — Confirm Codex CLI is signed into MSO ChatGPT

```bash
ssh azureuser@20.63.0.12 'sudo cat /home/azureuser/.openclaw-codex/.openclaw/agents/main/agent/acp-auth/codex-source/auth.json | python3 -c "
import json,sys,base64
d=json.load(sys.stdin); t=d.get(chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(115),{}).get(chr(105)+chr(100)+chr(95)+chr(116)+chr(111)+chr(107)+chr(101)+chr(110),chr(46)).split(chr(46))[1]+chr(61)*3
print(json.loads(base64.urlsafe_b64decode(t)).get(chr(101)+chr(109)+chr(97)+chr(105)+chr(108)))
"'
```
Expected: `mso@musculoskeletalmso.com`. If different or empty, re-auth via `sudo -u azureuser /home/azureuser/.npm-global/bin/codex login --device-auth`.

### 0.3 — Confirm Bot Framework registration exists + appPassword is in vault

```bash
az resource show -g SDNeurosurgery-OpenClaw --resource-type "Microsoft.BotService/botServices" -n <bf-reg-name> --query "{name:name,appId:properties.msaAppId,ep:properties.endpoint}" -o table
az keyvault secret show --vault-name SDN-YooVault --name <short>-bot-client-secret --query value -o tsv | head -c 20
```
If secret missing, mint via `az ad app credential reset --id $APP_ID --years 2 --query password -o tsv` and `az keyvault secret set ...`.

---

## PHASE 1 — Create the openclaw profile config

The new openclaw instance gets its own profile directory `/home/azureuser/.openclaw-<short>/` containing `openclaw.json`. The profile inherits the codex agent's workspace + auth (via shared filesystem) but has its own Teams channel config.

### 1.1 — Clone existing openclaw.json with new appId/appPassword + port

```bash
ssh azureuser@20.63.0.12 'sudo -u azureuser bash -c "
NEW_SHORT=<short>
NEW_PORT=<next-free-port>   # e.g. 4016
APP_ID=<bf-msaAppId>
APP_PASSWORD=<bf-secret>

mkdir -p /home/azureuser/.openclaw-\$NEW_SHORT
cp /home/azureuser/.openclaw-codex/openclaw.json /home/azureuser/.openclaw-\$NEW_SHORT/openclaw.json

# Patch the new config: replace appId, appPassword, webhook port
python3 - <<PY
import json
p = '/home/azureuser/.openclaw-\$NEW_SHORT/openclaw.json'
d = json.load(open(p))
t = d['channels']['msteams']
t['appId'] = '\$APP_ID'
t['appPassword'] = '\$APP_PASSWORD'
t['webhook']['port'] = \$NEW_PORT
# Optionally tweak gateway ports if conflict
json.dump(d, open(p,'w'), indent=2)
PY
"'
```

### 1.2 — Share the codex agent state via symlink

The new profile should reuse the same agents directory (workspace, codex CLI auth, memory) so all Codex variants share one ChatGPT session.

```bash
ssh azureuser@20.63.0.12 'sudo -u azureuser bash -c "
NEW_SHORT=<short>
# Symlink the agents dir so codex CLI auth is shared
[ -e /home/azureuser/.openclaw-\$NEW_SHORT/.openclaw ] || \
  ln -s /home/azureuser/.openclaw-codex/.openclaw /home/azureuser/.openclaw-\$NEW_SHORT/.openclaw
"'
```

---

## PHASE 2 — systemd unit

### 2.1 — Drop unit at /etc/systemd/system/openclaw-`<short>`.service

```bash
ssh azureuser@20.63.0.12 'sudo bash -c "
NEW_SHORT=<short>
NEW_PORT=<next-free-port>
cat > /etc/systemd/system/openclaw-\$NEW_SHORT.service <<EOF
[Unit]
Description=OpenClaw Codex Bot ($NEW_SHORT)
After=network-online.target openclaw-codex.service
Wants=network-online.target
Requires=openclaw-codex.service

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser
ExecStartPre=/home/azureuser/.openclaw-codex-fetch-identifiers.sh
ExecStart=/usr/bin/openclaw --profile \$NEW_SHORT
Restart=always
RestartSec=10
Environment=HOME=/home/azureuser

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable openclaw-\$NEW_SHORT.service
systemctl start openclaw-\$NEW_SHORT.service
sleep 5
systemctl is-active openclaw-\$NEW_SHORT.service
"'
```

### 2.2 — Verify webhook port is listening

```bash
ssh azureuser@20.63.0.12 'sudo ss -tlnp | grep "<NEW_PORT>"'
```

---

## PHASE 3 — nginx route on canadacentral

### 3.1 — Add location block to /etc/nginx/sites-enabled/default

```bash
ssh azureuser@20.63.0.12 'sudo bash -c "
NEW_SHORT=<short>     # e.g. zahid (used in URL path /zahid/api/messages)
NEW_PORT=<next-free-port>
PATH_NAME=<url-name>  # bot URL segment, e.g. zahid, neil

cat >> /tmp/nginx-block <<EOF

    location = /\$PATH_NAME/api/messages {
        proxy_http_version 1.1;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_read_timeout 300;
        proxy_send_timeout 300;
        proxy_pass http://127.0.0.1:\$NEW_PORT/api/messages;
    }
EOF
# Splice into the server block (before final })
python3 -c \"
import sys
p = '/etc/nginx/sites-enabled/default'
s = open(p).read()
new = open('/tmp/nginx-block').read()
idx = s.rstrip().rfind('}')
open(p,'w').write(s[:idx]+new+s[idx:])
\"
nginx -t && systemctl reload nginx
"'
```

---

## PHASE 4 — Update Bot Framework registration endpoint

```bash
az resource update -g SDNeurosurgery-OpenClaw --resource-type "Microsoft.BotService/botServices" \
  -n <bf-reg-name> \
  --set properties.endpoint="https://codex.musculoskeletalmso.com/<url-path>/api/messages" \
  --set properties.displayName="<Bot Display Name>"
```

---

## PHASE 5 — Verify end-to-end

### 5.1 — Direct HTTP probe

```bash
curl -sS -o /dev/null -w "%{http_code}\n" --max-time 8 \
  -X POST "https://codex.musculoskeletalmso.com/<url-path>/api/messages" \
  -H "Content-Type: application/json" -d '{"type":"ping"}'
```
Expected: **HTTP 401** (Bot Framework rejecting unsigned JWT — correct for an authenticated endpoint).

### 5.2 — Process inventory

```bash
ssh azureuser@20.63.0.12 'ps -ef | grep "openclaw --profile" | grep -v grep'
```
Should see one line per Codex variant.

### 5.3 — Send a test message in Teams

Hand the manifest zip to the owner per Section 6.3 (user self-sideload — do NOT install via Graph) and have them send "hi". Check `journalctl -u openclaw-<short>.service` for the request handling. Codex CLI session is shared, so the reply quality is identical to the main Codex bot.

---

## Rollback

```bash
sudo systemctl disable --now openclaw-<short>.service
sudo rm /etc/systemd/system/openclaw-<short>.service
sudo rm -rf /home/azureuser/.openclaw-<short>
sudo sed -i "/location = \/<url-path>\/api\/messages/,/^    \}\$/d" /etc/nginx/sites-enabled/default
sudo systemctl reload nginx
az resource update -g SDNeurosurgery-OpenClaw --resource-type "Microsoft.BotService/botServices" -n <bf-reg-name> --set properties.endpoint="<dead-url>"
```

---

## Common gotchas

- **Don't reuse the main Codex's appId** for variants. Bot Framework JWT validation will fail if the appId doesn't match the registration sending the message.
- **Gateway ports**: if two openclaw instances both try 18793, the second fails. Configure unique gateway ports per profile via `gateway.host` in openclaw.json (or accept that subsequent instances may fail to bind gateway and only handle webhook).
- **Codex CLI session contention**: all Codex variants share `/home/azureuser/.openclaw-codex/.openclaw/agents/main/.../auth.json`. Re-auth on one affects all.
- **MSO ChatGPT quota**: all Codex variants pull from one subscription. Heavy use by one variant slows all.

---

## Sentinel: CODEX_BOT_HANDBOOK_2026_05_25


---

## Phase 1.6 — Copy agents/codex/ from main profile (auth-profiles.json)

The msteams + codex plugin install creates the profile but NOT the codex agent auth resolution. Without this step the bot replies with "Missing API key for provider openai-codex".

```bash
mkdir -p /home/azureuser/.openclaw-SHORT/agents/codex
cp -rp /home/azureuser/.openclaw-codex/agents/codex/. /home/azureuser/.openclaw-SHORT/agents/codex/
chown -R azureuser:azureuser /home/azureuser/.openclaw-SHORT/agents
sudo systemctl restart openclaw-SHORT.service
```

(replace SHORT with your bot's short name)

**Side effect:** each profile then has an independent COPY of auth-profiles.json. If codex CLI re-auth happens on the main profile, you must re-copy to all variants. For long-term sharing, consider symlinking instead of copying — but that requires verifying openclaw is happy with shared write access.

## Phase 1.7 — Gateway port collision (optional but recommended)

If two openclaw profiles try to bind the same gateway port (default 18793), the second fails with `Port 18793 is already in use`. Set an explicit `gateway.port` in the profile's openclaw.json:

```python
import json
p = '/home/azureuser/.openclaw-SHORT/openclaw.json'
d = json.load(open(p))
d.setdefault('gateway', {})['port'] = 18813   # pick a unique unused port
json.dump(d, open(p, 'w'), indent=2)
```

The msteams plugin will pick its own listen port from `channels.msteams.webhook.port`. Browser plugin uses the next port after gateway.

## Phase 1.8 — Pick unique URL path

The Bot Framework endpoint URL uses a path segment (e.g. `/zahid-codex/`). If you reuse a path that another bot/legacy registration uses, that legacy mapping wins. Always use a unique path. Convention: `/<bot-short>/api/messages`.


---

## Phase 6 — Lock down to a single user (optional)

If the bot should be usable by ONLY the target user (no one else, including Dr. Yoo), apply all four layers below. Skip any one and the bot leaks.

### 6.1 — openclaw msteams allowlist (server-side gate)

Patch the profile's `openclaw.json` so the bot only responds to specific AAD object IDs:

```python
import json
p = '/home/azureuser/.openclaw-SHORT/openclaw.json'
d = json.load(open(p))
t = d['channels']['msteams']
t['dmPolicy']       = 'allowlist'
t['allowFrom']      = ['<owner-AAD-object-id>']
t['groupPolicy']    = 'allowlist'
t['groupAllowFrom'] = ['<owner-AAD-object-id>']
json.dump(d, open(p, 'w'), indent=2)
```

Restart `openclaw-SHORT.service`. This rejects messages from anyone NOT on the allowlist, regardless of who has the bot installed.

### 6.2 — Delete Teams catalog entry

Removes the bot from the org-wide Teams app store. Anyone trying to install will get "not found".

```python
import urllib.request, subprocess
cat_tok = subprocess.run(['/home/azureuser/yoomd-appcatalog-token.sh'], capture_output=True, text=True).stdout.strip()
TEAMS_APP_ID = '<from /v1.0/appCatalogs/teamsApps?$filter=externalId eq ...>'
req = urllib.request.Request(
    f'https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{TEAMS_APP_ID}',
    headers={'Authorization':'Bearer '+cat_tok}, method='DELETE')
urllib.request.urlopen(req)
```

### 6.3 — Hand the manifest zip to the owner for self-sideload

**Standing rule (2026-05-29, Dr. Yoo):** do NOT push the install via Graph and do NOT publish the zip to the tenant catalog for per-user bots. Instead, **deliver the manifest zip to the owner in Teams chat with step-by-step sideload instructions, and let them upload it themselves.**

Why this changed:
- Every programmatic upload risks tripping Microsoft's anti-abuse cooldown (~24h silent quarantine). User-driven sideload via "Upload a custom app" sidesteps it entirely.
- The owner ends up owning the install, so removal/reinstall is in their hands — no Graph token plumbing needed when something goes wrong.
- The tenant Teams App Permission Policy gate (the 2026-05-11 wall) doesn't apply to a user uploading a custom app into their own personal scope.

#### 6.3.a — Deliver the manifest zip to the owner in Teams

Use a sender bot (e.g. `mskmso-anthropic-upload-to.sh`) to post `manifest.zip` directly into the owner's 1:1 chat. **Do not email it. Do not link a SharePoint URL.** The zip must arrive as a Teams attachment so the owner can download it with one tap.

```bash
bash /home/azureuser/mskmso-anthropic-upload-to.sh "<owner-upn-or-chat-id>" manifest.zip "Your <Firstname> Codex bot — upload instructions below"
```

#### 6.3.b — Post the upload instructions in the SAME chat, right after the zip

Paste the following verbatim (substitute `<Firstname> Codex` for the bot's display name). Keep it as one message so the owner has the zip and the steps side-by-side.

> **How to install your `<Firstname> Codex` bot (one-time, ~30 seconds):**
>
> 1. **Download the zip** above to your computer (or phone — works on both).
> 2. In Teams, click **Apps** in the left sidebar (the grid icon).
> 3. Click **Manage your apps** at the bottom of the Apps panel.
> 4. Click **Upload an app**.
> 5. Click **Upload a custom app** (it may say *Upload for me* on some tenants).
> 6. Select the **zip file** you just downloaded.
> 7. When Teams asks, click **Add** to install it for yourself.
>
> That's it — the bot will appear in your chat list. Say "hi" to test it.

#### 6.3.c — Wait for the owner to confirm install, then verify

Don't proceed to 6.2 (catalog delete) until the owner sends a message that the bot replies to. The server-side allowlist (6.1) is already in force, so only the owner can talk to it anyway. If the owner has trouble with step 5 ("Upload a custom app" greyed out), that means their tenant Teams App Permission Policy blocks custom uploads for them — escalate to Dr. Yoo; don't try to push via Graph as a workaround.

### 6.4 — Manual uninstall from other users (Dr. Yoo, etc.)

Graph's `DELETE /users/{upn}/teamwork/installedApps/{id}` with a delegated YooMD token returns **HTTP 403** for personal app uninstalls — Microsoft requires the user themselves to remove it. Two paths:

- **The user manually removes**: in Teams, right-click the bot's chat → "Uninstall app".
- **OR**: use the Teams Admin Center → Manage apps → find app → bulk remove. Requires admin.

The server-side allowlist (6.1) already rejects their messages, so leaving the install in place is harmless functionally — just visually present.

### 6.5 — Order matters

Do them in this order so the owner doesn't lose access mid-process:

1. Patch openclaw config (6.1) + restart service
2. Hand zip + instructions to the owner (6.3) — wait for confirmation that they sideloaded it and can message the bot
3. Delete catalog entry (6.2), if it was ever published — for per-user bots the default is no catalog publish, so this step is usually a no-op
4. (Optional) ask each non-owner installer to uninstall manually (6.4)


---

## Phase 0.4 — Add swap to canadacentral (mandatory before 2nd+ openclaw instance)

Each openclaw process uses ~400 MB RSS at idle and spikes during model prewarm. With 3+ instances on a B2s (4 GB RAM, no default swap), the event loop saturates (`liveness warning: eventLoopDelay > 4000ms`) and incoming Bot Framework messages get queued or dropped during prewarm windows.

```bash
ssh azureuser@<canadacentral-ip> 'sudo bash -c "
if ! swapon --show | grep -q swap; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo /swapfile none swap sw 0 0 >> /etc/fstab
fi
"'
```

## Phase 0.5 — Stagger startup of multiple openclaw services

If you have N>1 openclaw instances on the same VM, set `After=openclaw-codex.service` AND `Requires=openclaw-codex.service` in each new service's `[Unit]` section so the main one boots first. Also consider `ExecStartPre=/bin/sleep 30` on the 2nd+ instances to space out prewarm.

## After multi-instance setup — known recovery gotcha

When you restart any openclaw instance, in-flight Bot Framework replies (in "send_attempt_started" state) get marked unrecoverable. The bot's reply is lost — the user must re-send the original message. Look for log entries like:

```
[delivery-recovery] Retry failed for delivery <uuid>: delivery state is send_attempt_started; refusing blind replay without adapter reconciliation
```

If you restart during active conversations, tell the affected users their last message needs to be resent.

---

## Phase 0.6 — AAD app secret-storage gotcha (mandatory before "verify")

When you create a Bot Framework registration via `az bot create --kind webapp`, Azure auto-creates an AAD app registration but **does NOT auto-create the service principal** in your tenant. The bot will receive inbound messages but every outbound reply fails with:

```
msteams send failed (HTTP 401): AADSTS7000229: missing service principal
```

OR

```
AADSTS7000215: Invalid client secret provided
```

if the secret was corrupted in transit.

### Required steps after `az bot create`:

1. **Create the SP explicitly:**
   ```bash
   az ad sp create --id <appId>
   ```

2. **Add a client secret** (use `az ad app credential reset` or Portal). Note the **value** field — only shown ONCE.

3. **Store secret in Key Vault — beware of leading characters.** AAD client secrets sometimes begin with characters that the shell mis-interprets (digit-like, dot, backslash). Always store using `--value @file` form or quote-protect:
   ```bash
   echo -n 'PASTE_SECRET_HERE' > /tmp/sec
   az keyvault secret set --vault-name SDN-YooVault --name <bot>-client-secret --file /tmp/sec
   rm /tmp/sec
   ```
   NOT this (loses leading char if it begins with `\<digit>` or similar):
   ```bash
   az keyvault secret set ... --value "$VAR"   # ← may corrupt
   ```

4. **Verify the round-trip BEFORE booting openclaw:**
   ```bash
   # Compare KV first-3 chars to AAD's "hint"
   az ad app credential list --id <appId> --query "[].hint" -o tsv
   az keyvault secret show --vault-name SDN-YooVault --name <bot>-client-secret --query value -o tsv | head -c 3
   # They MUST match exactly.
   ```

5. **Mint a test token** to confirm secret + SP both work:
   ```bash
   curl -sS -X POST "https://login.microsoftonline.com/$TENANT/oauth2/v2.0/token" \
        -d "client_id=$APPID&client_secret=$SECRET&grant_type=client_credentials&scope=https://api.botframework.com/.default" \
        | jq .access_token | head -c 30
   ```
   Should print `eyJ0...` (a JWT). Anything else = stop and fix before proceeding.

If you skip any of 1–5, the bot will appear to receive Teams messages (nginx 200) but every reply will silently fail. Logs show `delivery state is send_attempt_started; refusing blind replay`.
