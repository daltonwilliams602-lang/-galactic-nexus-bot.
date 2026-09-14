"""Local Windows-friendly setup and launcher. Never persists a bot token."""
import asyncio
from contextlib import contextmanager
import getpass
import json
import os
from pathlib import Path
import sys
import time
import discord
from .blueprint import CONTENT, ROLE_PERMISSIONS
from .server_config import (resolve_roles, plan, apply_channels, check_permissions, configure_native_safety,
                            role_changes, apply_role_changes, require_setup_permissions, setup_step, permission_label)
from .storage import Store


@contextmanager
def instance_lock(path):
    handle = open(path,'a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if handle.tell()==0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('Another Nexus process is using this project. Close it before starting a second copy.')
    try:
        yield
    finally:
        handle.close()


def write_json(path, data):
    path = Path(path)
    staging = path.with_suffix(path.suffix+'.new')
    staging.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    os.replace(staging,path)


def token_input():
    token = os.environ.get('NEXUS_TOKEN')
    if token:
        return token
    if not sys.stdin.isatty():
        raise RuntimeError('Use an interactive terminal to enter the token privately.')
    token = getpass.getpass('Paste the Discord BOT token (hidden; not saved): ').strip()
    if not token:
        raise RuntimeError('No token entered.')
    return token


async def configure(config_path, config, token, *, confirmation=None, plan_only=False, output_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)
    class ConfigureClient(discord.Client):
        started = False
        failure = None
        configured = False

        async def on_ready(self):
            if self.started:
                return
            self.started = True
            try:
                self.configured = await self.configure_guild()
            except Exception as exc:
                self.failure = exc
            finally:
                await self.close()

        async def configure_guild(self):
            guild = self.get_guild(int(config['guild_id']))
            if not guild or str(guild.owner_id)!=config['owner_id']:
                raise RuntimeError('Bot is not in the configured server, or its owner does not match Dalton’s supplied ID.')
            me = guild.me
            if me.guild_permissions.administrator:
                raise RuntimeError('Remove Administrator from the bot. Setup will list its required individual permissions.')
            roles = resolve_roles(guild,config.get('role_ids'))
            bot_role = me.top_role
            from .bot import PROGRESSION_ROLES
            if any(roles[n]>=bot_role for n in PROGRESSION_ROLES):
                raise RuntimeError('Move the bot role above Jedi Grand Master and below Moderator, then retry.')
            if any(roles[n]<=bot_role for n in set(roles)-PROGRESSION_ROLES):
                raise RuntimeError('Keep every owner and staff role above the bot.')
            # Never use temporary privilege escalation to edit staff/owner roles.
            for name in set(roles)-PROGRESSION_ROLES:
                expected = discord.Permissions(**{p:True for p in ROLE_PERMISSIONS[name]})
                if roles[name].permissions.value != expected.value:
                    raise RuntimeError(f'Staff role {name} differs from the blueprint. Owner must correct it in Discord; setup will not raise the bot above staff.')
            actions = plan(guild,roles,bot_role)
            changes = role_changes(guild, roles, PROGRESSION_ROLES)
            require_setup_permissions(guild, actions, changes)
            stamp = str(time.time_ns())
            backup = Path(config.get('backup_dir','backups'))
            backup.mkdir(parents=True,exist_ok=True)
            snapshot = {'guild_id':str(guild.id),'config':config,
                'settings':{'verification_level':guild.verification_level.value,'explicit_content_filter':guild.explicit_content_filter.value,
                            'default_notifications':guild.default_notifications.value,'system_channel_id':getattr(guild.system_channel,'id',None)},
                'roles':[{'id':str(r.id),'name':r.name,'permissions':r.permissions.value,'position':r.position} for r in guild.roles],
                'channels':[{'id':str(c.id),'name':c.name,'type':str(c.type),
                             'category_id':str(getattr(c,'category_id',None)),
                             'permissions':{str(r.id):[o.pair()[0].value,o.pair()[1].value] for r,o in c.overwrites.items()}}
                            for c in guild.channels]}
            with setup_step('backing up existing AutoMod rules', 'Check Manage Server on the bot role.'):
                snapshot['automod']=[{'id':str(r.id),'name':r.name,'enabled':r.enabled,'trigger_type':r.trigger.type.value,
                                     'metadata':r.trigger.to_metadata_dict(),'actions':[a.to_dict() for a in r.actions]}
                                    for r in await guild.fetch_automod_rules()]
            write_json(backup/f'server-before-{stamp}.json',snapshot)
            write_json(output_dir/'configuration-plan.json',{'guild':guild.name,'guild_id':str(guild.id),'actions':actions,
                'role_changes':[{'id':str(role.id),'name':role.name,'permissions':permissions.value}
                                for role,permissions in changes]})
            print(f'\nServer: {guild.name} ({guild.id})')
            print(f'Owner: {guild.owner_id}. Founders: '+', '.join(config['founder_ids']))
            print('Plan: repair category/channel access from the blueprint; create missing rooms; restrict @everyone; normalize progression permissions; seed missing guide posts.')
            print('Native safety: medium verification, SFW media filtering, mentions-only notifications, anti-hate/explicit-content presets, mention-spam and suspected-spam AutoMod. Normal profanity stays allowed.')
            for a in actions:
                if a['kind']=='archive-duplicate':
                    print(f'Preserve duplicate channel {a["id"]} as {a["name"]} with founder-only access.')
            print('No channels, members, roles, XP, campaigns, or history will be deleted. No invitations will be sent.')
            print('Review configuration-plan.json and the saved server-before backup.')
            if plan_only:
                print('Plan only. No Discord changes applied.')
                return False
            answer = confirmation
            if answer is None:
                answer = await asyncio.to_thread(input,'Type CONFIGURE PRIVATE TEST SERVER to apply, or Enter to cancel: ')
            if answer != 'CONFIGURE PRIVATE TEST SERVER':
                print('Cancelled. No Discord changes applied.')
                return False
            await apply_role_changes(changes)
            channel_ids = await apply_channels(guild,roles,bot_role,actions)
            config.update(role_ids={n:str(r.id) for n,r in roles.items()},channel_ids=channel_ids)
            write_json(config_path,config)
            # Re-fetch actual API state for the technical permission test.
            with setup_step('checking live role and channel permissions'):
                fresh_roles = await guild.fetch_roles()
                fresh_channels = await guild.fetch_channels()
            # A small read-only facade avoids modifying discord.py caches.
            from types import SimpleNamespace
            categories = []
            for c in fresh_channels:
                if isinstance(c,discord.CategoryChannel):
                    categories.append(SimpleNamespace(name=c.name,overwrites=c.overwrites,
                        channels=[x for x in fresh_channels if getattr(x,'category_id',None)==c.id]))
            facade = SimpleNamespace(default_role=next(r for r in fresh_roles if r.is_default()),categories=categories)
            fresh_map = {n:next(r for r in fresh_roles if r.id==roles[n].id) for n in roles}
            issues = check_permissions(facade,fresh_map,bot_role,channel_ids)
            if issues:
                raise RuntimeError('Post-configuration check failed: '+'; '.join(issues))
            await configure_native_safety(guild,int(channel_ids['STAFF/mod-logs']))
            write_json(output_dir/'permission-check.json',{'checked_at':time.time(),'guild_id':str(guild.id),'issues':[],'channels':channel_ids})
            for name,content in CONTENT.items():
                ids = [int(cid) for key,cid in channel_ids.items() if key.endswith('/'+name)]
                if len(ids)!=1:
                    continue
                channel = next(c for c in fresh_channels if c.id==ids[0])
                with setup_step('checking the guide post in #'+name,
                                'Check View Channels, Read Message History, and Send Messages for the bot in this channel.'):
                    history = [m async for m in channel.history(limit=1)]
                    if not history:
                        await channel.send(content,allowed_mentions=discord.AllowedMentions.none())
            normal = discord.Permissions(**{p:True for p in ROLE_PERMISSIONS['Galactic Nexus']})
            temporary = discord.Permissions(bot_role.permissions.value & ~normal.value)
            print('Configuration passed. In Server Settings > Roles > Galactic Nexus > Permissions, turn off:')
            for name, enabled in temporary:
                if enabled:
                    print('  - '+permission_label(name))
            print('Manage Channels and Manage Server must be off before Start Bot. Keep Manage Roles and the normal message/audit permissions.')
            print('Assign Founding Council to each of the four verified founders in Discord when they join. Keep staff roles above the bot.')
            return True

    client = ConfigureClient(intents=discord.Intents.default())
    async with client:
        await client.start(token)
    if client.failure:
        raise client.failure
    return client.configured


def main():
    os.chdir(Path(__file__).resolve().parents[1])
    config_path = Path('config.local.json')
    if not config_path.exists():
        write_json(config_path,json.loads(Path('config.example.json').read_text()))
    config = json.loads(config_path.read_text())
    print('GALACTIC NEXUS — PRIVATE FOUNDER TESTING — SETUP FIX v1.2\n1. Configure/check server\n2. Start bot\n3. Back up test data\n4. Exit')
    choice = input('Choose 1–4: ').strip()
    if choice=='4':
        return
    with instance_lock('.nexus.lock'):
        if choice=='3':
            path = Path(config.get('database_dir','data'))/'test.sqlite3'
            if not path.exists():
                print('No test database exists yet.')
                return
            store = Store(path)
            try:
                print('Backup saved:',store.backup(config.get('backup_dir','backups')))
            finally:
                store.close()
        elif choice in {'1','2'}:
            token = token_input()
            if choice=='1':
                asyncio.run(configure(config_path,config,token))
            else:
                from .bot import run_bot
                asyncio.run(run_bot(config,token))
        else:
            print('No action selected.')


if __name__=='__main__':
    try:
        main()
    except (RuntimeError,ValueError,discord.DiscordException,OSError) as exc:
        print('Stopped:',str(exc))
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('\nStopped. Saved progression remains intact.')
