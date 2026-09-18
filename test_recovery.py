import unittest,socket,ssl
from urllib.error import URLError
from unittest.mock import patch,MagicMock
from gmgn_api import Client,GMGNError,network_reason
from monitor import safe_error,retry_delay
class RecoveryTests(unittest.TestCase):
 def test_sanitized_error(self):
  self.assertEqual(network_reason(URLError(socket.gaierror(11001,'secret'))),'GMGN network dns errno=11001')
  self.assertEqual(network_reason(URLError('secret proxy url')),'GMGN network transport')
  self.assertEqual(safe_error(Exception('secret')),'Exception')
 def test_backoff(self):
  self.assertEqual(retry_delay(GMGNError('GMGN network timeout'),10),120)
  self.assertEqual(retry_delay(GMGNError('GMGN HTTP 401'),10),900)
 def test_opener_refreshed_and_paced(self):
  response=MagicMock();response.__enter__.return_value.read.return_value=b'{"code":0,"data":{}}'
  first=MagicMock();first.open.side_effect=URLError('secret')
  second=MagicMock();second.open.return_value=response
  with patch('gmgn_api.read_key',return_value='secret'),patch('gmgn_api.Pacer') as pace,patch('gmgn_api.build_opener',side_effect=[first,second]),patch('gmgn_api.time.sleep'):
   c=Client();self.assertEqual(c.get('stats'),{})
   self.assertEqual(pace.return_value.wait.call_count,2)
if __name__=='__main__':unittest.main()
