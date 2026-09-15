"""Read-only Discord setup checks; never starts workers or writes local state.

Run with python -m nexus.diagnose. This separate troubleshooting command can
inspect Discord before persistent storage is available. Hosted plan/configure/
run/backup actions still require their verified mounted volume.
"""
import asyncio
import json
import os
from pathlib import Path

import discord

from .blueprint import ROLE_PERMISSIONS, STAFF
from .server_config import (missing_setup_permissions, permission_label, plan,
                            resolve_roles, role_changes)


def inspect_guild(guild, config):
    if not guild or str(guild.owner_id) != config['owner_id']:
        raise RuntimeError('Configured server is unavailable or its owner does not match.')
    roles = resolve_roles(guild, config.get('role_ids'))
    bot_role = guild.me.top_role
    governance = set(STAFF) | {'Server Owner'}
    progression = set(roles) - governance
    issues = []
    if guild.me.guild_permissions.administrator:
        issues.append('Remove Administrator from the bot.')
    if any(roles[name] >= bot_role for name in progression):
        issues.append('Move the bot above progression roles and below Moderator.')
    if any(roles[name] <= bot_role for name in governance):
        issues.append('Keep every staff and owner role above the bot.')
    for name in sorted(governance):
        expected = discord.Permissions(**{p: True for p in ROLE_PERMISSIONS[name]})
        if roles[name].permissions != expected:
            issues.append('Owner must correct blueprint permissions for ' + name + '.')
    actions = plan(guild, roles, bot_role)
    changes = role_changes(guild, roles, progression)
    missing = missing_setup_permissions(guild, actions, changes)
    issues.extend('Setup permission needed: ' + permission_label(p) for p in missing)
    # Guild-level grants can be masked by an existing private-channel overwrite.
    # Report every affected planned resource in one read-only pass.
    resources = {channel.id: channel for channel in guild.channels}
    access_issues = []
    for action in actions:
        channel = resources.get(action.get('id'))
        if channel is None:
            continue
        effective = channel.permissions_for(guild.me)
        absent = [p for p in ('view_channel', 'send_messages', 'read_message_history',
                              'embed_links', 'attach_files') if not getattr(effective, p)]
        if absent:
            access_issues.append({'resource': action.get('key', action['name']),
                                  'id': str(channel.id),
                                  'missing': [permission_label(p) for p in absent]})
    if access_issues:
        issues.append('Owner must restore bot access to the listed planned categories/channels.')
    return {
        'diagnostic_only': True,
        'discord_mutations': False,
        'owner_verified': True,
        'resolved_human_roles': len(roles),
        'planned_categories': sum(a['kind'] == 'category' for a in actions),
        'planned_channels': sum(a['kind'] in {'text', 'voice'} for a in actions),
        'missing_channels': sum(a['kind'] in {'text', 'voice'} and a['id'] is None for a in actions),
        'duplicate_channels_to_preserve': sum(a['kind'] == 'archive-duplicate' for a in actions),
        'roles_needing_permission_repair': [r.name for r, _ in changes],
        'setup_issues': issues,
        'channel_access_issues': access_issues,
        'next_step': 'Attach persistent /data storage, then run hosted plan before configuration.',
    }


async def diagnose(config, token):
    class Inspector(discord.Client):
        started = False
        report = None
        failure = None

        async def on_ready(self):
            if self.started:
                return
            self.started = True
            try:
                self.report = inspect_guild(self.get_guild(int(config['guild_id'])), config)
            except Exception as exc:
                self.failure = exc
            finally:
                await self.close()

    async with Inspector(intents=discord.Intents.default()) as client:
        await client.start(token)
    if client.failure:
        raise client.failure
    if client.report is None:
        raise RuntimeError('Discord did not provide a diagnostic result.')
    return client.report


def main():
    token = os.environ.get('NEXUS_TOKEN', '').strip()
    if not token:
        print('Diagnostic blocked: set NEXUS_TOKEN privately in the host variables.', flush=True)
        return 1
    try:
        config = json.loads((Path(__file__).resolve().parents[1] / 'config.example.json').read_text())
        if config.get('mode') != 'test':
            raise RuntimeError('Diagnostic is restricted to the private test configuration.')
        report = asyncio.run(asyncio.wait_for(diagnose(config, token), timeout=60))
        print(json.dumps(report, indent=2), flush=True)
        print('DIAGNOSTIC COMPLETE. No Discord changes applied; the bot is not running.', flush=True)
        return 1 if report['setup_issues'] else 0
    except discord.LoginFailure:
        print('Diagnostic blocked: Discord rejected the configured bot credential.', flush=True)
    except discord.HTTPException as exc:
        print(f'Diagnostic blocked: Discord HTTP {exc.status}, code {exc.code}.', flush=True)
    except (RuntimeError, ValueError, OSError) as exc:
        # These are controlled validation/local failures; do not print HTTP requests.
        print('Diagnostic blocked: ' + str(exc), flush=True)
    except discord.DiscordException:
        print('Diagnostic blocked: Discord connection failed.', flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
