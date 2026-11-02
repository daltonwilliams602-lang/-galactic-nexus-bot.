# Selection log

Use `/selection-log` in Galactic Nexus. Founders and authorized staff can run it; the response and CSV are visible only to the requester.

The command fetches the full current Discord member list, then looks up each person's saved bot selection. It includes people who have never used the bot, excludes departed accounts, and lists bots separately as not needing selection. Manually assigned Discord roles do not count as completing the bot process.

- `selection:all` (default): everyone in the server.
- `selection:incomplete`: people who still need `/join` or `/path`, or have an unrecognized saved selection.
- `selection:complete`: people who joined and have a Jedi or Sith selection.
- `selection:jedi` or `selection:sith`: one side.
- `selection:bot`: bot accounts.
- `page:2`: next page. The attached CSV includes **all** matching rows, regardless of the displayed page.

The CSV includes Discord ID, username, server display name, selected side, completion status, rank, rules-confirmation status, and report time. IDs and potentially executable names use a leading apostrophe to keep spreadsheet applications from treating them as numbers or formulas. Reports are generated on demand without changing progression records or posting in public channels.

# 18+ rules

Rules, welcome text, `/join` options, errors, and confirmation wording now require **18+**. Startup updates age phrases in the bot's rules and onboarding posts in place, including embeds, while keeping other wording and formatting. It reports any older age wording in messages by other authors, which Discord does not let the bot edit.

New joins record the 18+ declaration with rules version 2. Older join records retain their original status and are labelled as an earlier rules acceptance, not an 18+ confirmation. Existing members may use `/join` again and confirm the updated rules; this keeps their faction, XP, ranks, original onboarding date, and history and does not send another welcome. This is self-attestation, not independent age verification.
