import unittest,sqlite3
from history_metrics import fetch_history
from gmgn_api import GMGNError
class HistoryStoreTests(unittest.TestCase):
 def test_accumulation_and_cursor(self):
  db=sqlite3.connect(':memory:');self.addCleanup(db.close)
  class Fake:
   def __init__(self):self.calls=[]
   def get(self,route,**params):
    n=int(params.get('cursor',0));self.calls.append(n)
    return {'activities':[{'tx_hash':str(n),'event_type':'buy','token':{'address':str(n)},'token_amount':'1','timestamp':n,'price_usd':'1','gas_usd':'0','dex_usd':'0'}],'next':str(n+1)}
  c=Fake();a=fetch_history(c,'w',db);b=fetch_history(c,'w',db)
  self.assertEqual(c.calls,[0,1,2,0,3,4]);self.assertEqual(a['activity_records'],3);self.assertEqual(b['activity_records'],5)
  self.assertFalse(b['history_complete'])
 def test_repeated_page(self):
  class Fake:
   def get(self,*a,**k):return {'activities':[{'tx_hash':'x','token':{'address':'x'},'token_amount':1,'event_type':'buy','timestamp':1}], 'next':'a'}
  h=fetch_history(Fake(),'w');self.assertEqual(h['pagination_stop'],'repeated_page')
 def test_page_survives_failure(self):
  db=sqlite3.connect(':memory:');self.addCleanup(db.close)
  class Fake:
   def get(self,*a,**k):
    if k.get('cursor'):raise GMGNError('network')
    return {'activities':[{'tx_hash':'x','token':{'address':'x'},'token_amount':1,'timestamp':1}], 'next':'a'}
  with self.assertRaises(GMGNError):fetch_history(Fake(),'w',db)
  self.assertEqual(db.execute('SELECT COUNT(*) FROM wallet_activity_cache').fetchone()[0],1)
if __name__=='__main__':unittest.main()
