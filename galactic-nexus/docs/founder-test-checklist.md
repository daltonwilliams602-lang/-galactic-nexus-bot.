# Founder test checklist

Do this after configuration passes and the bot reports PRIVATE TEST MODE. Use the dedicated test channels. Automated notifications are routed to `test-results` in this release. Record pass/fail notes there and stop on any unexpected privacy exposure or lost data.

You need Dalton and the three configured founders for the complete human workflow. You can do onboarding and your own simulation checks alone first. Commands may take a few seconds to appear after startup. Every state-changing command presents a preview and requires Confirm. Cancel should leave the stored state unchanged.

## A. First startup and onboarding

1. Run `/join age_confirmed:false rules_accepted:true`. It should refuse onboarding.
2. Run `/join age_confirmed:true rules_accepted:true`, inspect the preview, then Cancel. `/profile` should still show no selected path; native Member should not have been granted.
3. Repeat the valid join and Confirm. Within a delivery cycle, expect Member + Force Sensitive. Expect one welcome in `test-results`, with no automated welcome in `general`.
4. Run `/path` and choose Sith for Dalton; the other founders choose independently. Review the destination and confirm. Expect the correct faction role and Force Sensitive. Owning the server does not grant Sith Lord.
5. Run `/interest` with Game Nights twice, confirming each time. The first grants it; the second removes it. It grants no staff powers.

## B. Channel visibility

Dalton's actual ownership bypasses channel restrictions. It is not a useful negative-access test. For this step, use one other founder, temporarily remove their **native Founding Council role** as owner, and leave their Member/faction/rank roles. Restore the founder role afterward. Their configured founder ID still authorizes bot testing; this step tests channel visibility only.

| Perspective | Must see | Must not see |
|---|---|---|
| No Member or faction roles | Arrival | Shared chat, faction, staff, Council, testing rooms |
| Member + Force Sensitive | Arrival, shared chat, archives, Cantina | Factions, Council, staff, testing |
| Member + Light Side + Jedi rank | Shared areas and Jedi Temple | Sith Academy, staff, private Councils |
| Member + Dark Side + Sith rank | Shared areas and Sith Academy | Jedi Temple, staff, private Councils |
| Jedi High Council + Light Side + Member | Jedi High Council room | Dark Council and founding-council |
| Dark Council + Dark Side + Member | Dark Council room | Jedi High Council and founding-council |
| Member + Moderator | Staff and both faction areas | Founding Council discussions and lore Council rooms |
| Founding Council + Member | Oversight of all categories | No unintended restriction |

Check that ordinary members can read rules/announcements but cannot write or create threads there. They should be able to chat in general. Member roles should not grant invitations, Manage Roles, or Administrator.

For each faction, repeat the visibility check at ranks 0–4 using founder test controls, restoring Founding Council between changes if needed. Rank alone must not grant staff authority. Use your own separate non-founder test account if you want to live-test the bot's rejection of unauthorized commands. Do not confuse a founder with their native role removed for an unprivileged bot account: founder authority is ID-based.

## C. Text and voice XP

1. Start with onboarding and a selected path. Note `/profile` XP.
2. Send a normal, distinct conversation message of at least four words and 20 letters in an eligible chat channel. Expect 10 XP if no other award happened in the previous 60 seconds.
3. Immediately send another message or join voice. Expect no second award in the same minute. Repeating the first message after a minute should still not count; trivial edits and numeric suffixes should not bypass the duplicate filter.
4. Two founders join the same normal voice room, both unmuted/undeafened. Both run `/voice-check` and Confirm. Stay eligible for a complete minute, allowing up to another 15 seconds for the next poll. Expect a shared-pool voice award of 10 XP if no text award used that minute.
5. Repeat with one person alone, in AFK, self-muted, deafened, or with an expired check-in. Those conditions should not earn voice XP. If a peer leaves, continuity restarts.
6. Check-ins expire after 15 minutes unless renewed; qualifying text also renews participation for 15 minutes. Voice checks are attestations, not proof of speech. No voice audio is recorded.
7. The first 240 rewarded minutes per UTC day earn full credit. The next 240 earn one-fifth credit (2 XP at default settings), then daily activity credit stops. These caps are covered by local tests/calculations; no one needs to farm eight hours to inspect the settings.

## D. Promotions without grinding

Use the following only in private test mode. Every founder-test command affects the caller's test state and logs the change.

