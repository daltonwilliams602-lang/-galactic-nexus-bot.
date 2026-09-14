"""Voice presence and durable notification delivery, independent of slash commands."""
import hashlib
import json
import time
import discord
from .blueprint import RANKS


class VoicePresence:
    """Require a continuous minute with two eligible, attended participants.

    No audio is recorded. A fresh check-in is only a participation attestation;
    it cannot prove a human is actually speaking.
    """
    def __init__(self):
        self.since = {}
        self.last_tick = None

    def reset(self):
        self.since.clear()
        self.last_tick = None

    def observe(self, rooms, now):
        if self.last_tick is not None and (now < self.last_tick or now-self.last_tick > 45):
            self.since.clear()  # Disconnection/stall never produces backfilled XP.
        self.last_tick = now
        eligible = {str(uid): str(room) for room, users in rooms.items() if len(set(users)) >= 2 for uid in users}
        for uid in list(self.since):
            if uid not in eligible or self.since[uid][0] != eligible[uid]:
                del self.since[uid]
        for uid, room in eligible.items():
            self.since.setdefault(uid, (room, now))
        return {uid for uid, (_, start) in self.since.items() if now-start >= 60}


def notification(store, kind, payload):
    if kind == 'welcome':
        return 'incoming-transmissions', f'**INCOMING TRANSMISSION**\n<@{payload["member"]}> has entered the Galactic Nexus. Welcome aboard! Choose your path. Earn your rank. Shape the galaxy.'
    if kind in {'promotion', 'faction-request', 'council'}:
        q = store.get('proposal', payload['id'])
        if not q:
            raise RuntimeError('Notification refers to a missing review.')
        member = store.get('member', q['member'], {})
        destination = {'promotion':'promotion-queue', 'faction-request':'faction-requests', 'council':'council-voting'}[kind]
        body = f'**{q["kind"].title()} review {q["id"]}**\nMember: <@{q["member"]}>\nStatus: {q["status"]}\nPath: {q["path"]}'
        if kind == 'promotion':
            body += f'\n{RANKS[q["path"]][q["from_rank"]]} → {RANKS[q["path"]][q["rank"]]}\nPath XP: {member.get("paths",{}).get(q["path"],{}).get("xp",0)}\nRequired approvals: {2 if q["rank"]==4 else 1}\nUse `/promotion-review` with this review ID.'
        elif kind == 'council':
            body += f'\nMotion: {q["purpose"]}\nThree founder yes votes, then `/council-finalize`.'
        else:
            body += '\nUse `/faction-review` with this review ID.'
        return destination, body + '\nReason: ' + q.get('reason','')
    if kind == 'report':
        return 'reports', f'**Private report {payload["id"]}**\nMember: <@{payload["member"]}>\n{payload["reason"]}'
    if kind == 'campaign-result':
        campaign = store.get('campaign', payload['id'])
        return 'campaign-history', f'**{campaign["name"]} — confirmed result**\nJedi: {campaign["scores"]["jedi"]} | Sith: {campaign["scores"]["sith"]}\nWinner: {campaign["winner"] or "Tie; no exclusive winner"}\nSeason: {campaign["id"]}'
    if kind in {'audit','native-audit','error'}:
        return ('bot-logs' if kind == 'error' else 'mod-logs'), json.dumps(payload, ensure_ascii=False, indent=2)
    raise RuntimeError(f'Unsupported notification kind: {kind}')


async def deliver_one(bot, row):
    """Retry role work; reconcile uncertain message sends by their footer ID.

    Discord nonce deduplication is short-lived. After an uncertain send, require
    readable channel history and locate the durable marker before resending.
    """
    payload = json.loads(row['payload'])
    if bot.store.get('delivery-message', row['id']):
        return
    guild = bot.get_guild(bot.guild_id)
    if row['kind'] == 'roles':
        try:
            member = await guild.fetch_member(int(payload['member']))
        except discord.NotFound:
            return  # Member departed; on rejoin a fresh reconciliation is enqueued.
        await bot.reconcile_member(member)
        return
    destination, body = notification(bot.store, row['kind'], payload)
    if bot.engine.c['mode'] == 'test':
        destination = 'test-results'
    channel = bot.channel(destination)
    marker = hashlib.sha256(row['id'].encode()).hexdigest()[:24]
    receipt = bot.store.get('delivery-attempt', row['id'])
    if receipt:
        if receipt['channel'] != channel.id:
            raise RuntimeError('Delivery destination changed after an uncertain send. Review the old channel before retrying.')
        after = discord.Object(id=receipt['after_id'])
        async for message in channel.history(limit=None, after=after, oldest_first=True):
            if message.author.id == bot.user.id and any(e.footer.text == 'nexus:'+marker for e in message.embeds):
                bot.store.put('delivery-message', row['id'], str(message.id))
                return
    else:
        bot.store.put('delivery-attempt', row['id'], {
            'after_id': getattr(channel,'last_message_id',None) or 1,
            'at': time.time(), 'channel': channel.id})
    embed = discord.Embed(title='Galactic Nexus' + (' • TEST' if bot.engine.c['mode']=='test' else ''),
                          description=body[:3900], colour=0x3498DB)
    embed.set_footer(text='nexus:'+marker)
    # Complete payload remains in SQLite even when a Discord summary is shorter.
    message = await channel.send(embed=embed, nonce=marker, allowed_mentions=discord.AllowedMentions.none())
    bot.store.put('delivery-message', row['id'], str(message.id))


async def drain_outbox(bot, limit=10):
    now = time.time()
    rows = bot.store.db.execute('SELECT * FROM outbox WHERE delivered=0 ORDER BY rowid LIMIT 100').fetchall()
    processed = 0
    for row in rows:
        retry = bot.store.get('delivery-retry', row['id'], 0)
        if retry > now:
            continue
        try:
            await deliver_one(bot, row)
        except (discord.HTTPException, RuntimeError) as exc:
            # Persist the error type, not HTTP details or credentials.
            bot.store.db.execute('UPDATE outbox SET attempts=attempts+1,last_error=? WHERE id=?',
                                 (type(exc).__name__, row['id']))
            bot.store.put('delivery-retry', row['id'], now+min(300, 5*2**min(row['attempts'],6)))
        else:
            bot.store.db.execute('UPDATE outbox SET delivered=1,last_error=? WHERE id=?', ('',row['id']))
        processed += 1
        if processed >= limit:
            break
