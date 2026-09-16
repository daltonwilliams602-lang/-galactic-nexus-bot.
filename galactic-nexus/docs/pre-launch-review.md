# Galactic Nexus — implementation and pre-launch review

**Release update (2026-09-16):** the hosted worker, persistent volume, private setup, founder testing, and restart checks have been exercised. This release adds explicit owner-approved live activation while preserving existing XP, ranks, history, and pending approvals. See [HOSTING.md](../HOSTING.md) for activation and recovery. Later operational records determine live deployment status; the implementation checklist below is not evidence that every human acceptance scenario was exercised.

## 1. Created and prepared

Existing Discord guild: **THE GALACTIC NEXUS**, ID **1548550668900372560**. Branded icon, private profile, description, 28 custom human roles, nine categories, most or all requested channels, and initial Arrival posts were created in the earlier browser work. One duplicated Council construction channel may remain. The reviewed configuration script preserves and renames duplicate channels rather than deleting them.

The blueprint targets **41 text channels and 8 voice rooms**. The installed bot adds a managed integration role, giving 29 named roles in the planned hierarchy plus @everyone.

## 2. Role hierarchy

Highest to lowest:

1. Server Owner
2. Founding Council
3. Admin
4. Senior Moderator
5. Moderator
6. Galactic Nexus
7. Jedi Grand Master
8. Dark Lord of the Sith
9. Darth
10. Jedi High Council
11. Dark Council
12. Rulers of the Galaxy
13. Inactive Council
14. Jedi Master
15. Sith Lord
16. Jedi Knight
17. Sith Warrior
18. Padawan
19. Sith Apprentice
20. Jedi Initiate
21. Sith Acolyte
22. Light Side
23. Dark Side
24. Force Sensitive
25. Founder Tester
26. Game Nights
27. Stream Alerts
28. Events
29. Member

## 3. Permission hierarchy

The technical owner has Discord's inherent ownership. Server Owner is cosmetic; Founding Council is a separate permanent governance designation by explicit account IDs. The bot never assigns or removes staff/owner/custom roles during progression reconciliation.

@everyone has read-history/application-command permissions and receives Arrival visibility through channel overwrites. The owner can enable Create Invite on @everyone; the bot preserves that setting and still rejects every other unexpected permission. Member enables conversation and voice but no global channel visibility, mass mentions, or management. Invite permission is inherited from @everyone when the owner enables it. Lore, faction, Council, prestige, test, and notification roles have no native moderation powers.

Moderator has message/thread/nickname management, timeouts, and voice moderation. Senior Moderator, Admin, and Founding Council additionally have kick, ban, audit-log, and event management permissions. None has Administrator or Manage Roles. The owner manually selects staff.

The bot runs below staff and above progression. Normal operation needs Manage Roles, message/history/embed/file access, and audit visibility. Setup temporarily also needs Manage Channels, Manage Server, Create Public Threads, Create Private Threads, and Send Messages in Threads for native configuration/AutoMod and channel restrictions. If progression role permissions need repair, setup checks for and lists any additional permissions required to grant them. Remove all listed temporary permissions afterward. Normal startup refuses Manage Channels, Manage Server, and Administrator. All bound role IDs and permission overwrites are checked; a later unsafe change stops the bot.

## 4. Channel/category inventory

**ARRIVAL:** incoming-transmissions, rules, announcements, choose-your-path, roles, server-guide

**HOLOCOMMS:** general, star-wars, memes, clips-and-media, art, gaming, bot-commands

**GALACTIC ARCHIVES:** rank-progression, trials-and-challenges, galactic-campaign, campaign-history, events, suggestions

**JEDI TEMPLE:** jedi-commons, jedi-training, jedi-missions, Jedi Temple (voice)

**SITH ACADEMY:** sith-commons, sith-training, sith-missions, Sith Academy (voice)

**CANTINA & EVENTS:** game-nights, trivia, community-events, General VC (voice), Cantina (voice), Gaming 1 (voice), Gaming 2 (voice), AFK (voice)

**COUNCIL CHAMBERS:** jedi-high-council, dark-council, founding-council, council-voting, nominations

**STAFF:** staff-chat, promotion-queue, faction-requests, reports, mod-logs, bot-logs

**FOUNDER TESTING:** testing-lab, test-results, Founder Test VC (voice)


Private Jedi/Sith categories grant the relevant faction plus staff oversight. Founding Council sees governance areas. Only the matching lore Council sees its own Council room; the other Council and ordinary moderators do not gain that access. Staff channels are private. Founder Testing is founder-only. Arrival and the selected announcement/reference channels are read-only for ordinary members, including thread creation/posting. The dedicated AFK room never earns XP.

