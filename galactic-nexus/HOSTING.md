# Galactic Nexus online hosting

This build runs the existing Discord bot on an always-on cloud worker. Once deployed and verified, your PC can be switched off. There is no website, public domain, extra XP bot, or separate database service to manage.

**Current status (2026-09-14):** the GitHub repository and existing Railway worker are connected. The image builds, but hosted startup is blocked by the missing persistent volume. Railway's connected controls accepted multiple volume changes without showing a live volume afterward. Do not treat a successful build or accepted change as proof that Discord is online. Live configuration and founder testing remain pending.

### Read-only Discord diagnosis

Temporarily use start command `python -m nexus.diagnose` and restart policy `NEVER` for one diagnostic deployment. It uses the existing private `NEXUS_TOKEN` variable to check the configured guild owner, role hierarchy, required setup permissions, and missing channels. It does not write state, connect a database, send messages, change Discord settings, or start XP workers. A completed diagnostic is not a running bot.

This command is separate from hosted setup: `python -m nexus.hosted` continues to require real persistent storage for every action. After diagnosis, restore that start command and restart policy `ON_FAILURE` with 5 retries. Attach and verify `/data`, run `NEXUS_ACTION=plan`, review the saved plan, then configure and run as described below.

## Hosting plan

Use one Railway service and one persistent volume. Railway's Hobby plan has a **$5/month minimum**, including $5 of resource usage; usage beyond that is additional. The proposed initial budget is **$10/month**, subject to your approval and the actual billing controls in your workspace. This is a spending target, not a measured cost or an uptime guarantee. [Railway pricing](https://docs.railway.com/pricing/plans)

