"""Inspectable, repeatable server configuration through an authorized bot account.

No deletions, member XP edits, governance-role grants, or public launch actions.
"""
import json
from contextlib import contextmanager
from pathlib import Path
import discord
from .blueprint import CATEGORIES, ROLE_ORDER, ROLE_PERMISSIONS, READ_ONLY, STAFF, audience


@contextmanager
def setup_step(label, permission_hint='Check the bot role and the permissions on the named channel.'):
    """Keep Discord failures tied to the operation, without exposing requests/tokens."""
    print('[Setup] '+label, flush=True)
    try:
        yield
    except discord.HTTPException as exc:
        hint = permission_hint if exc.status == 403 else 'Keep this error message for review.'
        raise RuntimeError(
            f'Configuration stopped while {label}.\n'
            f'Discord returned HTTP {exc.status}, error {exc.code}. {hint}\n'
            'Earlier completed steps are retained. Keep this folder and rerun option 1 after correcting the problem.'
        ) from exc


def role_changes(guild, roles, editable):
    """Do not rewrite roles that already match, including @everyone."""
    desired = [(guild.default_role, discord.Permissions(read_message_history=True, use_application_commands=True,
        create_instant_invite=guild.default_role.permissions.create_instant_invite))]
    desired += [(roles[name], discord.Permissions(**{p: True for p in ROLE_PERMISSIONS[name]}))
                for name in ROLE_ORDER if name in editable]
    return [(role, permissions) for role, permissions in desired if role.permissions != permissions]


async def apply_role_changes(changes):
    for role, permissions in changes:
        with setup_step('updating role '+role.name+' ('+str(role.id)+')',
                        'Check Manage Roles, the permissions listed by setup, and the bot role order.'):
            await role.edit(permissions=permissions, reason='Reviewed Nexus private role permissions')


def missing_setup_permissions(guild, actions, changes):
    """Check allow AND deny bits, including powers lost when @everyone is reduced.

    Discord requires possession of permissions written to role/channel settings.
    Use guild permissions so newly created channels have the same prerequisites.
    Never count a temporary @everyone permission that this run will remove.
    """
    required = discord.Permissions(**{p: True for p in ROLE_PERMISSIONS['Galactic Nexus']},
                                   manage_channels=True, manage_guild=True).value
    for _, permissions in changes:
        required |= permissions.value
    current_channels = {channel.id: channel for channel in guild.channels}
    for action in actions:
        for allow, deny in action.get('permissions', {}).values():
            required |= allow | deny
        current = current_channels.get(action.get('id'))
        if current is not None:
            # Replacing the overwrite map also removes old allow/deny bits.
            # Private-category UI defaults can add Connect even to text roles.
            for allow, deny in signature(current.overwrites).values():
                required |= allow | deny
    replacements = {role.id: permissions.value for role, permissions in changes}
    future = 0
    for role in guild.me.roles:
        future |= replacements.get(role.id, role.permissions.value)
    available = guild.me.guild_permissions.value & future
    return [name for name, enabled in discord.Permissions(required & ~available) if enabled]


def permission_label(name):
    return {'manage_guild': 'Manage Server', 'view_channel': 'View Channels',
            'external_emojis': 'Use External Emojis', 'external_stickers': 'Use External Stickers',
            'stream': 'Video', 'use_voice_activation': 'Use Voice Activity',
            'use_embedded_activities': 'Use Activities'}.get(name, name.replace('_', ' ').title())


def require_setup_permissions(guild, actions, changes):
    missing = missing_setup_permissions(guild, actions, changes)
    if missing:
        labels = '\n'.join('  - '+permission_label(name) for name in missing)
        raise RuntimeError(
            'Configuration has not started. The bot needs these permissions for the planned changes:\n'+labels+
            '\nIn Discord: Server Settings > Roles > Galactic Nexus > Permissions.\n'
            'Enable the listed permissions on the bot role, click Save Changes, then reopen Start-Nexus.cmd and choose 1.\n'
            'Leave Administrator off and keep the bot below Moderator. Setup will list the permissions to remove when it finishes.'
        )


def automod_specs():
    return [
        ('Nexus • SFW and anti-hate',discord.AutoModTrigger(presets=discord.AutoModPresets(slurs=True,sexual_content=True,profanity=False))),
        ('Nexus • Mention spam',discord.AutoModTrigger(mention_limit=5,mention_raid_protection=True)),
        ('Nexus • Suspected spam',discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.spam)),
    ]


