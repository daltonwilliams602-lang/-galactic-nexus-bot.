"""Offline tests for Discord boundary failures, without credentials or network."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
import discord
from nexus.bot import NexusBot, ConfirmView, PROGRESSION_ROLES, role_delta, register_commands
from nexus.blueprint import ROLE_ORDER, STAFF
from nexus.engine import Actor, PolicyError


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_selection_log_is_staff_only_private_and_fetches_full_roster(self):
        register_commands(self.bot)
        command = self.bot.tree.get_command('selection-log', guild=discord.Object(id=100))
        calls = []
        async def fetch_members(*, limit):
            calls.append(limit)
            for uid in range(1, 1003):
                yield Obj(id=uid, name=f'user{uid}', display_name=f'Member {uid}', bot=False)
        interaction = Obj(response=Obj(defer=AsyncMock()), edit_original_response=AsyncMock(),
                          guild=Obj(fetch_members=fetch_members, filesize_limit=10_000_000))
        self.bot.fresh_actor = AsyncMock(return_value=Actor('99'))
        await command.callback(interaction)
        self.assertEqual(calls, [])
        self.assertIn('Staff access required', interaction.edit_original_response.call_args.kwargs['content'])
        self.bot.fresh_actor = AsyncMock(return_value=Actor('1'))
        captured = {}
        async def capture(**kwargs):
            captured.update(kwargs)
            captured['csv'] = kwargs['attachments'][0].fp.read().decode('utf-8-sig')
        interaction.edit_original_response = AsyncMock(side_effect=capture)
        before = self.bot.store.all('member')
        await command.callback(interaction, selection='incomplete')
        self.assertEqual(calls, [None])
        self.assertEqual(self.bot.store.all('member'), before)
        self.assertIn('1002', captured['content'])
        self.assertIn('user1002', captured['csv'])
        self.assertEqual(captured['allowed_mentions'].to_dict(), {'parse': []})
        for call in interaction.response.defer.call_args_list:
            self.assertEqual(call.kwargs, {'ephemeral': True})

    async def test_selection_log_does_not_return_partial_data_after_fetch_failure(self):
        register_commands(self.bot)
        command = self.bot.tree.get_command('selection-log', guild=discord.Object(id=100))
        async def fetch_members(*, limit):
            yield Obj(id=10, name='user', display_name='Member', bot=False)
            raise discord.ClientException('Member fetch failed')
        interaction = Obj(response=Obj(defer=AsyncMock()), edit_original_response=AsyncMock(),
                          guild=Obj(fetch_members=fetch_members))
        self.bot.fresh_actor = AsyncMock(return_value=Actor('1'))
        await command.callback(interaction)
        response = interaction.edit_original_response.call_args.kwargs
        self.assertNotIn('attachments', response)
        self.assertIn('Could not create selection log', response['content'])

    async def test_age_update_preserves_custom_wording_and_other_authors(self):
        from nexus.blueprint import CONTENT, LIVE_CONTENT
        messages = {}
        def channel(name):
            current = LIVE_CONTENT.get(name, CONTENT[name])
            old = current.replace('18+', '17+').replace('at least 18', 'at least 17')
            # Include altered formatting that cannot match the setup template.
            old = old + '\nCustom footer: keep this.'
            if '17+' not in old and 'at least 17' not in old:
                old += '\n17+ community'
            items = [Obj(author=Obj(id=author), content=text, embeds=[], edit=AsyncMock())
                     for author, text in [(7, old), (8, old), (7, current), (7, 'Custom founder guide')]]
            embedded = discord.Embed(title='Community rules', description='You must be at least 17. Be respectful.')
            items.append(Obj(author=Obj(id=7), content='', embeds=[embedded], edit=AsyncMock()))
            messages[name] = items
            async def history(limit):
                for message in items:
                    yield message
            return Obj(history=history)
        await NexusBot.refresh_age_guides(Obj(user=Obj(id=7), channel=channel, config_data={'mode': 'live'}))
        for name, items in messages.items():
            items[0].edit.assert_awaited_once()
            self.assertIn('Custom footer: keep this.', items[0].edit.call_args.kwargs['content'])
            self.assertNotIn('17+', items[0].edit.call_args.kwargs['content'])
            for item in items[1:4]:
                item.edit.assert_not_awaited()
            self.assertEqual(items[4].edit.call_args.kwargs['embeds'][0].description,
                             'You must be at least 18. Be respectful.')

    async def test_guide_refresh_only_edits_exact_bot_templates(self):
        from nexus.blueprint import CONTENT, LEGACY_PROGRESSION_GUIDES, LEGACY_VOICE_GUIDES
        edits=[]
        preserved=[]
        def channel(name):
            messages=[]
            for author_id, content in ((7,(LEGACY_PROGRESSION_GUIDES | LEGACY_VOICE_GUIDES)[name]),
                                       (8,(LEGACY_PROGRESSION_GUIDES | LEGACY_VOICE_GUIDES)[name]),
                                       (7,'Custom founder guide')):
                message=Obj(author=Obj(id=author_id),content=content,edit=AsyncMock())
                messages.append(message)
            edits.append((name,messages[0]))
            preserved.extend(messages[1:])
            async def history(limit):
                for message in messages:
                    yield message
            return Obj(history=history)
        await NexusBot.refresh_progression_guides(Obj(user=Obj(id=7),channel=channel,config_data={"mode":"test"}))
        for name,message in edits:
            message.edit.assert_awaited_once()
            self.assertEqual(message.edit.call_args.kwargs['content'],CONTENT[name])
        for message in preserved:
            message.edit.assert_not_awaited()

    async def test_live_commands_hide_founder_test(self):
        self.bot.config_data['mode'] = 'live'
        register_commands(self.bot)
        self.assertIsNone(self.bot.tree.get_command('founder-test', guild=discord.Object(id=100)))
        self.assertIsNone(self.bot.tree.get_command('voice-check', guild=discord.Object(id=100)))
        self.assertIsNotNone(self.bot.tree.get_command('join', guild=discord.Object(id=100)))

    async def test_ticket_commands_are_private_and_reject_nonstaff(self):
        register_commands(self.bot)
        group = self.bot.tree.get_command('ticket', guild=discord.Object(id=100))
        close = self.bot.tree.get_command('close', guild=discord.Object(id=100))
        self.assertIsNotNone(close.get_command('ticket'))
        report = self.bot.tree.get_command('report', guild=discord.Object(id=100))
        self.assertEqual([p.name for p in report.parameters], ['reason', 'member'])
        self.bot.store.put('report', 'secret', {'member':'10', 'reason':'Private evidence', 'at':1, 'status':'open'})
        for command, args in ((group.get_command('summary'), {}), (group.get_command('view'), {'ticket':'secret'})):
            interaction = Obj(response=Obj(defer=AsyncMock()), edit_original_response=AsyncMock())
            self.bot.fresh_actor = AsyncMock(return_value=Actor('99'))
            await command.callback(interaction, **args)
            interaction.response.defer.assert_awaited_once_with(ephemeral=True)
            self.assertEqual(interaction.edit_original_response.call_args.kwargs['content'], 'Staff access required.')
        self.bot.fresh_actor = AsyncMock(return_value=Actor('20', frozenset({'Moderator'})))
        interaction = Obj(response=Obj(defer=AsyncMock()), edit_original_response=AsyncMock())
        await group.get_command('view').callback(interaction, ticket='secret')
        self.assertIn('Private evidence', str(interaction.edit_original_response.call_args.kwargs['embed'].to_dict()))

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bot = NexusBot(dict(guild_id='100', owner_id='1', founder_ids=['1','2','3','4'], mode='test'),
                            db_path=Path(self.tmp.name)/'test.sqlite3')
        self.bot._role_ids = {name: n+1000 for n, name in enumerate(ROLE_ORDER)}
        self.bot._validated.set()

    async def asyncTearDown(self):
        await self.bot.close()
        self.tmp.cleanup()

    def member(self, uid='1', names=(), guild_id=100):
        m = Obj(id=int(uid), bot=False, roles=[Obj(id=self.bot._role_ids[n], name=n) for n in names],
                timed_out_until=None)
        m.guild = Obj(id=guild_id, fetch_member=AsyncMock(return_value=m))
        m.add_roles = AsyncMock()
        m.remove_roles = AsyncMock()
        return m

    def enrolled(self, uid):
        m = self.bot.engine.member(uid)
        m['accepted'] = True
        self.bot.engine.save_member(m)

    def test_role_delta_preserves_owner_staff_and_custom_roles(self):
        mapping = self.bot._role_ids
        protected = {mapping[n] for n in STAFF + ['Server Owner','Galactic Nexus']} | {999999}
        current = protected | {mapping['Dark Side'], mapping['Dark Council']}
        add, remove = role_delta(current, {'Member','Light Side','Force Sensitive'}, mapping)
        self.assertFalse(remove & protected)
        self.assertEqual(remove, {mapping['Dark Side'], mapping['Dark Council']})
        self.assertEqual(add, {mapping['Member'], mapping['Light Side'], mapping['Force Sensitive']})

    def test_same_named_fake_staff_role_does_not_authorize(self):
        m = self.member('5')
        m.roles = [Obj(id=99999, name='Admin')]
        self.assertFalse(self.bot.engine.staff(self.bot.actor(m)))

    async def test_reconcile_does_not_touch_unknown_members(self):
        m = self.member()
        await self.bot.reconcile_member(m)
        m.guild.fetch_member.assert_not_awaited()

    async def test_test_mode_does_not_touch_nonfounders(self):
        self.enrolled('99')
        m = self.member('99')
        await self.bot.reconcile_member(m)
        m.guild.fetch_member.assert_not_awaited()

    async def test_reconcile_does_not_touch_other_guild(self):
        self.enrolled('1')
        m = self.member(guild_id=200)
        await self.bot.reconcile_member(m)
        m.guild.fetch_member.assert_not_awaited()

    async def test_failed_removal_does_not_add_new_access(self):
        self.enrolled('1')
        m = self.member(names=['Dark Side'])
        m.remove_roles.side_effect = RuntimeError('Simulated failed removal')
        with self.assertRaises(RuntimeError):
            await self.bot.reconcile_member(m)
        m.add_roles.assert_not_awaited()

    async def test_reconcile_uses_fresh_membership_and_preserves_staff(self):
        self.enrolled('1')
        old = self.member()
        fresh = self.member(names=['Admin','Dark Side'])
        old.guild.fetch_member.return_value = fresh
        await self.bot.reconcile_member(old)
        removed = {x.id for x in fresh.remove_roles.call_args.args}
        self.assertEqual(removed, {self.bot._role_ids['Dark Side']})

    async def test_confirmation_refetches_authorization_before_commit(self):
        # Model a previously authorized actor whose privileges changed.
        view = ConfirmView(self.bot, Actor('1'), 'token', {})
        self.bot.store.put('confirmation', 'token', {'action':'override','target':'2','used':False})
        self.bot.fresh_actor = AsyncMock(side_effect=PolicyError('Access revoked'))
        self.bot.engine.confirm = unittest.mock.Mock()
        interaction = Obj(user=Obj(id=1), response=Obj(defer=AsyncMock()), edit_original_response=AsyncMock())
        button = next(x for x in view.children if x.label == 'Confirm')
        await button.callback(interaction)
        self.bot.engine.confirm.assert_not_called()

    async def test_command_registration_survives_setup(self):
        register_commands(self.bot)
        guild = discord.Object(id=100)
        before = {c.name for c in self.bot.tree.get_commands(guild=guild)}
        await self.bot.setup_hook()
        after = {c.name for c in self.bot.tree.get_commands(guild=guild)}
        self.assertEqual(before, after)
        self.assertIn('join', after)
        self.assertIn('promotion-review', after)
        for c in self.bot.tree.get_commands(guild=guild):
            self.assertTrue(c.to_dict(self.bot.tree)['name'])

    def test_supplied_owner_and_founder_roster(self):
        config = json.loads((Path(__file__).parents[1]/'config.example.json').read_text())
        self.assertEqual(config['owner_id'], '258470721829732353')
        self.assertEqual(set(config['founder_ids']), {
            '258470721829732353','1494827444698480742','1132159444688568490','1374863187102535731'})
        self.assertEqual(config['mode'], 'test')
        self.assertFalse(config['owner_approved_launch'])

    def test_voice_is_automatic_for_idle_members_but_excludes_bots_and_timeouts(self):
        import time
        now=time.time()
        guild=Obj(afk_channel=None)
        members=[]
        for uid in ['1','2','3','4']:
            self.enrolled(uid)
            m=self.bot.engine.member(uid); m['path']='jedi'
            self.bot.engine.save_member(m)
            member=self.member(uid)
            member.voice=Obj(self_mute=False,self_deaf=False,mute=False,deaf=False,suppress=False)
            member.is_timed_out=lambda:False
            members.append(member)
        rooms=[Obj(id=10,members=members),Obj(id=11,members=members)]
        guild.voice_channels=rooms
        self.bot.config_data['channel_ids']={'CANTINA & EVENTS/vc:General VC':'10','CANTINA & EVENTS/vc:AFK':'11'}
        self.assertEqual(self.bot.attended_rooms(guild,now),{10:['1','2','3','4'],11:['1','2','3','4']})
        members[0].voice.self_mute=True
        members[1].voice.self_deaf=True
        members[2].bot=True
        self.bot.store.put('voice-check','4',{'until':now-1})
        members[3].is_timed_out=lambda:True
        self.assertEqual(self.bot.attended_rooms(guild,now),{10:['1','2'],11:['1','2']})

    def test_setup_instance_lock_rejects_second_process(self):
        from nexus.launch import instance_lock
        path=Path(self.tmp.name)/'lock'
        with instance_lock(path):
            with self.assertRaises(RuntimeError):
                with instance_lock(path):
                    self.fail('Second lock acquired')

    def test_preview_shows_rank_name_and_member(self):
        from nexus.bot import preview_text
        text=preview_text({'affected_member':'1','current_path':'jedi','current_rank':4,
                           'proposed':{'rank':'Sith Apprentice','total_xp_preserved':151200}})
        self.assertIn('Jedi Master',text)
        self.assertIn('Sith Apprentice',text)
        self.assertIn('<@1>',text)
        self.assertIn('151200',text)


if __name__ == '__main__':
    unittest.main()
