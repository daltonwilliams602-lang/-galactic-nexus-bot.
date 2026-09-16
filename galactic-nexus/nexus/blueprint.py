"""The single source of truth for Discord roles, channels and welcome copy."""

RANKS = {
    "jedi": ["Force Sensitive", "Jedi Initiate", "Padawan", "Jedi Knight", "Jedi Master"],
    "sith": ["Force Sensitive", "Sith Acolyte", "Sith Apprentice", "Sith Warrior", "Sith Lord"],
}
FACTIONS = {"jedi": "Light Side", "sith": "Dark Side"}
COUNCILS = {"jedi": "Jedi High Council", "sith": "Dark Council"}
PRESTIGE = {"Jedi Grand Master": "jedi", "Darth": "sith", "Dark Lord of the Sith": "sith"}
STAFF = ["Founding Council", "Admin", "Senior Moderator", "Moderator"]
OPT_INS = ["Game Nights", "Stream Alerts", "Events"]
MEMBER_PERMISSIONS = ["send_messages", "send_messages_in_threads", "create_public_threads",
    "embed_links", "attach_files", "add_reactions", "external_emojis", "external_stickers",
    "read_message_history", "connect", "speak", "stream", "use_voice_activation",
    "use_application_commands", "use_embedded_activities", "change_nickname"]
MOD_PERMISSIONS = ["manage_messages", "moderate_members", "mute_members", "deafen_members",
    "move_members", "manage_threads", "manage_nicknames"]
SENIOR_PERMISSIONS = MOD_PERMISSIONS + ["kick_members", "ban_members", "view_audit_log",
    "manage_events", "create_events"]
# Highest to lowest. Owner is cosmetic: actual Discord ownership is authoritative.
ROLE_ORDER = ["Server Owner", "Founding Council", "Admin", "Senior Moderator", "Moderator",
    "Galactic Nexus", "Jedi Grand Master", "Dark Lord of the Sith", "Darth",
    "Jedi High Council", "Dark Council", "Rulers of the Galaxy", "Inactive Council",
    "Jedi Master", "Sith Lord", "Jedi Knight", "Sith Warrior", "Padawan", "Sith Apprentice",
    "Jedi Initiate", "Sith Acolyte", "Light Side", "Dark Side", "Force Sensitive",
    "Founder Tester", "Game Nights", "Stream Alerts", "Events", "Member"]
ROLE_PERMISSIONS = {r: [] for r in ROLE_ORDER}
ROLE_PERMISSIONS.update({"Member": MEMBER_PERMISSIONS, "Moderator": MOD_PERMISSIONS,
    "Senior Moderator": SENIOR_PERMISSIONS, "Admin": SENIOR_PERMISSIONS,
    "Founding Council": SENIOR_PERMISSIONS,
    "Galactic Nexus": ["manage_roles", "view_channel", "send_messages", "embed_links",
        "attach_files", "read_message_history", "view_audit_log"]})
COLORS = {r: 0 for r in ROLE_ORDER}
for r in ["Light Side", "Jedi Initiate", "Padawan", "Jedi Knight", "Jedi Master", "Jedi High Council", "Jedi Grand Master"]:
    COLORS[r] = 0x3498DB
for r in ["Dark Side", "Sith Acolyte", "Sith Apprentice", "Sith Warrior", "Sith Lord", "Dark Council", "Darth", "Dark Lord of the Sith"]:
    COLORS[r] = 0xE74C3C
COLORS.update({"Founding Council": 0xF1C40F, "Server Owner": 0xF1C40F,
    "Admin": 0x9B59B6, "Senior Moderator": 0x71368A, "Moderator": 0x1ABC9C,
    "Rulers of the Galaxy": 0xF1C40F, "Inactive Council": 0x607D8B, "Founder Tester": 0xE67E22})

CATEGORIES = {
    "ARRIVAL": ["incoming-transmissions", "rules", "announcements", "choose-your-path", "roles", "server-guide"],
    "HOLOCOMMS": ["general", "star-wars", "memes", "clips-and-media", "art", "gaming", "bot-commands"],
    "GALACTIC ARCHIVES": ["rank-progression", "trials-and-challenges", "galactic-campaign", "campaign-history", "events", "suggestions"],
    "JEDI TEMPLE": ["jedi-commons", "jedi-training", "jedi-missions", "vc:Jedi Temple"],
    "SITH ACADEMY": ["sith-commons", "sith-training", "sith-missions", "vc:Sith Academy"],
    "CANTINA & EVENTS": ["game-nights", "trivia", "community-events", "vc:General VC", "vc:Cantina", "vc:Gaming 1", "vc:Gaming 2", "vc:AFK"],
    "COUNCIL CHAMBERS": ["jedi-high-council", "dark-council", "founding-council", "council-voting", "nominations"],
    "STAFF": ["staff-chat", "promotion-queue", "faction-requests", "reports", "mod-logs", "bot-logs"],
    "FOUNDER TESTING": ["testing-lab", "test-results", "vc:Founder Test VC"],
}
READ_ONLY = {"rules", "announcements", "choose-your-path", "roles", "server-guide",
    "rank-progression", "trials-and-challenges", "galactic-campaign", "campaign-history",
    "events", "jedi-missions", "sith-missions", "promotion-queue", "faction-requests",
    "reports", "mod-logs", "bot-logs", "test-results"}
