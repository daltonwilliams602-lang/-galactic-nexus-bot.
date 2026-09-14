# Start here, Dalton

**For the hosted version that works while your PC is off, use [HOSTING.md](HOSTING.md).** These Windows instructions remain available for local setup and testing.

**Setup fix v1.2. Your bot connected successfully, but the configuration run stopped with Discord error 50013 (Missing Permissions).** Configuration, normal bot startup, and founder checks still need to finish. Community invitations remain closed until founder testing and your explicit launch approval.

## Updating your existing folder after the permission error

Close the launcher. Extract this ZIP, then copy the contents of its `galactic-nexus` folder into your existing `galactic-nexus` folder. Choose **Replace the files in the destination**. Keep your existing `config.local.json`, `data`, and `backups`; they are not included in the ZIP and must not be deleted. Use the same bot application and token.

In Discord, open **Server Settings → Roles → Galactic Nexus → Permissions**. In addition to the permissions already enabled, temporarily enable **Create Public Threads**, **Create Private Threads**, and **Send Messages in Threads**, then **Save Changes**. Leave Administrator off and keep the bot below Moderator.

Run **Setup-Nexus.cmd** (expect 67 tests and OK; the Linux signal test skips on Windows), then **Start-Nexus.cmd → 1**. The menu should show **SETUP FIX v1.2**. Paste the token and press Enter; hidden input is normal. If the permission check lists additional permissions needed for role repairs, enable those exact permissions on the bot role, save, and reopen option 1. The check makes no Discord changes before it passes.

Type `CONFIGURE PRIVATE TEST SERVER` when prompted. After **Configuration passed**, turn off the temporary permissions listed by the launcher, then reopen **Start-Nexus.cmd → 2**. If Discord rejects another operation, the updated launcher prints the exact role, channel, or setting and error code. Keep that message; retrying does not require deleting the folder or database.

## 1. Download and extract this package

Extract the entire ZIP to a folder you will keep, such as `Documents/Galactic-Nexus`. Run the files from the extracted folder, not from inside the ZIP. Keep the folder on your Windows PC rather than in a folder simultaneously used by another bot computer.

