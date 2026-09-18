import unittest
from unittest.mock import patch
from gmgn_scan import unwrap,assess
from gmgn_api import GMGNError,Client

class GMGNTests(unittest.TestCase):
    def test_nested_error(self):
        with self.assertRaises(GMGNError): unwrap({'code':400,'data':{}})
    def test_nested_success(self):
        self.assertEqual(unwrap({'code':0,'data':{'rank':[]}}),{'rank':[]})
    def test_unrealized_not_hit(self):
        stats={'realized_profit':'100','pnl_stat':{'avg_holding_period':3600}}
        r=assess([{'token_address':'a','realized_profit':0,'unrealized_profit':1000}],stats,stats)
        self.assertEqual(r['realized_token_hits'],0)
        self.assertEqual(r['state'],'observing')
    def test_bundler_is_signal_only(self):
        stats={'realized_profit':'100','pnl_stat':{'avg_holding_period':3600}}
        r=assess([{'token_address':'a','realized_profit':100,'maker_token_tags':['bundler']}],stats,stats)
        self.assertEqual(r['state'],'signal_only')
        self.assertFalse(r['copy_eligible'])
    def test_repeatability_never_auto_copy(self):
        stats={'realized_profit':'100','pnl_stat':{'avg_holding_period':3600}}
        r=assess([{'token_address':t,'realized_profit':100} for t in ['a','b']],stats,stats)
        self.assertEqual(r['state'],'history_review')
        self.assertFalse(r['copy_eligible'])
    def test_unknown_stats_not_approved(self):
        self.assertEqual(assess([],{}, {})['state'],'observing')
    def test_trade_route_blocked(self):
        with patch('gmgn_api.read_key',return_value='fixture-key'):
            c=Client()
            with self.assertRaises(ValueError): c.get('swap')

if __name__=='__main__': unittest.main()
