import unittest,json,sqlite3
from datetime import datetime,timezone
from contextlib import closing
from unittest.mock import patch
from ai_review import prepare,validate
from manual_review import submit,inbox
from telegram_notify import enqueue

class ManualTests(unittest.TestCase):
 def db(self):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.execute('CREATE TABLE gmgn_candidates(wallet TEXT,state TEXT,evidence TEXT)')
  return db
 def test_unreviewed_never_sent(self):
  with closing(self.db()) as db:
   enqueue(db,{'wallet':'a','state':'history_review'})
   self.assertEqual(db.execute('SELECT COUNT(*) FROM telegram_outbox').fetchone()[0],0)
 def test_review_and_stale_protection(self):
  with closing(self.db()) as db:
   e={'wallet':'a','state':'history_review','checked_at':'fixture','snapshot_version':1,'snapshot_started_at':datetime.now(timezone.utc).isoformat()}
   db.execute('INSERT INTO gmgn_candidates VALUES(?,?,?)',('a','history_review',json.dumps(e)));db.commit()
   prepare(db,e);r=inbox(db)[0]
   result={'verdict':'watch','summary':'Нужна история','strengths':[],'risks':['Малая выборка'],'missing_checks':['Задержка']}
   with self.assertRaises(ValueError):submit(db,'a','wrong',result)
   with patch('manual_review.flush',return_value=0):submit(db,'a',r['evidence_hash'],result)
   self.assertEqual(inbox(db),[])
 def test_copy_verdict_not_supported_without_evidence(self):
  with self.assertRaises(ValueError):validate({'verdict':'copy'})

if __name__=='__main__':unittest.main()
