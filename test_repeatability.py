import unittest,json
from unittest.mock import patch
from test_scheduling import SchedulingTests
from gmgn_review import review
from history_metrics import closed_metrics,fetch_history
from gmgn_scan import assess

def trade(token,side,qty,price,t):
 return dict(token={'address':token},tx_hash=str(t),timestamp=t,event_type=side,token_amount=qty,price_usd=price,gas_usd=0,dex_usd=0)
class RepeatabilityTests(SchedulingTests):
 def test_fallback_admits_unobserved_tokens(self):
  self.add('a',hits=0)
  class Fake:
   def __init__(self):self.calls=[]
   def get(self,route,**kw):
    self.calls.append(route)
    if route=='stats':return {'realized_profit':10,'pnl_stat':{'avg_holding_period':120}}
    return {'activities':[trade(t,s,1,p,i*10+j) for i,t in enumerate(['X','Y']) for j,(s,p) in enumerate([('buy',1),('sell',2)])]}
  c=Fake()
  with patch('gmgn_report.export'):review(self.db,c)
  e=json.loads(self.db.execute('SELECT evidence FROM gmgn_candidates').fetchone()[0])
  self.assertEqual(e['state'],'history_review');self.assertEqual(e['history_token_hits'],2)
  self.assertEqual(c.calls,['stats','stats','activity'])
 def test_net_loss_and_duplicate_tokens_not_hits(self):
  rows=[trade('X','buy',1,1,1),trade('X','sell',1,2,2),trade('X','buy',1,5,3),trade('X','sell',1,1,4)]
  self.assertEqual(closed_metrics(rows)['profitable_token_addresses'],[])
  stats={'realized_profit':1,'pnl_stat':{'avg_holding_period':120}}
  a=assess([{'token_address':'X','realized_profit':1}],stats,stats,['X'])
  self.assertEqual(a['realized_token_hits'],1)
 def test_open_and_unknown_inventory_not_hits(self):
  self.assertEqual(closed_metrics([trade('X','buy',1,1,1),trade('Y','sell',1,5,2)])['profitable_token_addresses'],[])
 def test_empty_history_is_insufficient_not_bad_pnl(self):
  self.add('a',hits=0)
  class Fake:
   def get(self,route,**kw):
    return {'activities':[]} if route=='activity' else {'realized_profit':10,'pnl_stat':{'avg_holding_period':120}}
  with patch('gmgn_report.export'):review(self.db,Fake())
  e=json.loads(self.db.execute('SELECT evidence FROM gmgn_candidates').fetchone()[0])
  self.assertEqual(e['reasons'],['HISTORY_REPEATABILITY_INSUFFICIENT'])
 def test_cursor_bound(self):
  class Fake:
   def __init__(self):self.n=0
   def get(self,*a,**k):self.n+=1;return {'activities':[],'next':'same'}
  c=Fake();h=fetch_history(c,'a');self.assertEqual(c.n,2);self.assertFalse(h['history_complete'])
if __name__=='__main__':unittest.main()
