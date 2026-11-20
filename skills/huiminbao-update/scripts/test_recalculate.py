"""Opt-in real Excel test. Creates only synthetic temporary files."""
from datetime import date
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from recalculate import recalculate
from workflow import read_json, sha


@unittest.skipUnless(os.name == "nt" and os.environ.get("HMB_TEST_EXCEL") == "1"
                     and importlib.util.find_spec("win32com") is not None,
                     "Requires Windows Excel, pywin32 and HMB_TEST_EXCEL=1")
class ExcelIntegrationTests(unittest.TestCase):
    def test_real_excel_numeric_error_date_and_baseline_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            source = p / "source.xlsx"
            wb = Workbook()
            ws = wb.active
            ws["A1"], ws["A2"] = 2, 3
            ws["B1"] = "=SUM(A1:A2)"
            ws["C1"] = "=NA()"
            ws["D1"] = "=DATE(2028,1,1)"
            ws["D1"].number_format = "yyyy-mm-dd"
            wb.save(source)
            wb.close()
            before = sha(source)
            result = recalculate(source, p / "copy.xlsx", p / "report.json")
            self.assertTrue(result["input_unchanged"])
            self.assertEqual(sha(source), before)
            report = read_json(p / "report.json")
            data = report["sheets"]["Sheet"]
            self.assertEqual(data["formulas"]["B1"]["value"], 5)
            self.assertEqual(data["formulas"]["C1"]["value"], "#N/A")
            self.assertEqual(data["formulas"]["C1"]["type"], "e")
            self.assertTrue(data["formulas"]["D1"]["value"].startswith("2028-01-01"))
            self.assertEqual(data["errors"], {"C1": "#N/A"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