Railway also offers a $0 plan with a small resource credit for experimentation. Available free/trial credit can be checked first, but it should not be treated as an unlimited always-on hosting promise. The paid Hobby option is the proposed ongoing setup. Your original project brief requires asking before purchasing hosting, so connecting Railway alone does not authorize a subscription. [Railway plan comparison](https://docs.railway.com/pricing)

| Setting | Value |
| --- | --- |
| Project | Galactic Nexus |
| Service | galactic-nexus-bot |
| Build | Included `Dockerfile` using Python 3.12 |
| Source root | Folder containing `Dockerfile`, `nexus`, and `config.example.json` |
| Start command | `python -m nexus.hosted` (already set in Dockerfile) |
| Replicas | 1 |
| Persistent volume | `nexus-state`, mounted at `/data`; use the connected workspace's verified size allowance (512 MB reported on 2026-09-14) |
| Serverless / sleeping | Disabled |
| Restart policy | On Failure, 5 retries |
| HTTP healthcheck / public domain | None; this is a Discord background worker |
| Cron schedule | None |
| Public launch | Disabled; private founder testing only |

The volume must be attached before starting. The worker refuses temporary container storage. Railway mounts volumes at runtime, so setup runs as a service action, not a build or pre-deploy command. [Railway volumes](https://docs.railway.com/volumes)

Keep Serverless disabled. A spending hard limit, if enabled, can stop the service when reached; choose it with the owner. [Railway cost controls](https://docs.railway.com/pricing/cost-control)

## Deploy without keeping your PC running

Before creating paid resources, confirm the hosting budget. Create the dedicated service, upload this source or connect its private repository, and attach the volume. The Docker build installs the dependency and runs the test suite. Do not upload the token or a populated database as source code.

In the service's **Variables**, set:

| Variable | Value |
| --- | --- |
| `NEXUS_TOKEN` | Existing Discord bot token, entered privately in Railway |
| `NEXUS_DATA_DIR` | `/data` |
| `NEXUS_ACTION` | `plan` for the first deployment |

No token is included in this package. Do not put it in ChatGPT, a repository, the start command, or build arguments. Railway supplies `RAILWAY_VOLUME_MOUNT_PATH` when the volume is attached; do not create it manually to bypass the volume check.

### 1. Check the existing server

Deploy with `NEXUS_ACTION=plan`. The worker verifies the Discord owner, role hierarchy, and required permissions, saves a server snapshot and configuration plan on the volume, and exits without applying Discord changes. This setup-only deployment finishes; it is not the running bot yet.

If permissions are missing, the log lists their exact names. In Discord **Server Settings → Roles → Galactic Nexus → Permissions**, enable those permissions and save. The earlier instructions omitted **Create Public Threads**, **Create Private Threads**, and **Send Messages in Threads**. Setup also needs Manage Roles, Manage Channels, Manage Server, and normal message/audit access. Member-role repairs may require additional permissions, which the check lists. Keep Administrator off and the bot below Moderator and above Jedi Grand Master.

### 2. Apply the reviewed setup in the cloud

After reviewing the plan, set:

| Variable | Value |
| --- | --- |
| `NEXUS_ACTION` | `configure` |
| `NEXUS_SETUP_CONFIRMATION` | `CONFIGURE PRIVATE TEST SERVER` |

Redeploy the same service with the same volume. This applies the reviewed private setup and saves actual role/channel IDs. It preserves messages, duplicate construction channels, progression, and governance assignments. Failures identify the exact operation; keep the volume and correct that issue before retrying.

After **Configuration passed**, remove the temporary Discord permissions listed in the log. Keep Manage Roles, View Audit Log, View Channels, Send Messages, Embed Links, Attach Files, and Read Message History. Manage Channels and Manage Server must be off before normal startup.

### 3. Start the continuously running bot

Set `NEXUS_ACTION=run`, remove `NEXUS_SETUP_CONFIRMATION`, and redeploy. Keep the token and volume unchanged. Confirm the log says:

`Galactic Nexus is online in PRIVATE TEST MODE. Use /join in Discord.`

Confirm the bot appears online and slash commands respond. A container showing “running” alone does not prove successful Discord authentication and permission validation.

Run **one cloud worker only** and close any old PC bot process. The client handles Discord reconnections. Failed workers exit with an error so Railway can restart them; repeated configuration failures stop after the configured retries and require correction. A host shutdown closes the client/database and releases the volume lock.

## Saved state and migration

| Location | Purpose |
| --- | --- |
| `/data/config.local.json` | Verified roster, role/channel IDs, and settings |
| `/data/data/test.sqlite3` | Progression, audit history, receipts, and pending deliveries |
| `/data/backups/` | SQLite backups and server-before snapshots |
| `/data/review/` | Configuration plan and permission check |

Every deployment reuses these files. Progression is not rebuilt from the example configuration. SQLite backups occur at normal startup and every six hours and stay on the same volume. Download copies or enable provider volume backups after reviewing any storage charges to cover a lost volume too. Never replace a populated database with an empty one.

If you already earned test XP on your PC, stop that bot and preserve its entire `config.local.json`, `data`, and `backups`. Transfer them into the matching locations above **before the first cloud run**. Use a completed SQLite backup, or copy the database and any WAL files only after the old process fully stops. Keep private state out of Docker build context and source control. If only setup was attempted and no bot progression was started, the host can initialize the supplied private-test configuration.

For manual backups while the worker is stopped, run `python -m nexus.hosted backup`. It refuses to create an empty database. Use Railway's volume browser or download commands to retrieve files. [Volume file access](https://docs.railway.com/volumes#manage-volume-files)

## Verify the hosted deployment

1. Close the PC launcher and switch your PC off. From Discord on your phone, run `/profile` or `/dashboard` and confirm a response.
2. Complete `/join` and the checks in `docs/founder-test-checklist.md`.
3. Note a test profile's XP and faction. Restart the Railway service and confirm the same state returns after the online log appears.
4. Confirm a new SQLite backup exists and the permission check succeeded.
5. Invite the founders when ready and assign Founding Council manually. Public community launch still requires the pre-launch review.

## Validation completed here

67 offline checks are verified, covering state across restart, preview-only setup, required storage, private mode, secret handling, duplicate-worker exclusion, backups, and a real Linux SIGTERM shutdown. The Dockerfile runs the suite during cloud build. A local Docker engine and Railway deployment commands were unavailable in this session. Image build, live credentials, permissions, spending controls, and hosted restart must be verified on Railway before calling the bot online.
