import tempfile
import unittest
import sqlite3
from pathlib import Path
from nexus.engine import Engine, Actor, PolicyError
from nexus.storage import Store
from nexus.blueprint import ROLE_ORDER, ROLE_PERMISSIONS, can_view, RANKS


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1800000000.0
        self.s = Store(Path(self.tmp.name) / 'live.sqlite3')
        self.cfg = dict(guild_id='fixture', owner_id='1', founder_ids=['1','2','3','4'], mode='live', owner_approved_launch=True)
        self.e = Engine(self.s, self.cfg, clock=lambda:self.now)
        self.owner = self.actor('1')
        self.mod = self.actor('20', 'Moderator')
        self.mod2 = self.actor('21', 'Moderator')
        self.user = self.actor('10')

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def actor(self, uid, *roles):
        return Actor(uid, frozenset(roles), frozenset({'1','2','3','4','20','21'}))

    def do(self, actor, action, target=None, **args):
        args.setdefault('reason', 'Documented test decision')
        token, _ = self.e.preview(actor, action, target or actor.id, args)
        return self.e.confirm(actor, token)

    def join(self, actor=None, path='jedi'):
        actor = actor or self.user
        self.do(actor, 'join', age_confirmed=True, rules_accepted=True)
        self.do(actor, 'path', path=path)
        return actor

    def set_rank(self, uid, rank, path='jedi', xp=None):
        m = self.e.member(uid)
        m.update(accepted=True, path=path, alignment='light' if path=='jedi' else 'dark', rank=rank)
        m['paths'][path] = {'xp': xp or self.cfg.get('rank_thresholds', [0,500,3000,14400,151200])[rank], 'earned_rank':rank,'transferred_rank':0}
        m['xp'] = m['paths'][path]['xp']
        self.e.save_member(m)

    def pending(self, kind='promotion', uid='10'):
        return next(k for k,v in self.s.all('proposal').items() if v['kind']==kind and v['member']==uid and v['status']=='pending')

    def test_confirmation_does_not_mutate_and_is_actor_bound(self):
        token,_ = self.e.preview(self.user,'join','10',dict(age_confirmed=True,rules_accepted=True))
        self.assertFalse(self.e.member('10')['accepted'])
        with self.assertRaises(PolicyError): self.e.confirm(self.mod,token)
        self.e.confirm(self.user,token)
        with self.assertRaises(PolicyError): self.e.confirm(self.user,token)

    def test_confirmation_expires(self):
        token,_=self.e.preview(self.user,'join','10',dict(age_confirmed=True,rules_accepted=True))
        self.now += 181
        with self.assertRaises(PolicyError): self.e.confirm(self.user,token)

    def test_onboarding_requires_both_affirmations(self):
        with self.assertRaises(PolicyError): self.do(self.user,'join',age_confirmed=False,rules_accepted=True)
        with self.assertRaises(PolicyError): self.do(self.user,'path',path='sith')

    def test_no_self_promotion_or_lore_authority(self):
        self.join()
        for actor in [self.user,self.actor('10','Jedi Master'),self.actor('10','Dark Council')]:
            with self.assertRaises(PolicyError): self.do(actor,'override','10',field='rank',value=3)
        self.set_rank('20',0,xp=500)
        self.e.queue_promotion(self.e.member('20'))
        with self.assertRaises(PolicyError): self.do(self.mod,'promotion-review',self.pending(uid='20'),decision='approve')

    def test_fifty_qualifying_minutes_open_first_review(self):
        self.join()
        for i in range(50):
            if i % 10 == 0:
                self.do(self.user,'voice-check')
            self.now += 60
            self.assertEqual(self.e.award_activity('10','voice',eligible_voice=True),10)
        self.assertEqual(self.e.member('10')['xp'],500)
        self.assertEqual(self.e.member('10')['rank'],0)
        pid=self.pending()
        self.do(self.mod,'promotion-review',pid,decision='approve')
        self.assertEqual(self.e.member('10')['rank'],1)

    def test_text_voice_share_minute_and_reject_spam(self):
        self.join()
        self.do(self.user,'voice-check')
        self.assertEqual(self.e.award_activity('10','text',content='lol',event_id='short'),0)
        content='This is a meaningful sentence about our game tonight'
        self.assertEqual(self.e.award_activity('10','text',content=content,event_id='a'),10)
        self.assertEqual(self.e.award_activity('10','voice',eligible_voice=True),0)
        self.now += 60
        self.assertEqual(self.e.award_activity('10','text',content=content,event_id='b'),0)
        self.assertEqual(self.e.award_activity('10','voice',eligible_voice=False),0)
        self.assertEqual(self.e.award_activity('10','voice',eligible_voice=True),10)
        self.now += 901
        self.assertEqual(self.e.award_activity('10','voice',eligible_voice=True),0)

    def test_high_rank_needs_two_distinct_approvals(self):
        self.set_rank('10',3,xp=151200)
        self.e.queue_promotion(self.e.member('10'))
        pid=self.pending()
        self.do(self.mod,'promotion-review',pid,decision='approve')
        self.assertEqual(self.e.member('10')['rank'],3)
        with self.assertRaises(PolicyError): self.do(self.mod,'promotion-review',pid,decision='approve')
        self.do(self.mod2,'promotion-review',pid,decision='approve')
        self.assertEqual(self.e.member('10')['rank'],4)

    def test_revoked_staff_approval_does_not_count(self):
        self.set_rank('10',3,xp=151200)
        self.e.queue_promotion(self.e.member('10'))
        pid=self.pending()
        self.do(self.mod,'promotion-review',pid,decision='approve')
        next_actor=Actor('21',frozenset({'Moderator'}),frozenset({'21'}))
        self.do(next_actor,'promotion-review',pid,decision='approve')
        self.assertEqual(self.e.member('10')['rank'],3)

    def test_discipline_defers_without_losing_xp(self):
        self.set_rank('10',0,xp=500)
        self.e.queue_promotion(self.e.member('10'))
        pid=self.pending()
        self.do(self.mod,'standing','10',decision='add',days=30)
        with self.assertRaises(PolicyError): self.do(self.mod2,'promotion-review',pid,decision='approve')
        self.do(self.mod2,'promotion-review',pid,decision='defer')
        self.assertEqual(self.e.member('10')['xp'],500)
        self.assertEqual(self.s.get('proposal',pid)['status'],'deferred')

    def test_faction_penalty_cooldown_and_high_rank_history(self):
        self.set_rank('10',4)
        self.do(self.user,'path',path='sith')
        m=self.e.member('10')
        self.assertEqual(m['rank'],2)
        self.assertEqual(m['paths']['jedi']['earned_rank'],4)
        self.assertEqual(m['xp'],151200)
        with self.assertRaises(PolicyError): self.do(self.user,'path',path='jedi')
        self.now += 30*86400
        self.do(self.user,'path',path='jedi')
        self.assertEqual(self.e.member('10')['rank'],3)
        self.assertIsNotNone(self.pending())

    def test_faction_exception_needs_review(self):
        self.join()
        self.do(self.user,'faction-request',path='sith')
        pid=self.pending('faction')
        self.assertEqual(self.e.member('10')['path'],'jedi')
        self.do(self.mod,'faction-review',pid,decision='approve')
        self.assertEqual(self.e.member('10')['path'],'sith')

    def test_xp_correction_rejects_stale_value(self):
        self.join()
        token,_=self.e.preview(self.owner,'override','10',dict(field='xp',value=100,reason='Correct accidental event award'))
        self.e.award_activity('10','text',content='This conversation contains a legitimate new message',event_id='new')
        with self.assertRaises(PolicyError): self.e.confirm(self.owner,token)
        self.assertEqual(self.e.member('10')['xp'],10)

    def test_audit_cannot_be_rewritten_or_deleted(self):
        self.join()
        with self.assertRaises(sqlite3.IntegrityError): self.s.db.execute('DELETE FROM audit')
        with self.assertRaises(sqlite3.IntegrityError): self.s.db.execute("UPDATE audit SET reason='changed'")

    def test_backup_preserves_readable_data(self):
        self.join()
        target=self.s.backup(Path(self.tmp.name)/'backups')
        restored=Store(target)
        self.assertEqual(restored.get('member','10')['path'],'jedi')
        restored.close()

    def test_permission_matrix_for_required_perspectives(self):
        self.assertTrue(can_view([], 'ARRIVAL'))
        self.assertFalse(can_view([], 'HOLOCOMMS'))
        for path,ranks in RANKS.items():
            side='Light Side' if path=='jedi' else 'Dark Side'
            own='JEDI TEMPLE' if path=='jedi' else 'SITH ACADEMY'
            other='SITH ACADEMY' if path=='jedi' else 'JEDI TEMPLE'
            for rank in ranks:
                roles=['Member',side,rank]
                with self.subTest(rank=rank,path=path):
                    self.assertTrue(can_view(roles,'HOLOCOMMS'))
                    self.assertTrue(can_view(roles,own))
                    self.assertFalse(can_view(roles,other))
                    self.assertFalse(can_view(roles,'STAFF'))
                    self.assertFalse(can_view(roles,'COUNCIL CHAMBERS','founding-council'))
        self.assertTrue(can_view(['Jedi High Council'],'COUNCIL CHAMBERS','jedi-high-council'))
        self.assertFalse(can_view(['Jedi High Council'],'COUNCIL CHAMBERS','dark-council'))
        self.assertFalse(can_view(['Dark Council'],'COUNCIL CHAMBERS','jedi-high-council'))
        self.assertTrue(can_view(['Moderator'],'STAFF'))
        self.assertFalse(can_view(['Moderator'],'COUNCIL CHAMBERS','dark-council'))
        self.assertTrue(can_view(['Founding Council','Dark Side'],'COUNCIL CHAMBERS','jedi-high-council'))
        self.assertTrue(can_view([], 'STAFF',owner=True))
        for name,permissions in ROLE_PERMISSIONS.items():
            self.assertNotIn('administrator',permissions,name)
            if name not in {'Galactic Nexus'}: self.assertNotIn('manage_roles',permissions,name)
        self.assertLess(ROLE_ORDER.index('Moderator'),ROLE_ORDER.index('Jedi Master'))

    def nominate_and_vote(self, uid='10', purpose='appoint', path='jedi'):
        self.do(self.mod,'council-nominate',uid,purpose=purpose,path=path)
        pid=self.pending('council',uid)
        for uid in ['1','2','3']:
            self.do(self.actor(uid),'council-vote',pid,vote='yes')
        return pid

    def test_council_votes_never_auto_appoint(self):
        self.set_rank('10',4)
        pid=self.nominate_and_vote()
        self.assertFalse(self.s.all('council'))
        self.do(self.owner,'council-finalize',pid)
        self.assertEqual(self.s.get('council','jedi:10')['status'],'active')
        self.assertIn('Jedi High Council',self.e.desired_roles('10'))

    def test_council_abstention_does_not_shrink_denominator(self):
        self.set_rank('10',4)
        self.do(self.mod,'council-nominate','10',purpose='appoint',path='jedi')
        pid=self.pending('council')
        for uid,vote in [('1','yes'),('2','yes'),('3','abstain'),('4','abstain')]:
            self.do(self.actor(uid),'council-vote',pid,vote=vote)
        with self.assertRaises(PolicyError): self.do(self.owner,'council-finalize',pid)

    def test_council_cap_is_rechecked_at_final_confirmation(self):
        for i in range(11):
            self.s.put('council',f'jedi:{100+i}',{'member':str(100+i),'path':'jedi','status':'active'})
        self.set_rank('10',4)
        pid=self.nominate_and_vote()
        token,_=self.e.preview(self.owner,'council-finalize',pid,dict(reason='Approve nominated candidate'))
        self.s.put('council','jedi:999',{'member':'999','path':'jedi','status':'active'})
        with self.assertRaises(PolicyError): self.e.confirm(self.owner,token)
        self.assertEqual(len([s for s in self.s.all('council').values() if s['status']=='active']),12)

    def test_council_removal_preserves_rank_and_history(self):
        self.set_rank('10',4)
        pid=self.nominate_and_vote()
        self.do(self.owner,'council-finalize',pid)
        pid=self.nominate_and_vote(purpose='remove')
        self.do(self.owner,'council-finalize',pid)
        seat=self.s.get('council','jedi:10')
        self.assertEqual(seat['status'],'removed')
        self.assertEqual(len(seat['history']),2)
        self.assertEqual(self.e.member('10')['rank'],4)

    def test_faction_transfer_revokes_council_access(self):
        self.set_rank('10',4)
        pid=self.nominate_and_vote()
        self.do(self.owner,'council-finalize',pid)
        self.do(self.user,'path',path='sith')
        self.assertNotIn('Jedi High Council',self.e.desired_roles('10'))
        self.assertNotIn('Dark Council',self.e.desired_roles('10'))
        self.assertEqual(self.s.get('council','jedi:10')['status'],'former')

    def test_campaign_events_deduplicate_and_keep_previous_seasons(self):
        self.join()
        self.do(self.owner,'campaign-start',name='First Campaign',days=30)
        first=self.s.get('meta','active_campaign')
        self.do(self.mod,'influence','10',amount=20,event_id='trivia-1')
        with self.assertRaises(PolicyError): self.do(self.mod,'influence','10',amount=20,event_id='trivia-1')
        self.assertNotIn('Rulers of the Galaxy',self.e.desired_roles('10'))
        self.do(self.owner,'campaign-finish')
        self.assertIn('Rulers of the Galaxy',self.e.desired_roles('10'))
        self.do(self.owner,'campaign-start',name='Second Campaign',days=10)
        second=self.s.get('meta','active_campaign')
        self.assertNotEqual(first,second)
        self.assertEqual(self.s.get('campaign',first)['scores']['jedi'],20)
        self.assertEqual(self.s.get('campaign',second)['scores'],{'jedi':0,'sith':0})
        self.assertEqual(len(self.s.all('contribution')),1)

    def test_test_mode_is_separate_and_self_limited(self):
        test_store=Store(Path(self.tmp.name)/'test.sqlite3')
        engine=Engine(test_store,self.cfg|{'mode':'test'},clock=lambda:self.now)
        with self.assertRaises(PolicyError): engine.preview(self.user,'join','10',dict(age_confirmed=True,rules_accepted=True))
        with self.assertRaises(PolicyError): engine.preview(self.owner,'founder-test','2',dict(field='rank',value=4,reason='Try another account'))
        with self.assertRaises(PolicyError): Engine(self.s,self.cfg|{'mode':'test'})
        self.assertFalse(engine.member('10')['accepted'])
        test_store.close()

    def test_failed_override_rolls_back_receipts_audit_and_outbox(self):
        self.join()
        count=self.s.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        with self.assertRaises(PolicyError): self.do(self.owner,'override','10',field='xp',value=-100)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],count)
        self.assertEqual(self.e.member('10')['xp'],0)


if __name__ == '__main__': unittest.main()