async def configure_native_safety(guild, alert_channel_id):
    with setup_step('updating native SFW and notification settings', 'Check Manage Server on the bot role.'):
        await guild.edit(verification_level=discord.VerificationLevel.medium,
                         explicit_content_filter=discord.ContentFilter.all_members,
                         default_notifications=discord.NotificationLevel.only_mentions,system_channel=None,
                         reason='Reviewed Nexus SFW and notification settings')
    with setup_step('reading existing AutoMod rules', 'Check Manage Server on the bot role.'):
        existing=await guild.fetch_automod_rules()
    for name,trigger in automod_specs():
        owned=[r for r in existing if r.name==name]
        if len(owned)>1:
            raise RuntimeError('Duplicate AutoMod rule: '+name)
        actions=[discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message),
                 discord.AutoModRuleAction(channel_id=alert_channel_id)]
        kwargs=dict(name=name,trigger=trigger,actions=actions,enabled=True,exempt_roles=[],exempt_channels=[],
                    reason='Reviewed Nexus AutoMod; normal profanity remains allowed')
        if owned:
            with setup_step('updating AutoMod rule '+name, 'Check Manage Server and access to STAFF/mod-logs for the bot.'):
                await owned[0].edit(**kwargs)
        else:
            if any(r.trigger.type==trigger.type for r in existing):
                raise RuntimeError('An existing AutoMod rule uses this trigger. Review it before installing '+name)
            with setup_step('creating AutoMod rule '+name, 'Check Manage Server and access to STAFF/mod-logs for the bot.'):
                await guild.create_automod_rule(event_type=discord.AutoModRuleEventType.message_send,**kwargs)


def overrides(guild, roles, bot_role, category, channel=None):
    result = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for name in audience(category, channel):
        role = guild.default_role if name == '@everyone' else roles[name]
        result[role] = discord.PermissionOverwrite(view_channel=True)
    if category == 'ARRIVAL' or channel in READ_ONLY:
        for overwrite in result.values():
            overwrite.send_messages = False
            overwrite.send_messages_in_threads = False
            overwrite.create_public_threads = False
            overwrite.create_private_threads = False
        # Read-only posts are maintained by founders; staff can discuss in staff-chat.
        result[roles['Founding Council']] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                                        read_message_history=True)
    result[bot_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
        embed_links=True, attach_files=True, read_message_history=True)
    return result


def signature(overwrites):
    return {str(target.id): (ow.pair()[0].value, ow.pair()[1].value) for target, ow in overwrites.items()}


def resolve_roles(guild, configured=None):
    required = set(ROLE_ORDER)-{'Galactic Nexus'}
    result = {}
    configured = configured or {}
    for name in required:
        choices = [r for r in guild.roles if r.name == name and not r.managed and not r.is_default()]
        if len(choices) != 1:
            raise RuntimeError(f'Expected exactly one role named {name}; found {len(choices)}. No automatic role creation or deletion.')
        role = choices[0]
        if name in configured and str(role.id) != str(configured[name]):
            raise RuntimeError(f'Previously recorded role ID changed: {name}. Review it manually.')
        result[name] = role
    return result


def check_permissions(guild, roles, bot_role, channel_ids):
    problems = []
    expected_everyone = discord.Permissions(read_message_history=True, use_application_commands=True,
        create_instant_invite=guild.default_role.permissions.create_instant_invite)
    if guild.default_role.permissions.value != expected_everyone.value:
        problems.append('@everyone permissions differ from the blueprint')
    for name, role in roles.items():
        expected = discord.Permissions(**{p:True for p in ROLE_PERMISSIONS[name]})
        if role.permissions.value != expected.value:
            problems.append(f'Role permissions differ: {name}')
    for category, names in CATEGORIES.items():
        matches = [c for c in guild.categories if c.name == category]
        if len(matches) != 1:
            problems.append(f'Expected one category: {category}')
            continue
        parent = matches[0]
        if signature(parent.overwrites) != signature(overrides(guild,roles,bot_role,category)):
            problems.append(f'Category permissions differ: {category}')
        for item in names:
            name = item.removeprefix('vc:')
            kind = discord.VoiceChannel if item.startswith('vc:') else discord.TextChannel
            matches = [c for c in parent.channels if c.name == name and isinstance(c,kind)]
            key = category+'/'+item
            if len(matches) != 1 or str(channel_ids.get(key)) != str(matches[0].id):
                problems.append(f'Channel missing, duplicated, or changed: {key}')
            elif signature(matches[0].overwrites) != signature(overrides(guild,roles,bot_role,category,name)):
                problems.append(f'Channel permissions differ: {key}')
    return problems


