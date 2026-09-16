"""Exercise Discord's actual permission resolution against synthetic members."""
import unittest
from types import SimpleNamespace as Obj
import discord
from nexus.blueprint import ROLE_ORDER, ROLE_PERMISSIONS, CATEGORIES, can_view, RANKS
from nexus.server_config import overrides, check_permissions, role_changes, register_dnd_xp_channels


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.guild=Obj(id=1,owner_id=5000)
        self.roles={}
        default=discord.Role(guild=self.guild,state=None,data={'id':'1','name':'@everyone','permissions':str(discord.Permissions(read_message_history=True,use_application_commands=True).value)})
        self.guild.default_role=default
        self.guild.roles=[default]
        for n,name in enumerate(reversed(ROLE_ORDER),start=2):
            role=discord.Role(guild=self.guild,state=None,data={'id':str(n),'name':name,'position':n,
                'permissions':str(discord.Permissions(**{p:True for p in ROLE_PERMISSIONS[name]}).value)})
            self.roles[name]=role
            self.guild.roles.append(role)
        self.guild.get_role=lambda rid:next((r for r in self.guild.roles if r.id==rid),None)
        self.guild.get_member=lambda uid:None

    def permissions(self,names,category,channel,owner=False,voice=False):
        mapping=overrides(self.guild,self.roles,self.roles['Galactic Nexus'],category,channel)
        overwrites=[{'id':str(role.id),'type':0,'allow':str(ow.pair()[0].value),'deny':str(ow.pair()[1].value)} for role,ow in mapping.items()]
        channel_type = discord.VoiceChannel if voice else discord.TextChannel
        c=channel_type(state=None,guild=self.guild,data={'id':'200','name':channel,'type':2 if voice else 0,'bitrate':64000,'user_limit':0,'position':0,'permission_overwrites':overwrites})
        m=discord.Member(data={'user':{'id':'5000' if owner else '6000','username':'fixture','discriminator':'0','avatar':None},
                              'flags':0,'roles':[str(self.roles[n].id) for n in names]},guild=self.guild,
                         state=Obj(store_user=lambda data:discord.User(state=None,data=data)))
        return c.permissions_for(m)

    def test_required_member_perspectives_match_blueprint(self):
        perspectives=[[],['Member','Force Sensitive'],['Member','Jedi High Council','Light Side'],
                      ['Member','Dark Council','Dark Side'],['Member','Moderator'],['Member','Founding Council']]
        for path,ranks in RANKS.items():
            side='Light Side' if path=='jedi' else 'Dark Side'
            perspectives += [['Member',side,r] for r in ranks[1:]]
        for names in perspectives:
            for category,channels in CATEGORIES.items():
                for channel in channels:
                    if channel.startswith('vc:'): continue
                    with self.subTest(names=names,channel=channel):
                        self.assertEqual(self.permissions(names,category,channel).view_channel,can_view(names,category,channel))

    def test_readonly_blocks_members_and_threads(self):
        p=self.permissions(['Member','Light Side'],'ARRIVAL','rules')
        self.assertTrue(p.view_channel)
        self.assertFalse(p.send_messages)
        self.assertFalse(p.send_messages_in_threads)
        self.assertFalse(p.create_public_threads)

    def test_owner_controlled_invites_keep_private_channels_private(self):
        self.guild.default_role._permissions |= discord.Permissions(create_instant_invite=True).value
        for names in ([], ['Member'], ['Member', 'Dark Side']):
            arrival = self.permissions(names, 'ARRIVAL', 'incoming-transmissions')
            self.assertTrue(arrival.create_instant_invite)
            self.assertFalse(arrival.send_messages)
            self.assertFalse(arrival.administrator)
            for category, channel in (('STAFF', 'reports'), ('FOUNDER TESTING', 'test-results'),
                                      ('JEDI TEMPLE', 'jedi-commons')):
                self.assertFalse(self.permissions(names, category, channel).view_channel)
        self.guild.categories = []
        problems = check_permissions(self.guild, self.roles, self.roles['Galactic Nexus'], {})
        self.assertNotIn('@everyone permissions differ from the blueprint', problems)
        self.assertFalse(role_changes(self.guild, self.roles, set()))
        self.guild.default_role._permissions |= discord.Permissions(manage_roles=True).value
        problems = check_permissions(self.guild, self.roles, self.roles['Galactic Nexus'], {})
        self.assertIn('@everyone permissions differ from the blueprint', problems)
        repaired = role_changes(self.guild, self.roles, set())[0][1]
        self.assertTrue(repaired.create_instant_invite)
        self.assertFalse(repaired.manage_roles)

    def test_soundboard_access_preserves_voice_privacy_and_permission_checks(self):
        self.guild.default_role._permissions |= discord.Permissions(
            use_soundboard=True, use_external_sounds=True).value
        for names in (['Member'], ['Member', 'Light Side'], ['Member', 'Dark Side']):
            voice = self.permissions(names, 'CANTINA & EVENTS', 'General VC', voice=True)
            self.assertTrue(voice.connect and voice.use_soundboard and voice.use_external_sounds)
            self.assertFalse(voice.administrator or voice.manage_roles)
            self.assertFalse(self.permissions(names, 'FOUNDER TESTING', 'Founder Test VC').view_channel)
        self.guild.categories = []
        self.assertNotIn('@everyone permissions differ from the blueprint',
                         check_permissions(self.guild, self.roles, self.roles['Galactic Nexus'], {}))
        self.assertFalse(role_changes(self.guild, self.roles, set()))
        self.guild.default_role._permissions |= discord.Permissions(administrator=True).value
        self.assertIn('@everyone permissions differ from the blueprint',
                      check_permissions(self.guild, self.roles, self.roles['Galactic Nexus'], {}))
        repaired = role_changes(self.guild, self.roles, set())[0][1]
        self.assertTrue(repaired.use_soundboard and repaired.use_external_sounds)
        self.assertFalse(repaired.administrator)

    def test_new_members_can_onboard_before_receiving_member_role(self):
        for roles in ([], ['Member']):
            p = self.permissions(roles, 'ARRIVAL', 'choose-your-path')
            self.assertTrue(p.view_channel and p.send_messages and p.use_application_commands)
            self.assertFalse(p.create_public_threads or p.create_private_threads or p.send_messages_in_threads)
            for name in CATEGORIES['ARRIVAL']:
                if name != 'choose-your-path':
                    self.assertFalse(self.permissions(roles, 'ARRIVAL', name).send_messages)
        self.assertFalse(self.permissions([], 'HOLOCOMMS', 'general').view_channel)

    def test_owner_has_inherent_access_without_roles(self):
        self.assertTrue(self.permissions([],'COUNCIL CHAMBERS','dark-council',owner=True).view_channel)

    def test_shared_chat_allows_member_conversation(self):
        p=self.permissions(['Member'],'HOLOCOMMS','general')
        self.assertTrue(p.view_channel and p.send_messages)
        self.assertFalse(p.administrator)