NO_XP = set(CATEGORIES["ARRIVAL"] + CATEGORIES["STAFF"] + CATEGORIES["COUNCIL CHAMBERS"]
    + ["bot-commands", "galactic-campaign", "campaign-history", "rank-progression", "test-results"])


def audience(category, channel=None):
    """Explicit visibility; no shared member allow on private categories."""
    if category == "ARRIVAL":
        return ["@everyone", "Founding Council"]
    if category == "JEDI TEMPLE":
        return ["Light Side"] + STAFF
    if category == "SITH ACADEMY":
        return ["Dark Side"] + STAFF
    if category == "STAFF":
        return STAFF
    if category == "FOUNDER TESTING":
        return ["Founding Council"]
    if category == "COUNCIL CHAMBERS":
        return ["Founding Council"] + ({"jedi-high-council": ["Jedi High Council"],
            "dark-council": ["Dark Council"]}.get(channel, []))
    return ["Member", "Founding Council"]


def can_view(roles, category, channel=None, owner=False):
    return owner or bool((set(roles) | {"@everyone"}) & set(audience(category, channel)))


RULES = """## THE GALACTIC NEXUS • Community rules
1. **17+ and SFW.** Confirm you are at least 17. No pornography or explicit sexual content.
2. **Treat people reasonably.** Profanity, mature jokes, and friendly Light vs Dark trash talk are welcome. Targeted harassment, serious bullying, and threats are not.
3. **No racism or hate speech.** A joke is not an excuse to attack a person's identity.
4. **Keep people and accounts safe.** No scams, malware, malicious links, doxxing, or raids.
5. **No spam or farming.** Don't exploit XP, voice activity, factions, campaigns, or bot commands.
6. **Respect privacy.** Ask before sharing private conversations or someone's personal information.
7. **Follow Discord's Terms and Community Guidelines.** Do not evade moderation or help banned members return.
8. **Appeal calmly.** Use `/report` for a private concern or appeal. Don't turn moderation disagreements into public fights.

This is a gaming community, not compulsory roleplay. Be someone others enjoy hanging out with.
"""
CONTENT = {
    "rules": RULES,
    "incoming-transmissions": "**INCOMING TRANSMISSIONS**\nWelcome to **THE GALACTIC NEXUS**.\n*Choose your path. Earn your rank. Shape the galaxy.*\n\nRead #rules, then use `/join` to confirm 17+ and accept them. Choose a faction in #choose-your-path.\n\n**PRIVATE FOUNDER TESTING:** invitations and public launch remain closed pending the owner's approval.",
    "choose-your-path": "**CHOOSE YOUR PATH**\nEveryone begins **Force Sensitive**. Use `/path` to choose **Jedi / Light Side** or **Sith / Dark Side**.\n\nYour first choice opens your faction's channels; your first three lore ranks advance automatically with enough XP. Jedi Master and Sith Lord require two different staff approvals. Switching later has a **30-day cooldown** and a displayed transfer penalty. Use `/faction-request` for a mistake or exception. Your earned history stays intact.",
    "roles": "**MAKE THE NEXUS YOUR OWN**\nUse `/interest` for optional **Game Nights**, **Stream Alerts**, and **Events** roles. These are notification preferences and do not grant authority.\nRank roles through Knight/Warrior update automatically from XP. Master/Lord and Council appointments need human approval; founder and staff authority remain separate.",
    "server-guide": "**YOUR QUICK SERVER GUIDE**\nChat in #general; share games, clips, art, or memes in HOLOCOMMS. Meet up in the Cantina voice rooms. Your faction has its own commons and training rooms.\n\n`/profile` • your rank and progress\n`/path` • choose or change faction\n`/voice-check` • confirm you're participating in VC\n`/campaign` • this season's score\n`/report` • private help or moderation appeal\n\nStaff roles and Founding Council govern the community. Jedi/Sith ranks and lore Councils do not grant moderation powers. Normal earned ranks do not expire when you take a break.",
    "rank-progression": "**FORCE XP • AUTOMATIC RANKS**\nJedi: Force Sensitive → Jedi Initiate → Padawan → Jedi Knight → Jedi Master.\nSith: Force Sensitive → Sith Acolyte → Sith Apprentice → Sith Warrior → Sith Lord.\n\nStarting thresholds: **500 / 3,000 / 14,400 / 151,200 XP**. At 10 XP per qualifying minute, these represent about **50 minutes / 5 hours / 24 hours / 252 hours** of cumulative activity equivalent. They are adjustable test values. Events can also contribute.\n\nText and eligible voice activity feed one pool; the same minute is not counted twice. The first three XP thresholds automatically grant Initiate/Acolyte, Padawan/Apprentice, and Knight/Warrior. Only Master/Lord opens a promotion review and needs two distinct staff approvals. Active conduct holds pause advancement without deleting XP.\n\nCouncils, Darth, Dark Lord, and Grand Master are human-awarded distinctions, never automatic XP levels.",
    "galactic-campaign": "**GALACTIC CAMPAIGNS**\nLight Side vs Dark Side, through game nights, trivia, art, challenges, and staff-created missions.\nEarn **Galactic Influence** for verified participation—not ordinary message volume. Seasons begin at about 30 days and remain configurable. A human reviews and confirms the result. The winners become **Rulers of the Galaxy** until the next result. A tie grants no exclusive winner.\nEvery season and contribution stays in history. A new season starts a new score ledger; it never erases previous results.",
    "campaign-history": "**THE GALACTIC HALL OF FAME**\nConfirmed campaign results will appear here. Test results remain in the founders' test records.",
    "promotion-queue": "**PRIVATE PROMOTION QUEUE**\nUse `/dashboard` and `/promotion-review`. Check member, faction, current/proposed rank, XP, and standing. Lower ranks advance automatically at their XP thresholds; only Master/Lord need two distinct reviewers. No self-approval. Defer or deny with a reason; preserve legitimate XP.",
    "council-voting": "**FOUNDING COUNCIL VOTES**\nAppointments/restorations require at least 2/3 of the four founders (**3 yes votes**). Removal/inactive status require 3/4 (**3 yes votes**). Abstentions do not shrink the denominator. The candidate cannot vote on their own case. A founder must confirm the final action; a timer never appoints or removes anyone. Maximum **12 active seats per lore Council**.",
    "founding-council": "**FOUNDING COUNCIL**\nThe four founders hold permanent governance standing regardless of faction, lore rank, or lore Council seat. Technical ownership remains with the actual Discord server owner. Founder IDs must be explicitly configured; this designation is never earned through XP.",
    "testing-lab": "**FOUNDER TESTING**\nThe bot starts in **test mode**, with a separate database. `/founder-test` changes your own test progression after a confirmation. Test rank, faction, cooldown, promotions, Councils, and campaigns here. Every change is logged.\n\nDo not open invitations publicly. Launch needs founder testing and explicit owner approval. No production XP, ranks, or history may be wiped to repair a bug.",
    "announcements": "**NEXUS STATUS: PRIVATE CONSTRUCTION & FOUNDER TESTING**\nThis server is being built. Public launch has not been approved. Expect unfinished systems while the founders test; automated welcomes and results belong in their dedicated channels.",
}

