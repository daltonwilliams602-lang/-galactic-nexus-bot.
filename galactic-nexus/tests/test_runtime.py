import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, patch
from nexus.runtime import VoicePresence, drain_outbox
from nexus.storage import Store


class VoiceTests(unittest.TestCase):
    def test_continuous_minute_required(self):
        p=VoicePresence()
        for t in [0,15,30,45]:
            self.assertEqual(p.observe({1:['1','2']},t),set())
        self.assertEqual(p.observe({1:['1','2']},60),{'1','2'})

    def test_alone_duplicate_users_and_different_rooms_do_not_count(self):
        p=VoicePresence()
        for t in range(0,121,15):
            self.assertFalse(p.observe({1:['1','1'],2:['2']},t))

    def test_peer_leaving_resets_continuity(self):
        p=VoicePresence()
        for t in [0,15,30,45]: p.observe({1:['1','2']},t)
        p.observe({1:['1']},50)
        self.assertFalse(p.observe({1:['1','2']},60))
        self.assertFalse(p.observe({1:['1','2']},75))

    def test_room_switch_and_stall_reset_continuity(self):
        p=VoicePresence()
        for t in [0,15,30,45]: p.observe({1:['1','2']},t)
        self.assertFalse(p.observe({2:['1','2']},60))
        self.assertFalse(p.observe({2:['1','2']},120))

    def test_disconnect_cannot_backfill(self):
        p=VoicePresence()
        p.observe({1:['1','2']},0)
        p.reset()
        self.assertFalse(p.observe({1:['1','2']},3600))


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'test.sqlite3')
        self.bot=Obj(store=self.store)

    async def asyncTearDown(self):
        self.store.close(); self.tmp.cleanup()

    async def test_failure_stays_pending_then_retries(self):
        ident=self.store.enqueue('roles',{'member':'1'})
        with patch('nexus.runtime.deliver_one',new=AsyncMock(side_effect=RuntimeError('offline'))):
            await drain_outbox(self.bot)
        row=self.store.db.execute('SELECT * FROM outbox').fetchone()
        self.assertEqual(row['delivered'],0)
        self.assertEqual(row['attempts'],1)
        self.store.put('delivery-retry',ident,0)
        with patch('nexus.runtime.deliver_one',new=AsyncMock()) as send:
            await drain_outbox(self.bot)
            await drain_outbox(self.bot)
            send.assert_awaited_once()
        self.assertEqual(self.store.db.execute('SELECT delivered FROM outbox').fetchone()[0],1)

    async def test_backoff_does_not_block_other_deliveries(self):
        a=self.store.enqueue('roles',{'member':'1'})
        b=self.store.enqueue('roles',{'member':'2'})
        self.store.put('delivery-retry',a,9999999999)
        with patch('nexus.runtime.deliver_one',new=AsyncMock()) as send:
            await drain_outbox(self.bot)
            self.assertEqual(send.call_args.args[1]['id'],b)

    async def test_test_notifications_never_use_public_channel(self):
        from nexus.runtime import deliver_one
        channel=Obj(id=123,send=AsyncMock(return_value=Obj(id=999)))
        self.bot.engine=Obj(c={'mode':'test'})
        self.bot.get_guild=lambda gid:Obj()
        self.bot.guild_id=100
        destinations=[]
        self.bot.channel=lambda name:destinations.append(name) or channel
        self.store.enqueue('welcome',{'member':'1'})
        row=self.store.db.execute('SELECT * FROM outbox').fetchone()
        await deliver_one(self.bot,row)
        self.assertEqual(destinations,['test-results'])
        self.assertFalse(channel.send.call_args.kwargs['allowed_mentions'].everyone)

    async def test_uncertain_send_finds_marker_in_history_without_duplicate(self):
        import hashlib
        from nexus.runtime import deliver_one
        ident=self.store.enqueue('welcome',{'member':'1'})
        marker='nexus:'+hashlib.sha256(ident.encode()).hexdigest()[:24]
        message=Obj(id=999,author=Obj(id=9),embeds=[Obj(footer=Obj(text=marker))])
        async def history(**kwargs):
            yield message
        channel=Obj(id=123,send=AsyncMock(),history=history)
        self.bot.engine=Obj(c={'mode':'test'})
        self.bot.get_guild=lambda gid:Obj()
        self.bot.guild_id=100
        self.bot.user=Obj(id=9)
        self.bot.channel=lambda name:channel
        self.store.put('delivery-attempt',ident,{'after_id':1,'channel':123})
        await deliver_one(self.bot,self.store.db.execute('SELECT * FROM outbox').fetchone())
        channel.send.assert_not_awaited()
        self.assertEqual(self.store.get('delivery-message',ident),'999')


if __name__=='__main__': unittest.main()