## 5. Onboarding

Join → Arrival/rules → `/join` with separate 17+ and rules affirmations → preview → Confirm → Member + Force Sensitive → `/path` → preview → Confirm → faction access. Self-service interest roles are separate. Founders choose their own paths. Dalton initially chooses Sith, without automatically receiving a high lore rank.

## 6. Force XP

Meaningful text and eligible voice minutes feed the same total and faction ledger. Native event participation is awarded explicitly through `/award-xp` with a stable event/member receipt. A member earns at most one activity award per real 60 seconds and minute bucket, shared across modalities. The database is authoritative; there is no XP-reset command.

## 7. Initial thresholds

| Rank step | Jedi | Sith | XP threshold | Full-credit activity equivalent |
|---|---|---|---|---|
| 0 | Force Sensitive | Force Sensitive | 0 | Onboarding |
| 1 | Jedi Initiate | Sith Acolyte | 500 | 50 minutes |
| 2 | Padawan | Sith Apprentice | 3,000 | 5 hours |
| 3 | Jedi Knight | Sith Warrior | 14,400 | 24 hours |
| 4 | Jedi Master | Sith Lord | 151,200 | 252 hours |

The curve, rate, transfer mapping, cooldown, and campaign/inactivity settings are editable through founder-confirmed `/configure` actions. Events and diminishing returns mean these are equivalents, not guaranteed elapsed-time deadlines.

## 8. Anti-farming

Text requires length and word-count thresholds; commands, repeated normalized text, near-duplicate word sequences, and reused message IDs are excluded. Numeric suffixes do not alter normalized words. Only salted token hashes and timestamps are retained for the current anti-repeat state, not stored chat bodies. Text/voice share a minute limiter. Qualifying conversation renews an attended-voice check-in.

Voice requires at least two non-bot, eligible, recently checked-in participants in a configured non-AFK room. Muted, deafened, suppressed, timed-out, or expired-check-in members do not count. Continuous eligibility is required for a minute; leaving, changing rooms, losing a peer, disconnects, and long polling stalls reset that continuity. No offline awards are backfilled and no audio is recorded. This is a practical attendance heuristic, not proof of active speech or meaningful content.

Daily diminishing returns: 240 full-credit minutes, then 240 at one-fifth rate, then no more activity XP for that UTC day. Event awards are separately verified human actions.

## 9. Promotions

Threshold → automatic advancement through Knight/Warrior. Only Master/Lord requires a private review and two distinct reviewers. No self-review. Reviewer authority and candidate timeout/standing are rechecked at confirmation. Deferred promotions retain XP; reopening clears prior approvals. Multiple earned lower thresholds can advance together; the top rank never skips human approval. Active conduct holds and explicit legacy review holds pause automatic advancement.

## 10. Faction changes

Normal changes have a 30-day cooldown, explicit preview, and confirmation. Private `/faction-request` and `/faction-review` allow documented exceptions approved by another staff member. The old faction and Council access are removed before new roles are added. An unsuccessful removal blocks new access and leaves the durable work pending.

## 11. Transfer mapping

| Current rank index | New, previously untrained path index |
|---|---|
| 0 | 0 |
| 1 | 0 |
| 2 | 1 |
| 3 | 2 |
| 4 | 2 |

The destination gets the threshold XP equivalent for the transferred rank. Historical earned ranks and total earned XP remain. Returning to a previously earned top rank restores rank 3 first and opens fresh human review for rank 4. Council seats are not silently restored.

## 12. Overrides and founder tests

`/override`, `/founder-test`, `/configure`, `/standing`, and `/prestige` require appropriate authority and confirmation. The preview identifies the member and changed values. Every change records an audit reason and state. Founder-test changes only the caller's test records and never runs in live mode. Governance IDs are a local explicit configuration, not a self-assignable role or editable slash-command setting.

## 13. Council votes/seats

Each faction has at most 12 active seats. Normal appointments/restorations require Master/Lord standing and three yes votes from the full four-founder roster, followed by another human confirmation. Removal/inactive motions also require three yes votes. Abstentions do not reduce the denominator; the subject cannot vote or finalize their own case. Caps and eligibility are checked again at finalization. Approximately 90 days of inactivity permits consideration, not automatic demotion. The actual owner has a separately logged emergency removal command.

## 14. Campaigns

