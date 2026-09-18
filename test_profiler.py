import unittest
from decimal import Decimal
import tracker
from profiler import calculate

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.db=tracker.connect(':memory:')
        self.i=0
    def tearDown(self): self.db.close()
    def add(self,side,qty,price,ts='2026-09-10T12:00:00Z',fee='0',token='T'):
        self.i+=1
        tracker.ingest(self.db,[dict(chain='solana',wallet='test',tx_id=str(self.i),event_index=0,token=token,side=side,ts=ts,quantity=str(qty),price_usd=str(price),fee_usd=fee)])
    def result(self): return calculate(self.db,'solana','test','2026-09-11T00:00:00Z')
    def test_partial_fees_and_full_cycle(self):
        self.add('BUY',10,2,'2026-09-01T00:00:00Z','1')
        self.add('SELL',4,3,'2026-09-02T00:00:00Z','0.4')
        r=self.result()
        self.assertEqual(Decimal(r['windows']['30']['known_realized_pnl_usd']),Decimal('3.2'))
        self.assertEqual(r['windows']['30']['closed_cycles'],0)
        self.assertEqual(Decimal(r['open_positions'][0]['remaining_cost_usd']),Decimal('12.6'))
        self.add('SELL',6,4,'2026-09-03T00:00:00Z','0.6')
        r=self.result()
        self.assertEqual(Decimal(r['windows']['30']['known_realized_pnl_usd']),Decimal('14'))
        self.assertEqual(r['windows']['30']['closed_cycles'],1)
        self.assertEqual(r['windows']['30']['median_hold_seconds'],172800)
        self.assertEqual(r['open_positions'],[])
    def test_fifo_multiple_buys(self):
        self.add('BUY',5,2,'2026-09-01T00:00:00Z')
        self.add('BUY',5,4,'2026-09-02T00:00:00Z')
        self.add('SELL',6,5,'2026-09-03T00:00:00Z')
        r=self.result()
        self.assertEqual(Decimal(r['windows']['30']['known_realized_pnl_usd']),16)
        self.assertEqual(Decimal(r['open_positions'][0]['remaining_cost_usd']),16)
    def test_unknown_inventory_no_fabricated_profit(self):
        self.add('SELL',100,100)
        r=self.result()
        self.assertIn('UNKNOWN_INVENTORY',r['data_quality'])
        self.assertEqual(Decimal(r['windows']['30']['known_realized_pnl_usd']),0)
        self.assertEqual(r['windows']['30']['closed_cycles'],0)
    def test_oversell_not_completed_cycle(self):
        self.add('BUY',1,2,'2026-09-01T00:00:00Z')
        self.add('SELL',2,3)
        r=self.result()
        self.assertEqual(r['windows']['30']['closed_cycles'],0)
        self.assertIn('UNKNOWN_INVENTORY',r['data_quality'])
    def test_pre_window_cost_basis_and_future_exclusion(self):
        self.add('BUY',1,5,'2026-01-01T00:00:00Z')
        self.add('SELL',1,8,'2026-09-05T00:00:00Z')
        self.add('BUY',1,100,'2026-10-01T00:00:00Z')
        r=self.result()
        self.assertEqual(r['event_count'],2)
        self.assertEqual(Decimal(r['windows']['7']['known_realized_pnl_usd']),3)
        self.assertEqual(r['open_positions'],[])
    def test_reentry_two_cycles(self):
        self.add('BUY',1,2,'2026-09-01T00:00:00Z')
        self.add('SELL',1,3,'2026-09-02T00:00:00Z')
        self.add('BUY',1,4,'2026-09-03T00:00:00Z')
        self.add('SELL',1,2,'2026-09-04T00:00:00Z')
        w=self.result()['windows']['30']
        self.assertEqual(w['closed_cycles'],2)
        self.assertEqual(w['win_rate_pct'],50)
        self.assertEqual(Decimal(w['expectancy_usd']),Decimal('-.5'))
        self.assertEqual(Decimal(w['profit_factor']),Decimal('.5'))
    def test_same_timestamp_uncertainty(self):
        self.add('BUY',1,1)
        self.add('SELL',1,2)
        self.assertIn('AMBIGUOUS_SAME_TIMESTAMP_ORDER',self.result()['data_quality'])
    def test_missing_wallet(self):
        with self.assertRaises(ValueError): self.result()
    def test_no_loss_not_infinite_profit_factor(self):
        self.add('BUY',1,1,'2026-09-01T00:00:00Z')
        self.add('SELL',1,2)
        self.assertIsNone(self.result()['windows']['30']['profit_factor'])
        self.assertEqual(self.result()['windows']['30']['profit_factor_status'],'no_losses')
    def test_window_boundary(self):
        self.add('BUY',1,1,'2026-01-01T00:00:00Z')
        self.add('SELL',1,2,'2026-09-04T00:00:00Z')
        self.assertEqual(self.result()['windows']['7']['closed_cycles'],1)

if __name__=='__main__': unittest.main()
