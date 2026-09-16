"""Discord adapter for Galactic Nexus.

The policy engine owns all state changes.  This module only translates Discord
events into policy calls, presents a second confirmation step, and reconciles
roles from the engine's desired state.  Run with NEXUS_TOKEN in the environment.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import getpass
from pathlib import Path
from typing import Any, Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .blueprint import ROLE_ORDER, ROLE_PERMISSIONS, STAFF, NO_XP, RANKS, CONTENT, LEGACY_PROGRESSION_GUIDES
from .engine import Actor, Engine, PolicyError
from .storage import Store
from .runtime import VoicePresence, drain_outbox
from .server_config import resolve_roles, check_permissions

# Governance and integration roles are never progression-managed.
PROGRESSION_ROLES = frozenset(ROLE_ORDER) - set(STAFF) - {"Server Owner", "Galactic Nexus"}


def role_delta(current_ids, desired_names, role_ids):
    managed = {role_ids[n] for n in PROGRESSION_ROLES}
    desired = {role_ids[n] for n in desired_names if n in PROGRESSION_ROLES}
    return desired - current_ids, (current_ids & managed) - desired


def preview_text(preview):
    """Display the proposed policy effect, without exposing internal state blobs."""
    labels={'affected_member':'Member','member':'Member','current_path':'Current faction',
            'current_rank':'Current rank','proposed_rank':'Proposed rank','path_xp':'Faction XP',
            'total_xp_preserved':'Total XP retained','current_council':'Current Council',
            'cooldown_days':'Faction cooldown (days)','review':'Review ID','motion':'Motion ID',
            'proposed':'Proposed change','earned_xp_preserved':'Earned XP retained'}
    rows=[]
    def show(data, depth=0):
        for key,value in data.items():
            label=labels.get(key,key.replace('_',' ').capitalize())
            if isinstance(value,dict):
                rows.append(f'**{label}**')
                show(value,depth+1)
                continue
            if key in {'affected_member','member'} and str(value).isdecimal():
                value=f'<@{value}>'
            elif key=='current_rank' and isinstance(value,int) and preview.get('current_path') in RANKS:
                value=RANKS[preview['current_path']][value]
            elif isinstance(value,list):
                value=', '.join(str(x) for x in value) or 'None'
            elif value is None:
                value='None'
            elif isinstance(value,bool):
                value='Yes' if value else 'No'
            rows.append(f'{label}: {value}')
    show(preview)
    return '\n'.join(rows)


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class NexusBot(commands.Bot):
    def __init__(self, config: dict[str, Any], *, db_path: str | os.PathLike[str]):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.config_data = config
        self.store = Store(db_path)
        self.engine = Engine(self.store, config)
        self.guild_id = int(config["guild_id"])
        self._role_ids: dict[str, int] = {}
        self._ready_once = False
        self._validated = asyncio.Event()
        self._role_lock = asyncio.Lock()
        self.voice_presence = VoicePresence()
        self._closing = False
        self._startup_error = None

    async def setup_hook(self) -> None:
        # Commands and workers start only after the owner and role map pass.
        pass

    async def on_ready(self) -> None:
        guild = self.get_guild(self.guild_id)
        if guild is None:
            self._startup_error = 'Configured guild is not available; refusing to run elsewhere.'
            await self.close()
            return
        if not self._ready_once:
            try:
                await self._load_roles(guild)
                self.validate_channels(guild)
                self.store.backup(self.config_data.get('backup_dir','backups'))
                await self.refresh_progression_guides()
                await self.tree.sync(guild=discord.Object(id=self.guild_id))
            except (RuntimeError, discord.HTTPException) as exc:
                self._startup_error = str(exc)
                await self.close()
                return
            self._ready_once = True
            self._validated.set()
            self.reconcile_loop.start()
            self.activity_loop.start()
            self.delivery_loop.start()
            self.backup_loop.start()
            print('Galactic Nexus is online in PRIVATE TEST MODE. Use /join in Discord.')

    async def refresh_progression_guides(self):
        for name, previous in LEGACY_PROGRESSION_GUIDES.items():
            async for message in self.channel(name).history(limit=100):
                if message.author.id == self.user.id and message.content == previous:
                    await message.edit(content=CONTENT[name], allowed_mentions=discord.AllowedMentions.none())
                    print('Updated automatic-rank guide in #'+name, flush=True)

    def channel(self, name):
        ids = [cid for key,cid in self.config_data.get('channel_ids',{}).items() if key.endswith('/'+name)]
        if len(ids)!=1:
            raise RuntimeError(f'Missing or ambiguous channel mapping: {name}')
        channel = self.get_channel(int(ids[0]))
        if channel is None or channel.guild.id != self.guild_id:
            raise RuntimeError(f'Channel unavailable: {name}')
        return channel

    def validate_channels(self, guild):
        roles = resolve_roles(guild,self._role_ids)
        bot_role = guild.me.top_role
        problems = check_permissions(guild,roles,bot_role,self.config_data.get('channel_ids',{}))
        if problems:
            raise RuntimeError('Run Configure Server to repair these permission checks: '+ '; '.join(problems))

    def native_event(self, action, target, details):
        if not self._validated.is_set():
            return
        with self.store.transaction():
            self.store.log('discord',action,str(target),None,details,'Native Discord event')
            self.store.enqueue('native-audit', {'action':action,'member':str(target),'details':details,'at':time.time()})

    async def on_member_join(self, member):
        if member.guild.id == self.guild_id:
            self.native_event('member-joined', member.id, {})
            if self.store.get('member',str(member.id)):
                self.store.enqueue('roles',{'member':str(member.id)})

    async def on_member_remove(self, member):
        if member.guild.id == self.guild_id:
            self.native_event('member-left',member.id,{})

    async def on_member_update(self, before, after):
        if after.guild.id != self.guild_id:
            return
        self.refresh_timeout(after)
        if before.roles != after.roles or before.timed_out_until != after.timed_out_until:
            self.native_event('roles-or-timeout-changed',after.id,{
                'old_roles':[str(r.id) for r in before.roles], 'new_roles':[str(r.id) for r in after.roles],
                'timeout_until':str(after.timed_out_until)})

    async def on_audit_log_entry_create(self, entry):
        if entry.guild.id == self.guild_id and str(entry.action) in {
            'AuditLogAction.kick','AuditLogAction.ban','AuditLogAction.unban','AuditLogAction.member_update'}:
            self.native_event(str(entry.action), getattr(entry.target,'id','unknown'),
                              {'actor':str(entry.user_id),'reason':entry.reason})

    async def on_disconnect(self):
        self.voice_presence.reset()

    async def recheck_safety(self, guild):
        if guild.id != self.guild_id or not self._ready_once or self._closing:
            return
        self._validated.clear()
        try:
            await self._load_roles(guild)
            self.validate_channels(guild)
        except (RuntimeError, discord.HTTPException) as exc:
            print('Safety check stopped the bot: '+str(exc))
            await self.close()
        else:
            self._validated.set()

    async def on_guild_role_update(self, before, after):
        await self.recheck_safety(after.guild)

    async def on_guild_role_delete(self, role):
        await self.recheck_safety(role.guild)

    async def on_guild_channel_update(self, before, after):
        if before.overwrites != after.overwrites or before.name != after.name:
            await self.recheck_safety(after.guild)

    async def on_guild_channel_delete(self, channel):
        await self.recheck_safety(channel.guild)

    def attended_rooms(self, guild, now):
        rooms = {}
        approved_voice_ids = {int(cid) for key,cid in self.config_data.get('channel_ids',{}).items()
                              if '/vc:' in key and not key.endswith('/vc:AFK')}
        for room in guild.voice_channels:
            if room.id not in approved_voice_ids or room == guild.afk_channel:
                continue
            users = []
            for member in room.members:
                uid = str(member.id)
                v = member.voice
                m = self.engine.member(uid)
                if member.bot or not v or v.self_mute or v.self_deaf or v.mute or v.deaf or v.suppress:
                    continue
                if self.engine.c['mode']=='test' and uid not in self.engine.c['founder_ids']:
                    continue
                self.refresh_timeout(member)
                if (m['accepted'] and m['path'] and not member.is_timed_out()
                    and self.store.get('voice-check',uid,{}).get('until',0)>now):
                    users.append(uid)
            rooms[room.id] = users
        return rooms

    async def on_voice_state_update(self, member, before, after):
        if member.guild.id == self.guild_id and self._validated.is_set():
            self.voice_presence.observe(self.attended_rooms(member.guild,time.time()),time.time())

    @tasks.loop(seconds=15)
    async def activity_loop(self):
        if not self._validated.is_set():
            self.voice_presence.reset()
            return
        guild = self.get_guild(self.guild_id)
        now = time.time()
        for uid in self.voice_presence.observe(self.attended_rooms(guild,now),now):
            self.engine.award_activity(uid,'voice',eligible_voice=True,now=now)

    @tasks.loop(seconds=5)
    async def delivery_loop(self):
        if not self._validated.is_set():
            return
        try:
            self.validate_channels(self.get_guild(self.guild_id))
        except RuntimeError as exc:
            print('Bot stopped: permissions changed. '+str(exc))
            self._validated.clear()
            # Cancel this worker through normal client shutdown, not mid-close.
            asyncio.create_task(self.close())
            return
        await drain_outbox(self)

    @tasks.loop(hours=6)
    async def backup_loop(self):
        self.store.backup(self.config_data.get('backup_dir','backups'))

    @activity_loop.before_loop
    @delivery_loop.before_loop
    @backup_loop.before_loop
    async def before_workers(self):
        await self._validated.wait()

    @activity_loop.error
    @delivery_loop.error
    @backup_loop.error
    async def worker_error(self, error):
        print('A background task failed ('+type(error).__name__+'). Bot stopped; preserve data and review the error before restarting.')
        self._validated.clear()
        if not self._closing:
            self.store.enqueue('error', {'type':type(error).__name__,'at':time.time()})
            asyncio.create_task(self.close())

    async def on_message(self, message: discord.Message) -> None:
        if not self._validated.is_set() or message.author.bot or message.guild is None or message.guild.id != self.guild_id:
            return
        channel = message.channel.parent if isinstance(message.channel, discord.Thread) else message.channel
        allowed = {int(cid) for key,cid in self.config_data.get('channel_ids',{}).items()
                   if '/vc:' not in key and key.split('/',1)[1] not in NO_XP}
        if channel is None or channel.id not in allowed or not isinstance(message.author, discord.Member):
            return
        self.refresh_timeout(message.author)
        # Policy decides whether the message qualifies; this adapter never awards
        # from bot commands, mentions, or content outside the configured guild.
        try:
            self.engine.award_activity(str(message.author.id), "text", content=message.content,
                                       event_id=str(message.id))
        except PolicyError:
            pass
        await self.process_commands(message)

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for worker in (self.reconcile_loop,self.activity_loop,self.delivery_loop,self.backup_loop):
            if worker.is_running():
                worker.cancel()
        self.store.close()
        await super().close()

    async def _load_roles(self, guild: discord.Guild) -> None:
        if str(guild.owner_id) != self.engine.c['owner_id']:
            raise RuntimeError("Configured owner does not match the actual Discord server owner.")
        mapping = self.config_data.get('role_ids', {})
        required = set(ROLE_ORDER) - {'Galactic Nexus'}
        missing = sorted(required - mapping.keys())
        if missing:
            raise RuntimeError("Record the verified Discord role IDs before startup: " + ", ".join(missing))
        ids = {name: int(mapping[name]) for name in required}
        if len(set(ids.values())) != len(ids):
            raise RuntimeError("Each configured role ID must be unique.")
        roles = {r.id: r for r in await guild.fetch_roles()}
        found = {name: roles.get(rid) for name, rid in ids.items()}
        for name, role in found.items():
            if role is None or role.name != name or role.managed or role.is_default():
                raise RuntimeError(f"Role ID does not match the verified role: {name}")
            if name in PROGRESSION_ROLES:
                allowed = discord.Permissions(**{flag: True for flag in ROLE_PERMISSIONS[name]})
                if role.permissions.value & ~allowed.value:
                    raise RuntimeError(f'Unexpected permissions on progression role: {name}')
        me = await guild.fetch_member(self.user.id)
        if me is None or not me.guild_permissions.manage_roles:
            raise RuntimeError("Bot needs Manage Roles.")
        if me.guild_permissions.administrator:
            raise RuntimeError("Remove Administrator from the bot before testing.")
        if me.guild_permissions.manage_channels or me.guild_permissions.manage_guild:
            raise RuntimeError('Configuration is finished: remove temporary Manage Channels and Manage Server from the bot before normal startup.')
        if any(found[name] >= me.top_role for name in PROGRESSION_ROLES):
            raise RuntimeError("Progression roles must be below the bot's highest role.")
        if any(found[name] <= me.top_role for name in set(STAFF) | {'Server Owner'}):
            raise RuntimeError("Staff and owner roles must stay above the bot.")
        self._role_ids = ids

    def actor(self, member: discord.Member) -> Actor:
        member_ids = {r.id for r in member.roles}
        role_names = frozenset(n for n, rid in self._role_ids.items() if rid in member_ids)
        return Actor(str(member.id), role_names)

    def refresh_timeout(self, member):
        state = self.store.get('member', str(member.id))
        if state is not None:
            until = member.timed_out_until.timestamp() if member.timed_out_until else 0
            if state['native_timeout_until'] != until:
                state['native_timeout_until'] = until
                self.engine.save_member(state, bump=False, sync=False)

    async def fresh_actor(self, interaction, action='', target=''):
        if interaction.guild_id != self.guild_id or not self._validated.is_set():
            raise PolicyError('This command is only available in the configured, validated server.')
        if self.engine.c['mode'] == 'test' and str(interaction.user.id) not in self.engine.c['founder_ids']:
            raise PolicyError('This server is in private founder testing.')
        guild = interaction.guild
        member = await guild.fetch_member(interaction.user.id)
        actor = self.actor(member)
        self.refresh_timeout(member)
        q = self.store.get('proposal', target)
        subject = q['member'] if q else target
        if subject and subject.isdecimal() and subject != str(member.id):
            self.refresh_timeout(await guild.fetch_member(int(subject)))
        # Only current, still-present staff approvals can count toward promotion.
        staff = set()
        for uid in (q or {}).get('approvals', []):
            try:
                prior = self.actor(await guild.fetch_member(int(uid)))
            except discord.NotFound:
                continue
            if self.engine.staff(prior):
                staff.add(uid)
        if self.engine.staff(actor):
            staff.add(actor.id)
        return Actor(actor.id, actor.roles, frozenset(staff))

    async def reconcile_member(self, member: discord.Member) -> None:
        if not self._validated.is_set() or member.guild.id != self.guild_id or member.bot:
            return
        if self.store.get('member', str(member.id)) is None:
            return
        if self.engine.c['mode'] == 'test' and str(member.id) not in self.engine.c['founder_ids']:
            return
        async with self._role_lock:
            member = await member.guild.fetch_member(member.id)
            self.refresh_timeout(member)
            self.engine.queue_promotion(self.engine.member(str(member.id)))
            add_ids, remove_ids = role_delta({r.id for r in member.roles},
                self.engine.desired_roles(str(member.id)), self._role_ids)
            # Remove stale faction/Council access before granting new access.
            if remove_ids:
                await member.remove_roles(*(discord.Object(id=x) for x in remove_ids), atomic=True,
                                          reason='Galactic Nexus policy reconciliation')
            if add_ids:
                await member.add_roles(*(discord.Object(id=x) for x in add_ids), atomic=True,
                                       reason='Galactic Nexus policy reconciliation')

    @tasks.loop(minutes=2)
    async def reconcile_loop(self) -> None:
        guild = self.get_guild(self.guild_id)
        if guild:
            for uid in self.store.all('member'):
                try:
                    await self.reconcile_member(await guild.fetch_member(int(uid)))
                except discord.NotFound:
                    continue
                except discord.HTTPException:
                    # State remains durable; the next pass retries reconciliation.
                    continue

    @reconcile_loop.before_loop
    async def before_reconcile(self) -> None:
        await self._validated.wait()

    async def policy(self, interaction: discord.Interaction, action: str, target: str | None = None,
                     **args: Any) -> dict[str, Any]:
        await interaction.response.defer(ephemeral=True)
        target = target or str(interaction.user.id)
        args.setdefault("reason", f"Discord command /{action}")
        try:
            actor = await self.fresh_actor(interaction, action, target)
            token, preview = self.engine.preview(actor, action, target, args)
        except (ValueError, discord.HTTPException) as exc:
            await interaction.edit_original_response(content=f'Cannot prepare action: {exc}')
            return {}
        details = preview_text(preview)
        if len(details) > 1700:
            await interaction.edit_original_response(content='Preview is too large to display safely. No action applied.')
            return {}
        await interaction.edit_original_response(
            content="Review this change, then confirm within three minutes.\n\n"+details,
            allowed_mentions=discord.AllowedMentions.none(), view=ConfirmView(self, actor, token, preview))
        return preview


class ConfirmView(discord.ui.View):
    def __init__(self, bot: NexusBot, actor: Actor, token: str, preview: dict[str, Any]):
        super().__init__(timeout=180)
        self.bot, self.actor, self.token, self.preview = bot, actor, token, preview

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.actor.id:
            await interaction.response.send_message("Only the requesting member can confirm this.", ephemeral=True)
            return
        try:
            await interaction.response.defer()
            item = self.bot.store.get('confirmation', self.token)
            if item is None:
                raise PolicyError('Confirmation unavailable.')
            actor = await self.bot.fresh_actor(interaction, item['action'], item['target'])
            self.bot.engine.confirm(actor, self.token)
            await interaction.edit_original_response(content="Applied and logged. Role updates will sync shortly.", view=None)
        except (ValueError, discord.HTTPException) as exc:
            used = self.bot.store.get('confirmation', self.token, {}).get('used', False)
            message = 'Saved; Discord response failed. Check /profile before retrying.' if used else f'Not applied: {exc}'
            await interaction.edit_original_response(content=message, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.actor.id or interaction.guild_id != self.bot.guild_id:
            await interaction.response.send_message('Only the requesting member can cancel this.', ephemeral=True)
            return
        await interaction.response.edit_message(content="Cancelled.", view=None)
        self.stop()


def register_commands(bot: NexusBot) -> None:
    guild = discord.Object(id=bot.guild_id)

    @bot.tree.command(name="join", description="Confirm the 17+ SFW rules and join the Nexus.", guild=guild)
    @app_commands.describe(age_confirmed="You confirm you are 17 or older.", rules_accepted="You accept the server rules.")
    async def join(i: discord.Interaction, age_confirmed: bool, rules_accepted: bool):
        await bot.policy(i, "join", age_confirmed=age_confirmed, rules_accepted=rules_accepted)

    @bot.tree.command(name="path", description="Choose or request a faction path.", guild=guild)
    @app_commands.choices(path=[app_commands.Choice(name="Jedi / Light Side", value="jedi"), app_commands.Choice(name="Sith / Dark Side", value="sith")])
    async def path(i: discord.Interaction, path: app_commands.Choice[str]):
        await bot.policy(i, "path", path=path.value)

    @bot.tree.command(name="voice-check", description="Confirm eligible voice participation for 15 minutes.", guild=guild)
    async def voice_check(i: discord.Interaction):
        await bot.policy(i, "voice-check")

    @bot.tree.command(name="interest", description="Toggle an optional notification role.", guild=guild)
    @app_commands.choices(role=[app_commands.Choice(name=x, value=x) for x in ("Game Nights", "Stream Alerts", "Events")])
    async def interest(i: discord.Interaction, role: app_commands.Choice[str]):
        await bot.policy(i, "interest", role=role.value, enabled=True)

    @bot.tree.command(name="profile", description="Show your current Nexus progression.", guild=guild)
    async def profile(i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        try:
            await bot.fresh_actor(i)
        except (PolicyError, discord.HTTPException) as exc:
            await i.edit_original_response(content=str(exc))
            return
        member = bot.engine.member(str(i.user.id))
        path = member['path']
        rank = RANKS[path][member['rank']] if path else 'Force Sensitive'
        await i.edit_original_response(content=f'Path: {path or "Not selected"}\nRank: {rank}\nTotal XP: {member["xp"]:,}')

    @bot.tree.command(name='faction-request', description='Ask staff to review a faction change exception.', guild=guild)
    async def faction_request(i: discord.Interaction, path: Literal['jedi','sith'], reason: str):
        await bot.policy(i, 'faction-request', path=path, reason=reason)

    @bot.tree.command(name='report', description='Submit a private concern or appeal to the staff queue.', guild=guild)
    async def report(i: discord.Interaction, reason: str):
        await bot.policy(i, 'report', reason=reason)

    @bot.tree.command(name='promotion-review', description='Review a pending promotion with a documented decision.', guild=guild)
    async def promotion_review(i: discord.Interaction, review_id: str, decision: Literal['approve','defer','deny','reopen'], reason: str):
        await bot.policy(i, 'promotion-review', review_id, decision=decision, reason=reason)

    @bot.tree.command(name='faction-review', description='Approve or deny a faction exception.', guild=guild)
    async def faction_review(i: discord.Interaction, review_id: str, decision: Literal['approve','deny'], reason: str):
        await bot.policy(i, 'faction-review', review_id, decision=decision, reason=reason)

    @bot.tree.command(name='award-xp', description='Award verified event participation with duplicate protection.', guild=guild)
    async def award_xp(i: discord.Interaction, member: discord.Member, amount: int, event_id: str, reason: str):
        await bot.policy(i, 'award-xp', str(member.id), amount=amount, event_id=event_id, reason=reason)

    @bot.tree.command(name='founder-test', description='Change your own test state with a confirmation.', guild=guild)
    async def founder_test(i: discord.Interaction, field: Literal['faction','rank','xp','path_xp','cooldown','eligibility','council'], value: str, reason: str):
        await bot.policy(i, 'founder-test', field=field, value=value, reason=reason)

    @bot.tree.command(name='override', description='Founder correction to a member’s progression, with an audit reason.', guild=guild)
    async def override(i: discord.Interaction, member: discord.Member, field: Literal['faction','rank','xp','path_xp','cooldown','eligibility'], value: str, reason: str):
        await bot.policy(i, 'override', str(member.id), field=field, value=value, reason=reason)

    @bot.tree.command(name='council-nominate', description='Open a lore Council appointment or removal motion.', guild=guild)
    async def council_nominate(i: discord.Interaction, member: discord.Member, purpose: Literal['appoint','remove','inactive','restore'], path: Literal['jedi','sith'], reason: str):
        await bot.policy(i, 'council-nominate', str(member.id), purpose=purpose, path=path, reason=reason)

    @bot.tree.command(name='council-vote', description='Cast a founder vote on an open motion.', guild=guild)
    async def council_vote(i: discord.Interaction, motion_id: str, vote: Literal['yes','no','abstain'], reason: str):
        await bot.policy(i, 'council-vote', motion_id, vote=vote, reason=reason)

    @bot.tree.command(name='council-finalize', description='Confirm a Council decision after the required votes.', guild=guild)
    async def council_finalize(i: discord.Interaction, motion_id: str, reason: str):
        await bot.policy(i, 'council-finalize', motion_id, reason=reason)

    @bot.tree.command(name='campaign-start', description='Start a new campaign while keeping previous seasons.', guild=guild)
    async def campaign_start(i: discord.Interaction, name: str, days: int, reason: str):
        await bot.policy(i, 'campaign-start', name=name, days=days, reason=reason)

    @bot.tree.command(name='influence', description='Award verified campaign participation.', guild=guild)
    async def influence(i: discord.Interaction, member: discord.Member, amount: int, event_id: str, reason: str):
        await bot.policy(i, 'influence', str(member.id), amount=amount, event_id=event_id, reason=reason)

    @bot.tree.command(name='campaign-finish', description='Review and confirm the current campaign result.', guild=guild)
    async def campaign_finish(i: discord.Interaction, reason: str):
        await bot.policy(i, 'campaign-finish', reason=reason)

    @bot.tree.command(name='campaign-edit', description='Adjust the current campaign name or duration.', guild=guild)
    async def campaign_edit(i: discord.Interaction, days: int, reason: str, name: str=''):
        await bot.policy(i,'campaign-edit',days=days,name=name,reason=reason)

    @bot.tree.command(name='standing', description='Add or clear a promotion hold without deleting XP.', guild=guild)
    async def standing(i: discord.Interaction, member: discord.Member, decision: Literal['add','clear'], reason: str, days: int=30, restriction_id: str=''):
        await bot.policy(i,'standing',str(member.id),decision=decision,reason=reason,days=days,restriction_id=restriction_id)

    @bot.tree.command(name='prestige', description='Grant or remove a special lore title.', guild=guild)
    async def prestige(i: discord.Interaction, member: discord.Member, title: Literal['Jedi Grand Master','Darth','Dark Lord of the Sith'], decision: Literal['grant','remove'], reason: str):
        await bot.policy(i,'prestige',str(member.id),title=title,decision=decision,reason=reason)

    @bot.tree.command(name='council-emergency-remove', description='Owner-only emergency removal of lore Council access.', guild=guild)
    async def council_emergency_remove(i: discord.Interaction, member: discord.Member, reason: str):
        await bot.policy(i,'council-emergency-remove',str(member.id),reason=reason)

    @bot.tree.command(name='configure', description='Founder-reviewed change to progression settings.', guild=guild)
    async def configure_setting(i: discord.Interaction, key: Literal['rank_thresholds','transfer_ranks','faction_cooldown_days','voice_checkin_minutes','campaign_days','inactivity_days','xp_per_minute'], value: str, reason: str):
        try:
            parsed = json.loads(value)
        except ValueError:
            await i.response.send_message('Enter a number, or a list such as [0,500,3000,14400,151200].',ephemeral=True)
            return
        await bot.policy(i,'configure',key=key,value=parsed,reason=reason)

    @bot.tree.command(name='campaign', description='Read the current Galactic Campaign scores.', guild=guild)
    async def campaign(i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        try:
            await bot.fresh_actor(i)
            cid=bot.store.get('meta','active_campaign')
            c=bot.store.get('campaign',cid) if cid else None
            text=(f'**{c["name"]}**\nJedi: {c["scores"]["jedi"]} | Sith: {c["scores"]["sith"]}\nStatus: {c["status"]}\nEnds: <t:{int(c["ends_at"])}:F>' if c else 'No campaign has started yet.')
            await i.edit_original_response(content=text,allowed_mentions=discord.AllowedMentions.none())
        except (PolicyError,discord.HTTPException) as exc:
            await i.edit_original_response(content=str(exc))

    @bot.tree.command(name='dashboard', description='Read private pending staff reviews.', guild=guild)
    async def dashboard(i: discord.Interaction, section: Literal['reviews','reports','councils','members','logs','delivery']='reviews', page: app_commands.Range[int,1,10000]=1):
        await i.response.defer(ephemeral=True)
        try:
            actor = await bot.fresh_actor(i)
            if not bot.engine.staff(actor):
                raise PolicyError('Staff access required.')
            if section=='reviews':
                records = [q for q in bot.store.all('proposal').values() if q['status'] in {'pending','deferred'} and (q['kind']!='council' or bot.engine.founder(actor))]
                rows = [f'{q["id"]} | {q["kind"]} | <@{q["member"]}> | {q["status"]}' for q in records]
            elif section=='reports':
                rows = [f'{rid} | <@{r["member"]}> | {r["reason"][:300]}' for rid,r in bot.store.all('report').items()]
            elif section=='councils':
                if not bot.engine.founder(actor):
                    raise PolicyError('Founder access required for Council records.')
                rows = [f'<@{s["member"]}> | {s["path"]} | {s["status"]}' for s in bot.store.all('council').values()]
            elif section=='members':
                rows = [f'<@{uid}> | {m["path"] or "unselected"} | rank {m["rank"]} | {m["xp"]} XP | holds: '+', '.join(bot.engine.active_restrictions(m)) for uid,m in bot.store.all('member').items()]
            elif section=='logs':
                logs=bot.store.db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 10000').fetchall()
                rows=[f'{r["id"]} | {r["action"]} | actor {r["actor"]} | target {r["target"]} | {r["reason"][:100]}' for r in logs]
            else:
                rows=[f'{r["id"][:12]} | {r["kind"]} | tries {r["attempts"]} | {r["last_error"]}' for r in bot.store.db.execute('SELECT * FROM outbox WHERE delivered=0 ORDER BY rowid')]
            content='\n'.join(rows[(page-1)*5:page*5]) or 'No records on this page.'
            await i.edit_original_response(content=f'**{section.title()} — page {page}**\n'+content[:1800], allowed_mentions=discord.AllowedMentions.none())
        except (PolicyError, discord.HTTPException) as exc:
            await i.edit_original_response(content=str(exc))


async def run_bot(config, token):
    if config.get("mode") != "test":
        raise RuntimeError('This release is for private founder testing. Live launch requires the separate pre-launch review.')
    db_dir = Path(config.get("database_dir", "data"))
    bot = NexusBot(config, db_path=db_dir / "test.sqlite3")
    register_commands(bot)
    async with bot:
        await bot.start(token)
    if bot._startup_error:
        raise RuntimeError(bot._startup_error)


def main():
    from .launch import main as launch
    launch()


if __name__ == "__main__":
    main()
