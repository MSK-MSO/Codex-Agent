# Bitwarden & eCW Access — Skill Guide for Claude Agents

This guide teaches a Claude agent how to (1) unlock and query the user's **Bitwarden** vault for secrets, and (2) log into **eClinicalWorks (eCW)** on the user's behalf. Adapt paths and credentials to your environment.

---

## Part 1 — Bitwarden Access

### 1.1 Why Bitwarden first
Bitwarden is the **single source of truth** for credentials. Before asking the user for any username, password, TOTP, or API key — check Bitwarden first.

### 1.2 Install the CLI
```
npm install -g @bitwarden/cli       # or: snap install bw / download static binary
bw --version
```

### 1.3 Login (one-time per host)
```
bw config server https://vault.bitwarden.com   # or self-hosted URL
bw login <user-email>
# enter master password when prompted
```
After `bw login`, the vault is **logged in but locked**. You need to **unlock** to read items.

### 1.4 Unlock and capture session token (every shell/session)
```
export BW_SESSION="$(bw unlock --raw)"   # prompts for master password, returns session token
```
The session token must be passed to every subsequent `bw` command (either via `--session "$BW_SESSION"` or by having it exported as `BW_SESSION`).

Keep the session token in memory only — never write it to disk.

### 1.5 Query the vault
```
bw sync                                          # refresh local cache
bw list items --search "ecw"                     # search by name
bw get item "eCW Login"                          # full JSON for one item
bw get password "eCW Login"                      # password field only
bw get username "eCW Login"                      # username field only
bw get totp "eCW Login"                          # current 6-digit TOTP code
```
Pipe through `jq` for custom fields:
```
bw get item "MSK MSO PACS" | jq -r '.login.uris[0].uri'
bw get item "eCW Login"    | jq -r '.fields[] | select(.name=="Practice URL") | .value'
```

### 1.6 Lock when done
```
bw lock
unset BW_SESSION
```
Always lock at the end of a task and clear `BW_SESSION` from the environment.

### 1.7 Rules of engagement
- **Never** print the master password, session token, or unlocked secrets back to the user verbatim unless they explicitly asked.
- **Never** commit `BW_SESSION` or credentials to disk, logs, or git.
- **Never** paste vault contents into third-party tools / chat / web forms.
- If a credential is missing from the vault, ask the user to add it — don't store it elsewhere.
- Treat every `bw` invocation as auditable on behalf of the user.

---

## Part 2 — eCW Access

### 2.1 Practice URL
- **Login URL:** `https://site586-bnt29viq.chartwire.com/mobiledoc/jsp/webemr/login/newLogin.jsp`
- **Practice host:** `site586-bnt29viq.chartwire.com`

### 2.2 Browser session (persistent headless Edge over CDP)
Reliable pattern: **persistent headless Edge** with a dedicated user-data-dir, kept alive across sessions so cookies/MFA trust persist. Drive it via Chrome DevTools Protocol (CDP).

Reference setup:
- Browser: headless Microsoft Edge
- CDP port: `18800`
- User data dir: `~/.config/ecw-chrome`
- Keepalive: e.g. `~/.openclaw/shared/ecw-keepalive.sh` — relaunches Edge with `--remote-debugging-port=18800 --user-data-dir=~/.config/ecw-chrome` if not running.

A Playwright driver attaches via `chromium.connect_over_cdp("http://127.0.0.1:18800")` and reuses the existing tabs/cookies.

### 2.3 Credentials — pull from Bitwarden
Don't keep eCW creds in a flat file when you can avoid it. Pull at runtime:
```
export BW_SESSION="$(bw unlock --raw)"
ECW_USER=$(bw get username "eCW Login")
ECW_PASS=$(bw get password "eCW Login")
# OTP comes from the user's MS Authenticator app — see 2.4
```
If Bitwarden is unavailable, fall back to a `chmod 600 ~/.ecw-credentials` file with `USERNAME` / `PASSWORD` / optional `TOTP_SECRET`.

### 2.4 MFA — Microsoft Authenticator (preferred)
eCW's primary 2FA is Microsoft Authenticator. The user opens MS Authenticator on their phone, reads the 6-digit code, and sends it to the agent. The agent fills it in.

**Do NOT brute-force passwords.** One failed login then stop — eCW locks the account after a few failures.

### 2.5 Login flow (three pages)
Use JS-clicks (`element.click()` in evaluate) — eCW buttons are sometimes overlaid and Playwright's `.click()` misses.
```
Page 1 — newLogin.jsp
  fill #doctorID with ECW_USER
  JS-click #nextStep

Page 2 — password page
  fill #passwordField with ECW_PASS
  JS-click #Login

Page 3 — OTPVerification.jsp
  fill #OTPCode with the 6-digit code from MS Authenticator
  JS-click #Submit
```
After step 3 the dashboard loads. Cookies persist in the user-data-dir so future runs usually skip to the dashboard.

### 2.6 Opening a patient chart
1. Click the **Action jellybean** (e.g. `#jellybean-panelLink65`; the number can vary — find by aria label "Action").
2. Fill `#searchText` with `LAST, FIRST` → Enter.
3. Click the matching row.
4. Click **Patient Hub**.

Open a progress note: Patient Hub → **Progress Notes** → tick the desired row's checkbox → **View**.

### 2.7 Keeping the session alive
- Cron/systemd keepalive every few minutes to ensure headless Edge is up.
- Periodically navigate to the dashboard URL inside the browser to defeat idle timeout.
- When eCW forces re-auth, ask the user for a fresh MS Authenticator code — never retry passwords.

### 2.8 Suggested file layout
```
~/.config/ecw-chrome/                       # persistent Edge profile (cookies)
~/.openclaw/shared/ecw-login.py             # Playwright driver, attaches to CDP 18800
~/.openclaw/shared/ecw-login-helper.sh      # idempotent wrapper
~/.openclaw/shared/ecw-keepalive.sh         # relaunches headless Edge if down
```
The driver should be idempotent: connect to CDP, detect which page the active tab is on (dashboard vs login vs OTP), and only run the steps still needed.

### 2.9 Things to never do
- Never attempt password login more than once on failure — account lock risk.
- Never paste eCW patient data into external systems / third-party tools / chat outside the clinician.
- Never run the browser non-headless on a shared display.
- Never share the user-data-dir contents (session cookies).
- Never store credentials in world-readable files.

---

## Part 3 — Operating principle
Bitwarden is the credential store; eCW is a stateful console you share with the clinician. Pull secrets from Bitwarden at runtime, stay logged into eCW as long as the session lasts, ask for an OTP only when forced, and never persist more than the minimum needed. Every patient action must be initiated by — and auditable to — the clinician user.
