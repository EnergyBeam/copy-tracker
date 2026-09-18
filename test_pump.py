import unittest
from pump_discovery import eligible
class PumpTests(unittest.TestCase):
 def test_fresh_pump(self):
  self.assertTrue(eligible(dict(chain='sol',launchpad_platform='Pump.fun',created_timestamp=990,buys_24h=3),1000))
 def test_wrong_platform_old_future_and_low_activity(self):
  base=dict(chain='sol',launchpad_platform='Pump.fun',created_timestamp=990,buys_24h=3)
  for change in [dict(launchpad_platform='other'),dict(created_timestamp=1),dict(created_timestamp=1001),dict(buys_24h=1),dict(offchain=True)]:
   self.assertFalse(eligible(dict(base,**change),1000))
if __name__=='__main__':unittest.main()
