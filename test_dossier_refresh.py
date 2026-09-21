import unittest,sqlite3,json
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from dossier_refresh import refresh,is_fresh
from gmgn_api import GMGNError
from manual_review import submit
class SnapshotTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  self.db.executescript('CREATE TABLE gmgn_candidates(wallet TEXT PRIMARY KEY,evidence TEXT,state TEXT,last_checked TEXT);CREATE TABLE gmgn_observations(wallet TEXT,payload TEXT,observed_at TEXT);')
  self.db.execute("INSERT INTO gmgn_candidates VALUES('w','{}','history_review','old')");self.db.commit()
 def client(self,pnl=1):
  class C:
   def get(self,*args,**kwargs):return {'realized_profit':pnl,'pnl_stat':{'avg_holding_period':100}}
  return C()
 def test_failure_does_not_publish_partial_stats(self):
  with patch('dossier_refresh.fetch_history',side_effect=GMGNError('fail')):
   with self.assertRaises(GMGNError):refresh(self.db,self.client(),'w')
  self.assertEqual(self.db.execute('SELECT evidence FROM gmgn_candidates').fetchone()[0],'{}')
 def test_success_and_withdraw(self):
  with patch('dossier_refresh.fetch_history',return_value={'profitable_token_addresses':['a','b']}):
   e=refresh(self.db,self.client(),'w');self.assertTrue(is_fresh(e))
   self.assertEqual(e['state'],'history_review')
   e=refresh(self.db,self.client(-1),'w');self.assertEqual(e['state'],'observing')
  self.assertEqual(self.db.execute('SELECT state FROM ai_reviews').fetchone()[0],'withdrawn')
 def test_expiration_blocks_submit(self):
  with patch('dossier_refresh.fetch_history',return_value={'profitable_token_addresses':['a','b']}):e=refresh(self.db,self.client(),'w')
  e['snapshot_started_at']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()
  self.assertFalse(is_fresh(e));self.assertFalse(is_fresh({}))
  self.db.execute('UPDATE gmgn_candidates SET evidence=?',(json.dumps(e),));self.db.commit()
  h=self.db.execute('SELECT evidence_hash FROM ai_reviews').fetchone()[0]
  with self.assertRaisesRegex(ValueError,'expired'):
   submit(self.db,'w',h,{'verdict':'watch','summary':'test','strengths':[],'risks':[],'missing_checks':[]})
if __name__=='__main__':unittest.main()
