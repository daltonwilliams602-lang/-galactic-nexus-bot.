"""Persistence, non-interactive setup, and process lifecycle for cloud hosting."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, patch

import discord
from nexus.blueprint import ROLE_ORDER, ROLE_PERMISSIONS
from nexus.hosted import (SETUP_CONFIRMATION, execute, mounted_data_dir, prepare_state)
from nexus.launch import configure as configure_server, write_json
from nexus.storage import Store


class HostedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path, self.config = prepare_state(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def ready_config(self):
        self.config['role_ids'] = {'Member': '20'}
        self.config['channel_ids'] = {'FOUNDER TESTING/test-results': '30'}
        write_json(self.config_path, self.config)

    def test_ephemeral_directory_and_wrong_railway_volume_are_rejected(self):
        with patch('nexus.hosted.is_mounted', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Persistent volume is missing'):
                mounted_data_dir({'NEXUS_DATA_DIR': str(self.root)})
        with patch('nexus.hosted.is_mounted', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'Attach a Railway volume'):
                mounted_data_dir({'NEXUS_DATA_DIR': str(self.root), 'RAILWAY_SERVICE_ID': 'fixture'})
            self.assertEqual(mounted_data_dir({'NEXUS_DATA_DIR': str(self.root),
                'RAILWAY_SERVICE_ID': 'fixture', 'RAILWAY_VOLUME_MOUNT_PATH': str(self.root)}), self.root)

    def test_restart_preserves_configuration_progress_and_receipts(self):
        self.ready_config()
        self.config['xp_per_minute'] = 7
        write_json(self.config_path, self.config)
        database = self.root/'data'/'test.sqlite3'
        store = Store(database)
        store.put('member', 'fixture', {'xp': 1234, 'rank': 2})
        self.assertFalse(store.seen('already-awarded'))
        store.close()
        _, loaded = prepare_state(self.root)
        self.assertEqual(loaded['xp_per_minute'], 7)
        self.assertEqual(loaded['role_ids'], self.config['role_ids'])
        self.assertEqual(loaded['founder_ids'], self.config['founder_ids'])
        self.assertEqual(Path(loaded['database_dir']), self.root/'data')
        store = Store(database)
        try:
            self.assertEqual(store.get('member', 'fixture')['xp'], 1234)
            self.assertTrue(store.seen('already-awarded'))
        finally:
            store.close()

    def test_database_without_matching_configuration_is_not_reinitialized(self):
        store = Store(self.root/'data'/'test.sqlite3')
        store.close()
        self.config_path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'matching configuration'):
            prepare_state(self.root)
        self.assertFalse(self.config_path.exists())

    def test_hosting_does_not_enable_public_mode(self):
        self.config['mode'] = 'live'
        write_json(self.config_path, self.config)
        with self.assertRaisesRegex(RuntimeError, 'private founder testing only'):
            prepare_state(self.root)

    async def test_missing_secret_never_opens_an_interactive_prompt(self):
        with patch('builtins.input', side_effect=AssertionError('No terminal prompts')), \
             patch('nexus.hosted.run_bot', new_callable=AsyncMock) as run:
            with self.assertRaisesRegex(RuntimeError, 'Set NEXUS_TOKEN'):
                await execute('run', self.root, {})
            run.assert_not_awaited()

    async def test_cloud_preview_and_explicit_configuration_are_separate(self):
        with patch('nexus.hosted.configure', new_callable=AsyncMock, return_value=True) as configure, \
             patch('builtins.input', side_effect=AssertionError('No terminal prompts')):
            await execute('plan', self.root, {'NEXUS_TOKEN': 'test-only-value'})
            self.assertTrue(configure.call_args.kwargs['plan_only'])
            self.assertEqual(configure.call_args.kwargs['output_dir'], self.root/'review')
            configure.reset_mock()
            with self.assertRaisesRegex(RuntimeError, 'NEXUS_SETUP_CONFIRMATION'):
                await execute('configure', self.root, {'NEXUS_TOKEN': 'test-only-value'})
            configure.assert_not_awaited()
            with contextlib.redirect_stdout(io.StringIO()):
                await execute('configure', self.root, {'NEXUS_TOKEN': 'test-only-value',
                              'NEXUS_SETUP_CONFIRMATION': SETUP_CONFIRMATION})
            self.assertFalse(configure.call_args.kwargs['plan_only'])
            self.assertEqual(configure.call_args.kwargs['confirmation'], SETUP_CONFIRMATION)
        self.assertNotIn('test-only-value', self.config_path.read_text())

    async def test_cloud_plan_saves_review_without_discord_mutations(self):
        guild = Obj(id=int(self.config['guild_id']), owner_id=int(self.config['owner_id']),
                    name='Fixture', categories=[], channels=[], roles=[], system_channel=None,
                    verification_level=discord.VerificationLevel.medium,
                    explicit_content_filter=discord.ContentFilter.all_members,
                    default_notifications=discord.NotificationLevel.only_mentions,
                    fetch_automod_rules=AsyncMock(return_value=[]),
                    create_category=AsyncMock(side_effect=AssertionError('Plan must not create channels')))
        guild.default_role = discord.Role(guild=guild, state=None, data={
            'id': str(guild.id), 'name': '@everyone', 'permissions': str(discord.Permissions(
                read_message_history=True, use_application_commands=True).value)})
        guild.roles.append(guild.default_role)
        for position, name in enumerate(reversed(ROLE_ORDER), 1):
            permissions = discord.Permissions(**{p: True for p in ROLE_PERMISSIONS[name]})
            if name == 'Galactic Nexus':
                permissions.update(manage_guild=True, manage_channels=True,
                                   create_public_threads=True, create_private_threads=True,
                                   send_messages_in_threads=True)
            guild.roles.append(discord.Role(guild=guild, state=None, data={
                'id': str(position), 'position': position, 'name': name, 'permissions': str(permissions.value)}))
        bot_role = next(r for r in guild.roles if r.name == 'Galactic Nexus')
        guild.me = Obj(top_role=bot_role, roles=[guild.default_role, bot_role],
                       guild_permissions=discord.Permissions(bot_role.permissions.value | guild.default_role.permissions.value))
        class Client:
            def __init__(self, **kwargs): pass
            def get_guild(self, guild_id): return guild
            async def __aenter__(self): return self
            async def __aexit__(self, *args): await self.close()
            async def close(self): pass
            async def start(self, token): await self.on_ready()
        with patch('nexus.launch.discord.Client', Client), \
             patch('discord.Role.edit', new_callable=AsyncMock) as role_edit, \
             patch('builtins.input', side_effect=AssertionError('No terminal prompts')), \
             contextlib.redirect_stdout(io.StringIO()):
            result = await configure_server(self.config_path, self.config, 'test-only-value',
                confirmation=SETUP_CONFIRMATION, plan_only=True, output_dir=self.root/'review')
        self.assertFalse(result)
        role_edit.assert_not_awaited()
        guild.create_category.assert_not_awaited()
        self.assertTrue((self.root/'review'/'configuration-plan.json').exists())
        self.assertEqual(len(list((self.root/'backups').glob('server-before-*.json'))), 1)

    async def test_unexpected_bot_exit_is_a_failure_for_the_host_supervisor(self):
        self.ready_config()
        with patch('nexus.hosted.run_bot', new_callable=AsyncMock) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'The bot stopped'):
                await execute('run', self.root, {'NEXUS_TOKEN': 'test-only-value'})
            self.assertEqual(run.call_args.args[1], 'test-only-value')

    async def test_second_worker_cannot_configure_while_bot_holds_volume_lock(self):
        self.ready_config()
        started = asyncio.Event()
        async def running(*args):
            started.set()
            await asyncio.Event().wait()
        with patch('nexus.hosted.run_bot', side_effect=running), \
             patch('nexus.hosted.configure', new_callable=AsyncMock) as configure, \
             contextlib.redirect_stdout(io.StringIO()):
            task = asyncio.create_task(execute('run', self.root, {'NEXUS_TOKEN': 'test-only-value'}))
            await asyncio.wait_for(started.wait(), timeout=2)
            try:
                with self.assertRaisesRegex(RuntimeError, 'Another Nexus process'):
                    await execute('plan', self.root, {'NEXUS_TOKEN': 'test-only-value'})
                configure.assert_not_awaited()
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_backup_uses_persistent_location_and_does_not_make_empty_database(self):
        with self.assertRaisesRegex(RuntimeError, 'No test database exists'):
            await execute('backup', self.root, {})
        database = self.root/'data'/'test.sqlite3'
        self.assertFalse(database.exists())
        store = Store(database)
        store.put('member', 'fixture', {'xp': 200})
        store.close()
        with contextlib.redirect_stdout(io.StringIO()):
            await execute('backup', self.root, {})
        copies = list((self.root/'backups').glob('*.sqlite3'))
        self.assertEqual(len(copies), 1)
        copy = Store(copies[0])
        try:
            self.assertEqual(copy.get('member', 'fixture')['xp'], 200)
        finally:
            copy.close()

    @unittest.skipUnless(os.name == 'posix', 'Linux hosting process signal test')
    def test_sigterm_finishes_cleanup_and_preserves_saved_state(self):
        program = '''
import asyncio, sys
from nexus.hosted import graceful_shutdown
from nexus.storage import Store
async def operation():
    store = Store(sys.argv[1])
    try:
        store.put('state', 'progress', 1234)
        print('READY', flush=True)
        await asyncio.Event().wait()
    finally:
        store.put('state', 'closed', True)
        store.close()
asyncio.run(graceful_shutdown(operation()))
'''
        database = self.root/'signal-test.sqlite3'
        process = subprocess.Popen([sys.executable, '-c', program, str(database)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import select
            self.assertTrue(select.select([process.stdout], [], [], 10)[0], 'Child did not become ready')
            self.assertEqual(process.stdout.readline().strip(), 'READY')
            process.send_signal(signal.SIGTERM)
            output, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, error)
            self.assertIn('stopped cleanly', output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            process.stdout.close()
            process.stderr.close()
        store = Store(database)
        try:
            self.assertEqual(store.get('state', 'progress'), 1234)
            self.assertIs(store.get('state', 'closed'), True)
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()
