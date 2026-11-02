"""Public sample database build checks."""

import tempfile
import unittest
from pathlib import Path

from sample_receipt.build_database import build_sample_database
from spending.database import connect


class SampleReceiptTests(unittest.TestCase):
    def test_public_sample_database_runs_ocr_and_leaves_human_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            database = build_sample_database(Path(directory) / 'sample.db')
            with connect(database) as db:
                self.assertEqual(
                    [tuple(row) for row in db.execute('SELECT status, count(*) FROM Receipt GROUP BY status')],
                    [('needs_review', 3)],
                )
                self.assertEqual(db.execute('SELECT count(*) FROM ocr_runs WHERE status="succeeded"').fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT count(*) FROM v_monthly_spending').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