Human-started seasons default to 30 days. Verified event/member Influence awards have durable duplicate protection. Ordinary chat does not produce Influence. A human reviews and confirms the result; only the owner can finish early. Ties grant no exclusive winner. The winning designation remains until another confirmed result. Closed seasons and contribution history are retained. Planet-control fields are reserved for a later extension without implementing conquest now.

## 15. Moderation

Native staff roles remain separate from lore. The configuration run sets medium verification, explicit-media filtering for all members, mentions-only defaults, and disables redundant native system join messages. It installs native AutoMod presets for slurs/sexual content, mention spam (limit 5 plus raid protection), and suspected spam. The general profanity preset remains off. These settings are prepared in code and will not exist until configuration succeeds. AutoMod does not guarantee that every malicious link, scam, threat, or abusive message is detected; human moderation and appeals remain necessary.

## 16. Logging and backups

SQLite WAL/full synchronous transactions store members, path history, immutable audit rows, review/vote records, campaigns, delivery receipts, and pending work. Discord summaries go to private destinations; all test notifications go to test-results. Native joins/leaves, role/timeouts, and available audit-log events are recorded without claiming every possible Discord action is visible. Complete audit state remains in SQLite when a Discord summary is shortened.

Notification work survives restarts. Stable message markers and SDK nonces reduce duplicate sends; an uncertain send is checked against readable destination history before retrying. A changed destination blocks automatic retry for review. Role reconciliation uses atomic add/remove calls and preserves unrelated/governance roles. Missing members are reconciled again if they return.

Backups run before startup changes and every six hours. Launcher option 3 makes an additional integrity-checked copy. Configuration saves the previous server state before editing. Backups are never auto-deleted. Keep a separate copy under your own control. The project lock prevents two local launchers sharing one database; it is not a distributed multi-host lock.

## 17–18. Integrations and custom code

One custom Galactic Nexus bot using pinned discord.py 2.7.1. Twenty-five slash commands cover onboarding, progress, voice checks, interests, faction requests/reviews, promotion reviews, event XP, founder testing, overrides, Council nominations/votes/finalization/emergency removal, campaigns/Influence, standing, prestige, configuration, reports, and the private dashboard. There is no extra ticket/XP/dashboard bot, public website, or inbound web service.

## 19. Hosting

Hosted build v1.3 runs as a Docker worker with persistent storage, allowing Dalton's PC to be off once deployment succeeds. The proposed Railway setup is one worker and a 1 GB volume at /data; see [../HOSTING.md](../HOSTING.md). Railway is connected, but deployment controls were not exposed in this session and no service or subscription was created. Its Hobby plan starts at $5/month plus usage beyond the included credit; the proposed $10/month budget needs owner approval under the original brief. Image build and live hosting remain to be verified.

## 20–21. Work that needs the owner and deployment

The owner created and installed the Discord application; the Windows launcher connected and verified the owner. Configuration stopped with error 50013. The hosted build includes the corrected checks and can perform plan/configure/run actions in the cloud. The owner must approve hosting costs, enter the token privately in host Variables, and correct the listed Discord bot-role permissions. After configuration, remove temporary permissions and start the hosted worker. Completed live configuration has not yet been verified. A PC process is no longer required for the planned deployment.

Native governance-role assignment remains with Dalton because the bot is deliberately below those roles. The four founder IDs are already supplied and configured, but the other founders have not been invited or granted native roles by this package. User-controlled invitations come after the first successful startup. Founder acceptance tests need those people in Discord.

## 22–23. Security and remaining limitations

No token is included or persisted by the launcher. Tokens are entered in a hidden local prompt or supplied through the process environment. Never distribute data/backup folders, private reports, or credentials with code updates.

67 offline checks are verified, including Discord permission resolution, cloud persistence, preview-only configuration, duplicate-worker exclusion, and graceful Linux shutdown. They do not prove successful live configuration, installed native rules, Docker image build, hosted operation, or user acceptance. The first Windows connection is confirmed by the screenshot; a successful permission report, hosted restart, PC-off check, and founder tests are still required. Live deliveries and API failures must be observed during founder testing.

The launcher is intentionally test-only. Preparing production requires a separate approved launch/migration review. No public invitation, production XP migration, payment, token extraction, or automatic launch is included. Extra future paths require extending the path definitions/commands and a tested migration, not overwriting saved member history.

## 24. Before launch

Complete START-HERE and the founder checklist; keep the generated permission-check result; resolve pending delivery errors; verify backups on a second drive; choose sustainable uptime; agree on pacing and staff decisions; check the rules on mobile; and explicitly approve a launch plan. Preserve all test history separately. No public launch has been approved or performed.
