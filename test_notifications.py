import json,unittest,sqlite3
from unittest.mock import patch
from contextlib import closing
from history_metrics import closed_metrics
from telegram_notify import report,enqueue,flush,schema

class NotificationTests(unittest.TestCase):
    def activity(self,side,qty,price,ts,**extra):
        return dict(token={'address':'T'},tx_hash=str(ts),timestamp=ts,event_type=side,token_amount=str(qty),price_usd=str(price),gas_usd='0',dex_usd='0',**extra)
    def test_mean_counts_losses_and_partial_exits(self):
        rows=[self.activity('buy',10,1,1),self.activity('sell',5,2,2),self.activity('sell',5,4,3),self.activity('buy',10,2,4),self.activity('sell',10,1,5)]
        r=closed_metrics(rows)
        self.assertEqual(r['closed_cycles'],2)
        self.assertEqual(float(r['mean_multiple']),1.75)
    def test_unknown_inventory_excluded(self):
        r=closed_metrics([self.activity('sell',1,2,1),self.activity('buy',1,1,2),self.activity('sell',1,3,3)])
        self.assertEqual(r['closed_cycles'],0)
        self.assertEqual(r['excluded_tokens'],1)
    def test_report_unknown_not_zero(self):
        text=report({'wallet':'fixture','stats_30d':{},'stats_7d':{}})
        self.assertIn('нет данных',text)
        self.assertIn('не подтверждённая дата создания',text)
        self.assertLessEqual(len(text),3900)
    def test_outbox_dedup_and_delivery(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row
            db.execute('CREATE TABLE gmgn_candidates(wallet TEXT,state TEXT,evidence TEXT)')
            db.execute("INSERT INTO gmgn_candidates VALUES(?,?,?)",("fixture","history_review",json.dumps({"ai_review":True})));db.commit()
            e={'wallet':'fixture','state':'history_review','ai_review':{'verdict':'watch','summary':'Недостаточно данных','strengths':[],'risks':[],'missing_checks':[]}}
            enqueue(db,e);enqueue(db,e)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM telegram_outbox').fetchone()[0],1)
            with patch('telegram_notify.config',return_value={'TELEGRAM_CHAT_ID':'fixture'}),patch('telegram_notify.telegram',return_value={'message_id':1}) as send:
                self.assertEqual(flush(db),1);self.assertEqual(flush(db),0);send.assert_called_once()
    def test_non_candidate_no_message(self):
        with closing(sqlite3.connect(':memory:')) as db:
            enqueue(db,{'wallet':'bad','state':'signal_only'})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM telegram_outbox').fetchone()[0],0)

if __name__=='__main__':unittest.main()
