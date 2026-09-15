"""Regression checks for setup's Discord 50013 permission failure."""
import contextlib
import io
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

import discord
from nexus.blueprint import ROLE_PERMISSIONS
from nexus.server_config import (apply_channels, apply_role_changes, missing_setup_permissions,
                                  overrides, require_setup_permissions, role_changes, signature)


class SetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = Obj(id=1, owner_id=99, roles=[], channels=[])
        self.guild.get_role = lambda rid: next((r for r in self.guild.roles if r.id == rid), None)
        self.everyone = self.role(1, '@everyone', discord.Permissions(read_message_history=True, use_application_commands=True))
        self.guild.default_role = self.everyone
        self.bot_permissions = discord.Permissions(
            **{p: True for p in ROLE_PERMISSIONS['Galactic Nexus']}, manage_channels=True, manage_guild=True)
        self.bot_role = self.role(50, 'Galactic Nexus', self.bot_permissions)
        self.member_role = self.role(2, 'Member', discord.Permissions(**{p: True for p in ROLE_PERMISSIONS['Member']}))
        self.roles = {'Member': self.member_role, 'Founding Council': self.role(60, 'Founding Council', discord.Permissions.none())}
        self.guild.me = discord.Member(guild=self.guild,
            state=Obj(store_user=lambda data: discord.User(state=None, data=data)),
            data={'user': {'id': '90', 'username': 'fixture', 'discriminator': '0', 'avatar': None},
                  'flags': 0, 'roles': ['50']})
        self.actions = [{'kind': 'category', 'permissions': signature(
            overrides(self.guild, self.roles, self.bot_role, 'ARRIVAL'))}]

    def role(self, rid, name, permissions):
        role = discord.Role(guild=self.guild, state=None, data={
            'id': str(rid), 'name': name, 'position': rid, 'permissions': str(permissions.value)})
        self.guild.roles.append(role)
        return role

    def give_bot_threads(self):
        self.bot_permissions.update(create_public_threads=True, create_private_threads=True, send_messages_in_threads=True)
        self.bot_role._permissions = self.bot_permissions.value

    def test_original_setup_permissions_cannot_apply_readonly_thread_denials(self):
        self.assertTrue(self.guild.me.guild_permissions.manage_roles)
        self.assertTrue(self.guild.me.guild_permissions.manage_channels)
        self.assertTrue(self.guild.me.guild_permissions.manage_guild)
        self.assertEqual(set(missing_setup_permissions(self.guild, self.actions, [])),
                         {'create_public_threads', 'create_private_threads', 'send_messages_in_threads'})
        with self.assertRaisesRegex(RuntimeError, 'Create Private Threads'):
            require_setup_permissions(self.guild, self.actions, [])
        self.give_bot_threads()
        self.assertEqual(missing_setup_permissions(self.guild, self.actions, []), [])

    def test_existing_overwrite_removal_is_checked_before_setup(self):
        self.give_bot_threads()
        self.actions[0]['id'] = 100
        self.guild.channels = [Obj(id=100, overwrites={
            self.bot_role: discord.PermissionOverwrite(view_channel=True, connect=True)})]
        self.assertEqual(missing_setup_permissions(self.guild, self.actions, []), ['connect'])
        with self.assertRaisesRegex(RuntimeError, 'Connect'):
            require_setup_permissions(self.guild, self.actions, [])
        self.bot_role._permissions |= discord.Permissions(connect=True).value
        self.assertEqual(missing_setup_permissions(self.guild, self.actions, []), [])

    def test_permission_lost_when_everyone_is_restricted_is_detected(self):
        self.everyone._permissions |= discord.Permissions(create_private_threads=True).value
        self.assertTrue(self.guild.me.guild_permissions.create_private_threads)
        changes = role_changes(self.guild, self.roles, {'Member'})
        self.assertIn('create_private_threads', missing_setup_permissions(self.guild, self.actions, changes))

    def test_member_repair_requires_its_granted_permissions(self):
        self.give_bot_threads()
        self.member_role._permissions = 0
        changes = role_changes(self.guild, self.roles, {'Member'})
        missing = missing_setup_permissions(self.guild, self.actions, changes)
        self.assertIn('connect', missing)
        self.assertIn('speak', missing)
        self.assertIn('add_reactions', missing)
        for _, permissions in changes:
            self.bot_role._permissions |= permissions.value
        self.assertEqual(missing_setup_permissions(self.guild, self.actions, changes), [])

    async def test_matching_roles_skip_api_edits_and_extra_permissions(self):
        self.give_bot_threads()
        changes = role_changes(self.guild, self.roles, {'Member'})
        self.assertEqual(changes, [])
        self.assertFalse(self.guild.me.guild_permissions.connect)
        self.assertEqual(missing_setup_permissions(self.guild, self.actions, changes), [])
        await apply_role_changes(changes)

    async def check_arrival_setup(self, fail_child=False):
        self.give_bot_threads()
        final = overrides(self.guild, self.roles, self.bot_role, 'ARRIVAL')
        parent = Obj(id=100, name='ARRIVAL', overwrites=final)
        events = []

        async def edit_parent(**kwargs):
            parent.overwrites = kwargs['overwrites']
            events.append('temporary' if parent.overwrites[self.bot_role].create_private_threads else 'final')
            return parent

        async def edit_child(**kwargs):
            events.append('child')
            for bit in ('create_public_threads', 'create_private_threads', 'send_messages_in_threads'):
                self.assertTrue(getattr(parent.overwrites[self.bot_role], bit))
                self.assertFalse(getattr(parent.overwrites[self.everyone], bit))
            self.assertEqual(signature(kwargs['overwrites']), signature(final))
            if fail_child:
                raise discord.Forbidden(Obj(status=403, reason='Forbidden'),
                    {'code': 50013, 'message': 'Missing Permissions'})

        parent.edit = AsyncMock(side_effect=edit_parent)
        child = Obj(id=101, name='rules', edit=AsyncMock(side_effect=edit_child))
        self.guild.get_channel = lambda cid: {100: parent, 101: child}.get(cid)
        actions = [dict(kind='category', name='ARRIVAL', id=100, position=0),
                   dict(kind='text', category='ARRIVAL', name='rules', key='ARRIVAL/rules', id=101)]
        with contextlib.redirect_stdout(io.StringIO()):
            if fail_child:
                with self.assertRaisesRegex(RuntimeError, 'updating channel ARRIVAL/rules'):
                    await apply_channels(self.guild, self.roles, self.bot_role, actions)
            else:
                result = await apply_channels(self.guild, self.roles, self.bot_role, actions)
                self.assertEqual(result, {'ARRIVAL/rules': '101'})
        self.assertEqual(events, ['temporary', 'child', 'final'])
        self.assertEqual(signature(parent.overwrites), signature(final))

    async def test_arrival_keeps_approved_bot_threads_until_children_finish(self):
        await self.check_arrival_setup()

    async def test_arrival_removes_temporary_overwrites_after_child_failure(self):
        await self.check_arrival_setup(fail_child=True)

    async def test_forbidden_error_names_role_and_stops_remaining_edits(self):
        error = discord.Forbidden(Obj(status=403, reason='Forbidden'), {'code': 50013, 'message': 'Missing Permissions'})
        first = Obj(id=12, name='Member', edit=AsyncMock(side_effect=error))
        second = Obj(id=13, name='Light Side', edit=AsyncMock())
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as caught:
                await apply_role_changes([(first, discord.Permissions.none()), (second, discord.Permissions.none())])
        self.assertIn('updating role Member (12)', str(caught.exception))
        self.assertIn('HTTP 403, error 50013', str(caught.exception))
        first.edit.assert_awaited_once()
        second.edit.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
