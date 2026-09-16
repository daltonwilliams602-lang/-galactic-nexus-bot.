"""Launch preserves records and recovers interrupted config publication."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.activation import activate, validate_live, LAUNCH_CONFIRMATION
from nexus.engine import Actor, Engine, PolicyError
from nexus.hosted import prepare_state
from nexus.storage import Store


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path, self.config = prepare_state(self.root)
        self.config.update(role_ids={'Member': '1'}, channel_ids={'FOUNDER TESTING/test-results': '2'})
        self.source = self.root/'data'/'test.sqlite3'
        self.live = self.root/'data'/'live.sqlite3'
        store = Store(self.source)
        engine = Engine(store, self.config)
        member = engine.member(self.config['owner_id'])
        member.update(accepted=True, xp=151200, rank=3, path='sith')
        member['paths'] = {'sith': {'xp':151200, 'earned_rank':3, 'transferred_rank':0}}
        store.put('member', member['id'], member)
        store.put('proposal','pending',{'status':'pending','approvals':['other-founder'],'required':2})
        store.put('campaign','closed',{'status':'closed','sith':10})
        store.put('report','private',{'text':'private founder report'})
        store.put('confirmation','stale',{'used':False})
        store.put('voice-check',member['id'],{'until':99999999999})
        store.seen('already-awarded')
        key=store.enqueue('report',{'report':'private'})
        store.db.execute('UPDATE outbox SET delivered=1 WHERE id=?',(key,))
        store.log('owner','existing','target',None,{},'Historical event')
        self.objects=store.db.execute('SELECT * FROM objects ORDER BY kind,id').fetchall()
        store.close()

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self):
        return activate(self.path,self.config,LAUNCH_CONFIRMATION)

    def test_preserves_all_progress_reviews_history_receipts_and_source(self):
        config=self.launch()
        validate_live(config,self.live)
        source=Store(self.source);live=Store(self.live)
        try:
            self.assertEqual([tuple(x) for x in self.objects], [tuple(x) for x in source.db.execute('SELECT * FROM objects ORDER BY kind,id')])
            for kind in ('member','proposal','campaign','report'):
                self.assertEqual(source.all(kind),live.all(kind))
            self.assertTrue(live.seen('already-awarded'))
            self.assertEqual(live.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],2)
            self.assertEqual(live.db.execute('SELECT COUNT(*) FROM outbox WHERE delivered=0').fetchone()[0],0)
            self.assertTrue(live.get('confirmation','stale')['used'])
            self.assertEqual(live.get('voice-check',config['owner_id'])['until'],0)
            engine=Engine(live,config)
            outsider=Actor('new-member')
            token,_=engine.preview(outsider,'join',outsider.id,{'age_confirmed':True,'rules_accepted':True})
            engine.confirm(outsider,token)
            self.assertTrue(engine.member(outsider.id)['accepted'])
            with self.assertRaisesRegex(PolicyError,'disabled in live'):
                engine.preview(Actor(config['owner_id']),'founder-test',config['owner_id'],{})
            self.assertNotIn('Founder Tester',engine.desired_roles(config['owner_id']))
        finally:
            source.close();live.close()
        _,loaded=prepare_state(self.root)
        self.assertEqual(loaded,config)
        self.assertEqual(activate(self.path,loaded,LAUNCH_CONFIRMATION),config)
        self.assertEqual(len(list((self.root/'backups').glob('*.sqlite3'))),1)

    def test_explicit_activation_required_and_queue_must_be_drained(self):
        with self.assertRaisesRegex(RuntimeError,'NEXUS_LAUNCH_CONFIRMATION'):
            activate(self.path,self.config,'')
        store=Store(self.source)
        store.enqueue('report',{'private':'do not reroute'})
        store.close()
        with self.assertRaisesRegex(RuntimeError,'Drain the test delivery queue'):
            self.launch()
        self.assertFalse(self.live.exists())
        self.assertFalse(list((self.root/'backups').glob('*.sqlite3')))

    def test_resume_after_config_write_failure_preserves_live_edits(self):
        from nexus.launch import write_json
        def fail_config(path,data):
            if path==self.path:
                raise OSError('simulated interruption')
            write_json(path,data)
        with patch('nexus.launch.write_json',side_effect=fail_config):
            with self.assertRaisesRegex(OSError,'interruption'):
                self.launch()
        live=Store(self.live)
        live.put('report','keep',{'text':'never overwrite live'})
        live.close()
        config=self.launch()
        validate_live(config,self.live)
        live=Store(self.live)
        try:self.assertEqual(live.get('report','keep')['text'],'never overwrite live')
        finally:live.close()

    def test_missing_or_unrelated_live_database_cannot_be_selected(self):
        with self.assertRaisesRegex(RuntimeError,'recorded activation'):
            validate_live(self.config|{'mode':'live','owner_approved_launch':True},self.live)
        self.assertFalse(self.live.exists())
        unrelated=Store(self.live);unrelated.close()
        with self.assertRaisesRegex(RuntimeError,'no activation marker'):
            self.launch()
        self.assertEqual(json.loads(self.path.read_text())['mode'],'test')
