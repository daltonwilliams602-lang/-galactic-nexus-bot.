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
    async def test_guide_refresh_only_edits_exact_bot_templates(self):
        from nexus.blueprint import CONTENT, LEGACY_PROGRESSION_GUIDES
        edits=[]
        preserved=[]
        def channel(name):
            messages=[]
            for author_id, content in ((7,LEGACY_PROGRESSION_GUIDES[name]),
                                       (8,LEGACY_PROGRESSION_GUIDES[name]),
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
        self.assertIsNotNone(self.bot.tree.get_command('join', guild=discord.Object(id=100)))

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

    def test_voice_filter_excludes_mute_deaf_afk_bots_and_unchecked_members(self):
        import time
        now=time.time()
        guild=Obj(afk_channel=None)
        members=[]
        for uid in ['1','2','3','4']:
            self.enrolled(uid)
            m=self.bot.engine.member(uid); m['path']='jedi'
            self.bot.engine.save_member(m)
            self.bot.store.put('voice-check',uid,{'until':now+900})
            member=self.member(uid)
            member.voice=Obj(self_mute=False,self_deaf=False,mute=False,deaf=False,suppress=False)
            member.is_timed_out=lambda:False
            members.append(member)
        rooms=[Obj(id=10,members=members),Obj(id=11,members=members)]
        guild.voice_channels=rooms
        self.bot.config_data['channel_ids']={'CANTINA & EVENTS/vc:General VC':'10','CANTINA & EVENTS/vc:AFK':'11'}
        self.assertEqual(self.bot.attended_rooms(guild,now),{10:['1','2','3','4']})
        members[0].voice.self_mute=True
        members[1].voice.self_deaf=True
        members[2].bot=True
        self.bot.store.put('voice-check','4',{'until':now-1})
        self.assertEqual(self.bot.attended_rooms(guild,now),{10:[]})

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
