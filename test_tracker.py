import unittest
import tracker

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.db=tracker.connect(':memory:')
        self.e=dict(chain='solana',wallet='fixture-wallet',tx_id='tx1',event_index=0,token='fixture-token',side='BUY',ts='2026-09-01T12:00:00Z',quantity='10',price_usd='2',fee_usd='0.1')
    def tearDown(self):
        self.db.close()
    def test_idempotent(self):
        self.assertEqual(tracker.ingest(self.db,[self.e,self.e]),1)
    def test_conflict_rolls_back_batch(self):
        with self.assertRaises(ValueError):
            tracker.ingest(self.db,[self.e,dict(self.e,quantity='11')])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
    def test_invalid_amounts(self):
        for value in ('NaN','Infinity','-1','0'):
            with self.assertRaises(ValueError):
                tracker.normalize(dict(self.e,quantity=value))
    def test_requires_timezone(self):
        with self.assertRaises(ValueError):
            tracker.normalize(dict(self.e,ts='2026-09-01T12:00:00'))
    def test_event_index_preserves_multi_swap(self):
        self.assertEqual(tracker.ingest(self.db,[self.e,dict(self.e,event_index=1)]),2)
    def test_missing_data_not_eligible(self):
        self.assertEqual(tracker.screen({})['state'],'watchlist')
    def test_paper_only(self):
        m=dict(closed_cycles=25,median_hold_seconds=60,price_drift_pct=5,slippage_pct=2,size_pool_pct=1,top1_profit_pct=70,history_verified=True,token_gate_passed=True,independence_verified=True,follower_backtest_passed=True,creator_flag=False,anti_farm_flag=False)
        self.assertEqual(tracker.screen(m)['state'],'paper_candidate')
        self.assertFalse(tracker.screen(m)['auto_copy'])
        for key,value in [('median_hold_seconds',59),('price_drift_pct',-6),('creator_flag',True),('slippage_pct',float('nan'))]:
            self.assertEqual(tracker.screen(dict(m,**{key:value}))['state'],'watchlist')

if __name__=='__main__': unittest.main()
