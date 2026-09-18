import unittest
import tracker
from discovery import discover,candidates,record_signals

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=tracker.connect(':memory:')
        self.events=[]
    def tearDown(self): self.db.close()
    def event(self,token,side,price,ts,wallet='NEW'):
        e=dict(chain='solana',wallet=wallet,tx_id=str(len(self.events)),event_index=0,token=token,side=side,ts=ts,quantity='10',price_usd=str(price),fee_usd='0')
        self.events.append(e)
        tracker.ingest(self.db,[e]); return e
    def seed_market(self):
        for i,token in enumerate(['A','B']):
            self.event(token,'BUY',1,f'2026-09-0{7+i}T12:00:00Z')
            self.event(token,'SELL',3,f'2026-09-0{7+i}T13:00:00Z')
    def test_unknown_address_found_without_seed_list(self):
        self.seed_market()
        r=discover(self.db,'2026-09-09T00:00:00Z')
        self.assertEqual(r['new_candidates'],1)
        c=candidates(self.db)[0]
        self.assertEqual(c['address'],'NEW')
        self.assertEqual(c['state'],'research_candidate')
        self.assertFalse(c['evidence']['copy_eligible'])
    def test_idempotent_and_no_future_leak(self):
        self.seed_market()
        r=discover(self.db,'2026-09-07T12:01:00Z')
        self.assertEqual(r['new_candidates'],0)
        discover(self.db,'2026-09-09T00:00:00Z')
        r=discover(self.db,'2026-09-09T00:00:00Z')
        self.assertEqual(r['changes'],[])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM candidate_changes').fetchone()[0],1)
    def test_one_hit_is_not_repeatability(self):
        self.event('A','BUY',1,'2026-09-07T12:00:00Z')
        self.event('A','SELL',3,'2026-09-07T13:00:00Z')
        discover(self.db,'2026-09-09T00:00:00Z')
        self.assertEqual(candidates(self.db)[0]['state'],'observing')
    def test_future_signals_only_once(self):
        self.seed_market()
        discover(self.db,'2026-09-09T00:00:00Z')
        self.assertEqual(record_signals(self.db,self.events),0)
        e=self.event('C','BUY',1,'2026-09-09T01:00:00Z')
        self.assertEqual(record_signals(self.db,[e]),1)
        self.assertEqual(record_signals(self.db,[e]),0)
    def test_stale_wallet_demoted(self):
        self.seed_market(); discover(self.db,'2026-09-09T00:00:00Z')
        discover(self.db,'2026-09-20T00:00:00Z')
        c=candidates(self.db)[0]
        self.assertEqual(c['state'],'observing')
        self.assertIn('INACTIVE',c['evidence']['reasons'])
    def test_no_rewind(self):
        self.seed_market(); discover(self.db,'2026-09-09T00:00:00Z')
        with self.assertRaises(ValueError): discover(self.db,'2026-09-08T00:00:00Z')
    def test_early_buyer_only(self):
        self.seed_market()
        self.event('A','BUY',1,'2026-09-07T12:45:00Z','LATE')
        discover(self.db,'2026-09-09T00:00:00Z')
        self.assertNotIn('LATE',[c['address'] for c in candidates(self.db)])

if __name__=='__main__': unittest.main()