1. Set your test XP to 0, then your test rank to 0 using `/founder-test`, confirming each change. Set XP first so reconciliation does not restore the rank from existing XP.
2. Preview `/founder-test field:xp value:500 reason:Testing first threshold` and Cancel. The rank and XP must not change. Repeat and Confirm: expect Jedi Initiate or Sith Acolyte automatically, with no lower-rank review.
3. Repeat with 3000 and 14400 XP: expect Padawan/Apprentice and then Knight/Warrior, retaining XP and earned-rank history.
4. Set XP to 151200. The rank must remain Knight/Warrior and `/dashboard section:reviews` must show a top-rank review. The subject's self-approval must be refused.
5. Another founder's first approval must leave rank 3. Their repeat approval, even with a different reason, must be refused. A second distinct founder must approve and confirm before Master/Lord is granted.
6. For a conduct hold, another founder uses `/standing member:<subject> decision:add days:1 reason:Temporary promotion-hold test`. Both automatic advancement and top-rank approval must be blocked while the hold is active; XP remains. Clear the specific restriction ID afterward. For an explicitly deferred top review, reopen it and obtain fresh approvals.
7. Existing lower-rank pending reviews are superseded when the rank is automatically earned; old explicit denied/deferred reviews remain holds until staff reopens them. Audit history remains intact.

## E. Faction switch and history

1. Set your test rank to 4, then set cooldown to 0 with `/founder-test field:cooldown value:0 reason:Test transfer`.
2. Preview a move to the other faction using `/path`. If it is your first time in that path, Master/Lord should transfer to rank 2, Apprentice/Padawan. The preview must name the destination rank, cooldown, retained XP, and loss of previous Council access.
3. Cancel first: no change. Repeat and confirm: old faction access ends, destination access opens, and earlier path history remains saved.
4. Try switching straight back. Expect the 30-day cooldown refusal.
5. Submit `/faction-request` for the return. Another founder reviews it using `/faction-review`; you cannot review your own request. Approval bypasses the cooldown. A previously earned rank 4 returns at rank 3 pending a fresh high-promotion review.

## F. Council governance

1. A founder simulates Master/Lord with `/founder-test field:rank value:4` after choosing a faction.
2. Another founder uses `/council-nominate member:<candidate> purpose:appoint path:<jedi or sith> reason:Council workflow test` and confirms.
3. Record the motion ID. The candidate's own vote must be refused. Two yes votes must not be enough to finalize.
4. The other three founders each use `/council-vote motion_id:<ID> vote:yes reason:Council workflow test` and Confirm. The seat must still not appear automatically.
5. Another founder uses `/council-finalize`, reviews the result, and confirms. Only then should the Council role appear.
6. Repeat with a removal motion. Normal removal also needs three yes votes plus final confirmation. Lore removal must leave Founding Council standing, normal rank, and XP intact.
7. Owner-only `/council-emergency-remove` can revoke an active lore seat after confirmation; it is logged and does not remove founder authority.
8. `/founder-test field:council value:inactive` can simulate your own inactive seat. Normal inactivity motions require the configured inactivity period; no one loses earned lore ranks automatically. The 12-seat cap is covered by automated policy tests, so do not create dummy members just to fill seats.

## G. Campaigns, corrections, and private reports

1. Use `/campaign-start name:Founder Test Season days:1 reason:Campaign test` and Confirm.
2. Use `/influence member:<founder> amount:10 event_id:founder-test-001 reason:Verified test participation` and Confirm. `/campaign` should show 10 for that founder's current faction.
3. Repeat the same event ID/member award. It must be rejected. Different event IDs are intentional separate awards; do not invent a new ID merely to retry a failed send.
4. Dalton may end this test season early with `/campaign-finish`. Review scores and confirm. Expect a private test result and the winning designation for the winning faction's recorded members. A tie grants no exclusive winner.
5. Start another season. Its score begins at zero; the prior season, contributions, and result remain in the database and logs. The previous winning designation stays until the next confirmed result.
6. Test `/campaign-edit`, `/prestige`, and an XP correction through `/override`, cancelling first and confirming only after checking the affected member and proposed value. The subject cannot approve their own live correction; private self-simulation belongs in founder-test.
7. Send a harmless `/report` test. It should appear privately in test-results and `/dashboard section:reports`, with no public post. There is no separate ticket bot.

## H. Restarts and final checks

1. Note XP, ranks, faction, a review ID, and campaign scores. Stop with Ctrl+C and restart using launcher option 2. They must remain unchanged. Pending role/notification work should retry, without another copy of already acknowledged messages.
2. Use launcher option 3 while the bot is stopped. Expect a new integrity-checked backup file; existing backups remain.
3. Try starting a second launcher against the same folder. It must refuse the second process.
4. Confirm native AutoMod rules are enabled, normal profanity filtering is off, mention-spam protection is on, and SFW media filtering is enabled. Filters can make mistakes and do not replace human moderation. Owner-exempt actions are not useful filter tests.
5. Confirm changing a protected role's permissions or a private channel's overwrites stops the bot rather than continuing with unsafe access. Use configuration to repair, remove temporary setup powers, and restart.
6. Review the private dashboard logs and delivery queue. Fix failures before widening invitations.

After these pass, stop and request the pre-launch review. The launcher in this package remains test-only. No script will publish invitations or silently convert the test database into production records.
