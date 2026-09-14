"""Exercise Discord's actual permission resolution against synthetic members."""
import unittest
from types import SimpleNamespace as Obj
import discord
from nexus.blueprint import ROLE_ORDER, ROLE_PERMISSIONS, CATEGORIES, can_view, RANKS
from nexus.server_config import overrides


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

    def permissions(self,names,category,channel,owner=False):
        mapping=overrides(self.guild,self.roles,self.roles['Galactic Nexus'],category,channel)
        overwrites=[{'id':str(role.id),'type':0,'allow':str(ow.pair()[0].value),'deny':str(ow.pair()[1].value)} for role,ow in mapping.items()]
        c=discord.TextChannel(state=None,guild=self.guild,data={'id':'200','name':channel,'type':0,'position':0,'permission_overwrites':overwrites})
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

    def test_owner_has_inherent_access_without_roles(self):
        self.assertTrue(self.permissions([],'COUNCIL CHAMBERS','dark-council',owner=True).view_channel)

    def test_shared_chat_allows_member_conversation(self):
        p=self.permissions(['Member'],'HOLOCOMMS','general')
        self.assertTrue(p.view_channel and p.send_messages)
        self.assertFalse(p.administrator)


if __name__=='__main__': unittest.main()