if __name__=='__main__': unittest.main()


class DndRegistrationTests(unittest.TestCase):
    def test_registration_requires_unique_typed_synced_rooms_and_removes_stale_ids(self):
        from unittest.mock import Mock
        parent = Obj(name='CANTINA & EVENTS', overwrites={}, channels=[])
        text = Mock(spec=discord.TextChannel)
        text.name, text.id, text.overwrites = 'dnd', 101, {}
        voice = Mock(spec=discord.VoiceChannel)
        voice.name, voice.id, voice.overwrites = 'DnD', 102, {}
        parent.channels = [text, voice]
        guild = Obj(categories=[parent])
        ids = {'existing': '100'}
        register_dnd_xp_channels(guild, ids)
        self.assertEqual(ids, {'existing': '100', 'CANTINA & EVENTS/dnd': '101',
                               'CANTINA & EVENTS/vc:DnD': '102'})
        parent.channels = [text, voice, voice]
        register_dnd_xp_channels(guild, ids)
        self.assertNotIn('CANTINA & EVENTS/vc:DnD', ids)
        text.overwrites = {ObjRole(): discord.PermissionOverwrite(view_channel=True)}
        register_dnd_xp_channels(guild, ids)
        self.assertEqual(ids, {'existing': '100'})


class ObjRole:
    id = 1
