import unittest,sqlite3,json
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from gmgn_review import review,select_queue
from monitor import workload
class SchedulingTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.executescript('CREATE TABLE gmgn_candidates(wallet TEXT PRIMARY KEY,first_seen TEXT,last_checked TEXT,state TEXT,evidence TEXT);CREATE TABLE gmgn_observations(wallet TEXT,token TEXT,observed_at TEXT,payload TEXT);')
  self.addCleanup(self.db.close)
 def add(self,w,state='pending_profile',hits=2,tag=None):
  old=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
  now=datetime.now(timezone.utc).isoformat()
  self.db.execute('INSERT INTO gmgn_candidates VALUES(?,?,?,?,?)',(w,old,old,state,'{}'))
  for i in range(hits):self.db.execute('INSERT INTO gmgn_observations VALUES(?,?,?,?)',(w,str(i),now,json.dumps({'token_address':str(i),'realized_profit':1,'tags':[tag] if tag else []})))
  self.db.commit()
 def run_profile(self,stats):
  class Fake:
   def __init__(self):self.calls=[]
   def get(self,route,**kw):self.calls.append(kw['period']);return stats
  c=Fake()
  with patch('gmgn_report.export'):out=review(self.db,c)
  return c.calls,out,json.loads(self.db.execute('SELECT evidence FROM gmgn_candidates').fetchone()[0])
 def test_fail30_skips7(self):
  self.add('a');calls,out,e=self.run_profile({'realized_profit':-1,'pnl_stat':{'avg_holding_period':120}})
  self.assertEqual(calls,['30d']);self.assertEqual(e['stats_7d'],{});self.assertEqual(e['state'],'observing')
 def test_pass_requests_both(self):
  self.add('a');calls,out,e=self.run_profile({'realized_profit':10,'pnl_stat':{'avg_holding_period':120}})
  self.assertEqual(calls,['30d','7d']);self.assertEqual(e['state'],'history_review')
 def test_tag_skips7(self):
  self.add('a',tag='bundler');calls,out,e=self.run_profile({'realized_profit':10,'pnl_stat':{'avg_holding_period':120}})
  self.assertEqual(calls,['30d']);self.assertEqual(e['state'],'signal_only')
 def test_fairness_and_priority(self):
  self.add('a',hits=1);self.add('b',hits=3);self.add('c',hits=2);self.add('d',tag='bundler');self.add('e',hits=2);self.add('old','observing');self.add('manual','history_review')
  rows=select_queue(self.db,5);names=[r['wallet'] for r in rows]
  self.assertEqual(names[0],'b');self.assertEqual(names[3],'a');self.assertEqual(names[4],'old');self.assertNotIn('manual',names)
 def test_backpressure(self):
  self.assertEqual(workload(7000)['pump_interval'],900)
  self.assertEqual(workload(0)['pump_interval'],60)
if __name__=='__main__':unittest.main()