# Only these exact bot-authored templates may be refreshed during this policy update.
LEGACY_PROGRESSION_GUIDES = {'choose-your-path': "**CHOOSE YOUR PATH**\nEveryone begins **Force Sensitive**. Use `/path` to choose **Jedi / Light Side** or **Sith / Dark Side**.\n\nYour first choice opens your faction's channels; your first lore rank still needs activity and human approval. Switching later has a **30-day cooldown** and a displayed transfer penalty. Use `/faction-request` for a mistake or exception. Your earned history stays intact.", 'roles': '**MAKE THE NEXUS YOUR OWN**\nUse `/interest` for optional **Game Nights**, **Stream Alerts**, and **Events** roles. These are notification preferences and do not grant authority.\nFaction, rank, Council, founder, and staff roles follow their separate approval systems.', 'rank-progression': '**FORCE XP • HUMAN-REVIEWED PROMOTIONS**\nJedi: Force Sensitive → Jedi Initiate → Padawan → Jedi Knight → Jedi Master.\nSith: Force Sensitive → Sith Acolyte → Sith Apprentice → Sith Warrior → Sith Lord.\n\nStarting thresholds: **500 / 3,000 / 14,400 / 151,200 XP**. At 10 XP per qualifying minute, these represent about **50 minutes / 5 hours / 24 hours / 252 hours** of cumulative activity equivalent. They are adjustable test values. Events can also contribute.\n\nText and eligible voice activity feed one pool; the same minute is not counted twice. An XP milestone privately opens staff review. The top promotion needs two distinct staff approvals. Conduct can defer promotion without deleting XP.\n\nCouncils, Darth, Dark Lord, and Grand Master are human-awarded distinctions, never automatic XP levels.', 'promotion-queue': '**PRIVATE PROMOTION QUEUE**\nUse `/dashboard` and `/promotion-review`. Check member, faction, current/proposed rank, XP, and standing. Lower promotions need one reviewer; Master/Lord need two distinct reviewers. No self-approval. Defer or deny with a reason; preserve legitimate XP.'}
