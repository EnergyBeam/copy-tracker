import tempfile,unittest,sqlite3
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from gmgn_api import Pacer

class PacerTests(unittest.TestCase):
    def test_shared_deadline_and_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'rate.sqlite3'
            a=Pacer(path,6);b=Pacer(path,6)
            with patch('gmgn_api.time.time',return_value=100): a.wait()
            with closing(sqlite3.connect(path)) as db: self.assertEqual(db.execute('SELECT next_at FROM pace').fetchone()[0],106)
            b.cooldown(150);a.cooldown(110)
            with closing(sqlite3.connect(path)) as db: self.assertEqual(db.execute('SELECT next_at FROM pace').fetchone()[0],150)
            with patch('gmgn_api.time.time',return_value=151): b.wait()
            with closing(sqlite3.connect(path)) as db: self.assertEqual(db.execute('SELECT next_at FROM pace').fetchone()[0],157)

if __name__=='__main__':unittest.main()