def plan(guild, roles, bot_role):
    """A plan binds existing IDs and proposed overwrites for human review."""
    actions = []
    for position, (category, names) in enumerate(CATEGORIES.items()):
        matches = [c for c in guild.categories if c.name == category]
        if len(matches)>1:
            raise RuntimeError(f'Duplicate category: {category}. Review manually.')
        parent = matches[0] if matches else None
        actions.append({'kind':'category','name':category,'id':parent.id if parent else None,'position':position,
                        'permissions':signature(overrides(guild,roles,bot_role,category))})
        for item in names:
            name = item.removeprefix('vc:')
            kind = discord.VoiceChannel if item.startswith('vc:') else discord.TextChannel
            matches = [c for c in (parent.channels if parent else []) if c.name==name and isinstance(c,kind)]
            if len(matches)>1:
                matches.sort(key=lambda c:c.id)
                for extra in matches[1:]:
                    actions.append({'kind':'archive-duplicate','id':extra.id,'name':name+'-duplicate-'+str(extra.id)[-4:],
                                    'permissions':signature(overrides(guild,roles,bot_role,'FOUNDER TESTING','test-results')),
                                    'note':'Preserve all messages; restrict this extra construction channel to founders.'})
            actions.append({'kind':'voice' if item.startswith('vc:') else 'text','category':category,'name':name,
                            'key':category+'/'+item,'id':matches[0].id if matches else None,
                            'permissions':signature(overrides(guild,roles,bot_role,category,name))})
    return actions


async def apply_channels(guild, roles, bot_role, actions):
    channels = {}
    parents = {}
    pending_cleanup = {}
    try:
        return await _apply_channels(guild, roles, bot_role, actions, channels, parents, pending_cleanup)
    finally:
        # ARRIVAL denies threads to members. Keep the approved bot-only thread
        # access until child edits finish, then remove it even after a failure.
        for name, parent in pending_cleanup.items():
            with setup_step('removing temporary category permissions from '+name):
                await parent.edit(overwrites=overrides(guild, roles, bot_role, name),
                                  reason='Remove temporary Nexus setup thread permissions')


async def _apply_channels(guild, roles, bot_role, actions, channels, parents, pending_cleanup):
    for action in actions:
        existing = guild.get_channel(action['id']) if action['id'] else None
        if action['kind']=='archive-duplicate':
            with setup_step('preserving duplicate channel '+action['name']+' ('+str(action['id'])+')'):
                await existing.edit(name=action['name'],overwrites=overrides(guild,roles,bot_role,'FOUNDER TESTING','test-results'),
                                    reason='Reviewed preservation of duplicate construction channel')
        elif action['kind']=='category':
            name = action['name']
            permissions = overrides(guild,roles,bot_role,name)
            if name == 'ARRIVAL':
                # Discord checks parent-channel permissions when editing a child.
                # Guild-level thread grants alone are masked by ARRIVAL's denies.
                permissions[bot_role].update(create_public_threads=True,
                    create_private_threads=True, send_messages_in_threads=True)
            if existing:
                with setup_step('updating category '+name+' ('+str(existing.id)+')'):
                    existing = await existing.edit(overwrites=permissions, position=action['position'], reason='Reviewed Nexus configuration')
            else:
                with setup_step('creating category '+name):
                    existing = await guild.create_category(name, overwrites=permissions, position=action['position'], reason='Reviewed Nexus configuration')
            parents[name] = existing
            if name == 'ARRIVAL':
                pending_cleanup[name] = existing
        else:
            parent = parents[action['category']]
            permissions = overrides(guild,roles,bot_role,action['category'],action['name'])
            if existing:
                # Reapply after category edits: Discord can have synchronized the child.
                with setup_step('updating channel '+action['key']+' ('+str(existing.id)+')'):
                    await existing.edit(overwrites=permissions, reason='Reviewed Nexus configuration')
            else:
                create = guild.create_voice_channel if action['kind']=='voice' else guild.create_text_channel
                with setup_step('creating channel '+action['key']):
                    existing = await create(action['name'], category=parent, overwrites=permissions, reason='Reviewed Nexus configuration')
            channels[action['key']] = str(existing.id)
    return channels
