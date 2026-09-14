import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from nexus.blueprint import ROLE_ORDER, ROLE_PERMISSIONS
from nexus.diagnose import diagnose, inspect_guild


def fixture():
    config = {'guild_id': '999', 'owner_id': '123'}
    guild = SimpleNamespace(id=999, owner_id=123, roles=[], categories=[], channels=[])
    guild.default_role = discord.Role(guild=guild, state=None, data={
        'id': '999', 'name': '@everyone', 'permissions': str(discord.Permissions(
            read_message_history=True, use_application_commands=True).value)})
    guild.roles.append(guild.default_role)
    for position, name in enumerate(reversed(ROLE_ORDER), 1):
        permissions = discord.Permissions(**{p: True for p in ROLE_PERMISSIONS[name]})
        if name == 'Galactic Nexus':
            permissions.update(manage_channels=True, manage_guild=True,
                               create_public_threads=True, create_private_threads=True,
                               send_messages_in_threads=True)
        guild.roles.append(discord.Role(guild=guild, state=None, data={
            'id': str(position), 'position': position, 'name': name,
            'permissions': str(permissions.value)}))
    bot_role = next(r for r in guild.roles if r.name == 'Galactic Nexus')
    guild.me = SimpleNamespace(top_role=bot_role, roles=[guild.default_role, bot_role],
        guild_permissions=discord.Permissions(bot_role.permissions.value | guild.default_role.permissions.value))
    return guild, config


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_inspection_never_writes_state_or_changes_discord(self):
        guild, config = fixture()
        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): await self.close()
            def get_guild(self, guild_id): return guild
            async def start(self, token): await self.on_ready()
            async def close(self): pass
        with patch('nexus.diagnose.discord.Client', Client), \
             patch('nexus.storage.Store', side_effect=AssertionError('No database access')), \
             patch('pathlib.Path.write_text', side_effect=AssertionError('No state writes')), \
             patch('discord.Role.edit', new_callable=AsyncMock) as edit, \
             patch('discord.Guild.create_text_channel', new_callable=AsyncMock) as create:
            report = await diagnose(config, 'test-only-value')
        edit.assert_not_awaited()
        create.assert_not_awaited()
        self.assertFalse(report['discord_mutations'])
        self.assertEqual(report['setup_issues'], [])
        self.assertEqual(report['planned_categories'], 9)
        self.assertEqual(report['planned_channels'], 49)
        self.assertEqual(report['missing_channels'], 49)
        self.assertNotIn('test-only-value', str(report))

    def test_mismatched_owner_is_rejected_before_planning(self):
        guild, config = fixture()
        guild.owner_id = 456
        with patch('nexus.diagnose.plan') as plan:
            with self.assertRaisesRegex(RuntimeError, 'owner does not match'):
                inspect_guild(guild, config)
            plan.assert_not_called()

    def test_reports_missing_permissions_and_unsafe_bot_role(self):
        guild, config = fixture()
        guild.me.guild_permissions = discord.Permissions(administrator=True)
        report = inspect_guild(guild, config)
        self.assertIn('Remove Administrator from the bot.', report['setup_issues'])
        self.assertIn('Setup permission needed: Manage Server', report['setup_issues'])


if __name__ == '__main__':
    unittest.main()
