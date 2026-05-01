# Nexus Provisioning Engine

Nexus is an enterprise-grade Slack provisioning engine. Maps organizational roles to digital workspace architectures. Configuration-driven, state-aware, and idempotent.
**GOAL** Automate the onboarding of new hires/additions into a pre-existing SLACK ecosystem. Setup once. Scale infinitely.
---

## 1. Slack App Configuration

You must provision a dedicated Slack App to generate security tokens.

1. Create a new app at [Slack API](https://api.slack.com/apps).
2. Navigate to **OAuth & Permissions**.
3. Add the following **Bot Token Scopes**:
   * `channels:join`
   * `channels:manage`
   * `groups:write`
   * `groups:read`
   * `users:read`
   * `users:read.email`
   * `chat:write`
   * `im:write`
4. Click **Install to Workspace**.
5. Copy the **Bot User OAuth Token** (`xoxb-`).

---

## 2. Private Channel Authorization

**CRITICAL:** Slack security protocols prevent bots from discovering or joining private channels dynamically. 

You must manually authorize the bot for every private channel defined in your configuration:
1. Open the target private channel in the Slack client.
2. Execute `/invite @Nexus` (or your specific bot name).

Failure to execute this step will result in a `channel_not_found` API error during provisioning.

---

## 3. Environment Setup

Nexus utilizes a zero-footprint configuration strategy. Organizational mapping occurs strictly within the environment file.

1. Clone the repository.
2. Copy the template:
   ```bash
   cp .env.example .env
Define your credentials and channel mappings in .env:

Bash
TENANT_ACME_SLACK_BOT_TOKEN=xoxb-your-token-here
TENANT_ACME_CHANNELS_ENGINEERING=C0XXXXXXXXX, C0ZZZZZZZZZ
TENANT_ACME_CHANNELS_ADMIN=C0XXXXXXXXX,C0YYYYYYYYY
Note: Retrieve Channel IDs by right-clicking the channel in Slack -> View channel details -> Scroll to the bottom.
IMPORTANT: You can add as many roles as you want with as many channels per role as you DESIRE. Format is : TENANT_ACME_CHANNELS_YourDesiredROLE=C0CHANNELID1,C0CHANNELID2, ETC

## 4. Execution

Execute the provisioning engine via the CLI. The engine validates the role against `.env`, resolves the Slack UID via email, processes channel invitations, and dispatches a welcome DM.

```bash
python3 main.py --tenant ACME provision \
  --user-id emp-8492 \
  --email user@company.com \
  --first-name Atakan \
  --last-name Turgut \
  --role admin

**NOTE**
The --user-id must be unique per employee to maintain idempotency in the state file. Do not use manual counters (e.g., u-001, u-002) as they break at scale. Use a deterministic corporate identifier such as an HR Employee ID (emp-8492) or an email prefix (atakan.turgut)

## 5. State Management
Nexus is idempotent. It tracks successful executions in data/state.json.

Duplicate Prevention: Rerunning the command for a provisioned --user-id skips the Slack API payload.

Failure Recovery: Failed runs do not commit to state and will re-attempt on the next execution.

Force Retry: To wipe memory and force a complete re-run for all users, delete the state file:

Bash
rm data/state.json