Install a supported Python 3 version, **3.12 or newer**, from [Python's official Windows downloads](https://www.python.org/downloads/windows/). Include the Python launcher when the installer offers it. The setup script uses `py -3` to select your installed Python.

## 2. Create the bot application

If Galactic Nexus is already installed and its token connects, keep that application and continue with its existing role. Do not create another bot for this update.

Open the [Discord Developer Portal](https://discord.com/developers/applications) while signed into your owner account. Create an application named **Galactic Nexus** and review/accept the terms yourself. Open its **Bot** page. Enable **Server Members Intent** and **Message Content Intent**, save, and generate the bot token using the token controls. Store it privately in your password manager; do not send it in chat. See [Discord's official application setup](https://docs.discord.com/developers/quick-start/getting-started) for these portal steps.

Keep the bot private to your own server. Leave OAuth2 Code Grant off; this package does not use an interactions endpoint or inbound web server.

Under **OAuth2 → URL Generator**, choose the `bot` and `applications.commands` scopes. For this one-time setup, select **Manage Roles, Manage Channels, Manage Server, View Audit Log, View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Create Public Threads, Create Private Threads, and Send Messages in Threads**. Do not select Administrator. Open the generated URL and authorize it specifically for **THE GALACTIC NEXUS**, server ID **1548550668900372560**. The bot installation process is described in the [discord.py bot account guide](https://discordpy.readthedocs.io/en/stable/discord.html).

Manage Server is temporary for native SFW settings and AutoMod. Manage Channels and the three thread permissions are temporary for configuration. Discord requires a bot to hold permissions it allows or denies in [channel overwrites](https://docs.discord.com/developers/resources/channel#edit-channel-permissions), and permissions it grants to [roles](https://docs.discord.com/developers/topics/permissions#permission-hierarchy). If a role needs repair, setup lists any additional permissions needed before making changes. Manage Roles remains for progression; remove the temporary permissions after configuration.

## 3. Set the role order

In Discord **Server Settings → Roles**, move the bot's managed **Galactic Nexus** role:

**below Moderator and above Jedi Grand Master.**

Keep Server Owner, Founding Council, Admin, Senior Moderator, and Moderator above it. All Jedi/Sith progression, faction, Council, prestige, event, Member, and Founder Tester roles go below it.

Assign **Server Owner** and **Founding Council** to your account. These are native manual assignments; the bot deliberately cannot grant governance roles. When the other verified founders join later, you assign them Founding Council yourself.

## 4. Run configuration once

Double-click **Setup-Nexus.cmd**. It creates a local Python environment, installs the pinned bot dependency, and runs the offline checks. If a step fails, it stops; keep the error message and ask for help before continuing.

Double-click **Start-Nexus.cmd**. Choose **1 — Configure/check server**. Paste the bot token at the hidden prompt and press Enter. Nothing appears as you paste; that is normal.

The configuration run checks the server and actual owner, reads the existing roles, saves a server snapshot, and writes `configuration-plan.json`. It then asks you to type:

`CONFIGURE PRIVATE TEST SERVER`

This applies the reviewed server configuration. It repairs private/read-only permissions, fills missing channels, preserves duplicate construction channels under renamed founder-only access, sets native SFW/AutoMod protections, and fills the role/channel ID maps. It does not delete messages or progression, assign governance, send invites, or launch publicly.

Wait for **Configuration passed**. The generated `permission-check.json` records the technical check against live API results. If the run stops, keep its message; it is safe to rerun after a targeted correction. Do not delete the project or database to retry.

In Discord, **remove the temporary permissions listed by the launcher from the bot role**, including Manage Channels, Manage Server, and the three thread permissions. Keep Manage Roles, View Audit Log, View Channels, Send Messages, Embed Links, Attach Files, and Read Message History. The normal bot refuses to run with Administrator, Manage Channels, or Manage Server.

## 5. Start the private bot

Open **Start-Nexus.cmd** again, choose **2 — Start bot**, and paste the token privately. Keep the window open.

Wait for **Galactic Nexus is online in PRIVATE TEST MODE**. If startup refuses a permission mismatch, correct it through configuration instead of bypassing the check. Guild ownership and role IDs are validated before commands are registered.

In Discord, try `/join` with both confirmations set to true. Press Confirm on the preview, then use `/path` and choose **Sith / Dark Side**. Use `/profile` to verify your state. You start Force Sensitive, not Sith Lord. Test welcomes and bot notifications go to the private `test-results` channel.

## 6. Invite only the other founders after the first startup works

The three IDs already configured are:

| Username | User ID |
|---|---|
| testing_account98 | 1494827444698480742 |
| fox225506 | 1132159444688568490 |
| jdowie. | 1374863187102535731 |

Your owner ID is **258470721829732353**. Grant each verified founder the native Founding Council role after they join. They can then complete `/join` and choose their own faction. Work through [the exact testing checklist](docs/founder-test-checklist.md). Do not share a public invitation yet.

## Keeping it running and safe to update

The bot operates only while this PC and its console are on and connected. There is no hosting subscription in this package; your existing PC still uses power and internet. No port forwarding, public web endpoint, or paid host is required by this implementation.

Close with Ctrl+C. Use launcher option **3** for an additional verified database backup while the bot is stopped. Automatic backups run at startup and every six hours. Keep a copy of the project data and backups on another drive you control; never publish the database, reports, or bot token.

When updating, replace code only. Keep `data`, `backups`, and `config.local.json`. The next startup reconciles saved roles; it does not reset XP. Only one launcher may use a project folder at a time.

## Current practical limits

The browser session previously used to build the server is no longer available, and this coding environment cannot connect directly to Discord's API. That is why the remaining authenticated configuration and first live connection have to run from your PC. Windows launchers have been reviewed here but cannot be executed in this Linux workspace. The offline suite runs again on your PC before the bot starts.

This is a private test release. The launcher deliberately refuses production mode. After the founders finish testing, review promotion pacing, permissions, backups, and moderation together before requesting a separate launch preparation. Test records remain separate; they must not silently become production XP.
