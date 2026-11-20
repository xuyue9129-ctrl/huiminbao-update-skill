"""Synthetic regression tests; never touch real workbooks or WeChat."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode
import zipfile

from lxml import etree as E
from openpyxl import Workbook, load_workbook

import workflow as w


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws["A1"] = "示例产品"
        ws["Q10"] = 100
        ws["BY10"] = '=IFERROR(VLOOKUP("x",A1:B2,2,FALSE),"")'
        ws["CE10"] = "=NA()"
        ws["B2"] = date(2028, 1, 1)
        ws["B2"].number_format = "yyyy-mm-dd"
        wb.create_sheet("2027更新与来源")["I7"] = '=HYPERLINK("#Summary!Q10","查看")'
        wb.save(self.base)
        wb.close()
        self.out, self.log = self.root / "out.xlsx", self.root / "log.json"

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, *edits):
        data, _, sheets = w.package(self.base)
        changes = []
        for addr, op, args in edits:
            _, cells = w.get_cells(data, sheets["Summary"])
            changes.append({"sheet": "Summary", "cell": addr, "expect": w.payload(cells[addr]),
                            "op": op, "reason": "合成测试", "evidence_refs": ["decisions/demo.json#test"], **args})
        p = self.root / "plan.json"
        p.write_text(json.dumps({"base_sha256": w.sha(self.base), "changes": changes}), encoding="utf-8")
        return p

    def test_inspect_and_cell_preconditions(self):
        d = w.inspect_book(self.base, ["Summary!Q10"])
        self.assertEqual(len(d["sheets"]), 2)
        self.assertEqual(d["cells"]["Summary!Q10"]["value"], "100")
        self.assertEqual(d["sheets"][0]["formulas"], 2)

    def test_patch_preserves_other_parts_and_baseline(self):
        before = w.sha(self.base)
        p = self.plan(("Q10", "set", {"value": " 升级版120元 "}),
                      ("BY10", "formula", {"formula": 'IFERROR(1/0,"")', "cache": "", "cache_type": "str"}),
                      ("CE10", "formula", {"formula": "NA()", "cache": "#N/A", "cache_type": "e"}))
        result = w.apply_plan(self.base, p, self.out, self.log)
        self.assertEqual(w.sha(self.base), before)
        self.assertEqual(len(result["changed_parts"]), 1)
        wb = load_workbook(self.out, data_only=True)
        self.assertEqual(wb["Summary"]["Q10"].value, " 升级版120元 ")
        self.assertEqual(wb["Summary"]["CE10"].data_type, "e")
        self.assertEqual(wb["Summary"]["CE10"].value, "#N/A")
        wb.close()
        a, _, _ = w.package(self.base)
        b, _, _ = w.package(self.out)
        self.assertEqual(set(a), set(b))
        self.assertTrue(all(a[n] == b[n] for n in a if n not in result["changed_parts"]))

    def test_no_overwrite(self):
        p = self.plan(("Q10", "set", {"value": 120}))
        self.out.write_bytes(b"user work")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            w.apply_plan(self.base, p, self.out, self.log)
        self.assertEqual(self.out.read_bytes(), b"user work")

    def test_stale_hash_rejected(self):
        p = self.plan(("Q10", "set", {"value": 120}))
        d = w.read_json(p)
        d["base_sha256"] = "0" * 64
        p.write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            w.apply_plan(self.base, p, self.out, self.log)
        self.assertFalse(self.out.exists())

    def test_stale_cell_rejected(self):
        p = self.plan(("Q10", "set", {"value": 120}))
        d = w.read_json(p)
        d["changes"][0]["expect"]["value"] = "999"
        p.write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "precondition"):
            w.apply_plan(self.base, p, self.out, self.log)

    def test_duplicate_patch_rejected(self):
        p = self.plan(("Q10", "set", {"value": 120}), ("Q10", "clear", {}))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            w.apply_plan(self.base, p, self.out, self.log)

    def test_numeric_cverr_rejected(self):
        p = self.plan(("CE10", "formula", {"formula": "NA()", "cache": -2146826246}))
        with self.assertRaisesRegex(ValueError, "CVErr"):
            w.apply_plan(self.base, p, self.out, self.log)

    def test_clear_and_date_preserve_formula_elsewhere(self):
        p = self.plan(("Q10", "clear", {}), ("B2", "set", {"value": {"date": "2029-01-01"}}))
        w.apply_plan(self.base, p, self.out, self.log)
        wb = load_workbook(self.out)
        self.assertIsNone(wb["Summary"]["Q10"].value)
        self.assertEqual(wb["Summary"]["B2"].value.year, 2029)
        self.assertEqual(wb["Summary"]["BY10"].data_type, "f")
        wb.close()

    def evidence(self):
        run = self.root / "run"
        (run / "evidence").mkdir(parents=True)
        (run / "evidence" / "p.txt").write_text("虚构官方产品2028版，120元。", encoding="utf-8")
        d = {"product_id": "demo", "product": "示例", "target_year": 2028,
             "year_basis": {"kind": "named_year", "quote": "2028版", "source_id": "s"},
             "sources": [{"id": "s", "kind": "official_account", "official": True,
                          "official_reason": "合成测试", "title": "说明", "url": "",
                          "accessed_at": "2027-11-01T10:00:00+08:00", "file": "evidence/p.txt"}],
             "decisions": [{"col": "Q", "action": "set", "old": None, "value": 120,
                            "reason": "原文明确", "quote": "120元", "source_id": "s"}]}
        p = run / "decision.json"
        return run, p, d

    def check_evidence(self, run, p, d):
        p.write_text(json.dumps(d), encoding="utf-8")
        return w.validate_evidence(p, run)

    def test_valid_evidence(self):
        run, p, d = self.evidence()
        self.assertTrue(self.check_evidence(run, p, d)["valid"])

    def test_path_traversal_rejected(self):
        run, p, d = self.evidence()
        d["sources"][0]["file"] = "../base.xlsx"
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.check_evidence(run, p, d)

    def test_session_url_rejected(self):
        run, p, d = self.evidence()
        d["sources"][0]["url"] = "https://example.invalid/?" + urlencode({"exportkey": "redacted"})
        with self.assertRaisesRegex(ValueError, "session"):
            self.check_evidence(run, p, d)

    def test_partial_year_rejected(self):
        run, p, d = self.evidence()
        d["year_basis"] = {"kind": "full_calendar_coverage", "quote": "跨年保障", "source_id": "s",
                           "start": "2027-11-01", "end": "2028-10-31"}
        with self.assertRaisesRegex(ValueError, "calendar"):
            self.check_evidence(run, p, d)

    def test_h5_requires_parent(self):
        run, p, d = self.evidence()
        d["sources"][0]["kind"] = "official_h5"
        with self.assertRaisesRegex(ValueError, "parent"):
            self.check_evidence(run, p, d)

    def test_not_found_does_not_imply_withdraw(self):
        run, p, d = self.evidence()
        d["decisions"] = [{"action": "not_found", "col": "BX", "reason": "未查到"}]
        self.assertTrue(self.check_evidence(run, p, d)["valid"])
        d["decisions"][0] = {"action": "withdraw", "col": "BX", "old": "旧值", "reason": "本批没提"}
        with self.assertRaisesRegex(ValueError, "prior evidence"):
            self.check_evidence(run, p, d)

    def test_scan_detects_workbook_and_personal_path(self):
        safe = self.root / "publish"
        safe.mkdir()
        (safe / "README.md").write_text("Generic instructions", encoding="utf-8")
        self.assertTrue(w.scan_package(safe)["passed"])
        (safe / "private.xlsx").write_bytes(b"x")
        self.assertFalse(w.scan_package(safe)["passed"])

    def test_missing_dimension_is_valid(self):
        data, infos, sheets = w.package(self.base)
        root = w.xml(data[sheets["Summary"]])
        root.remove(root.find(w.T("dimension")))
        data[sheets["Summary"]] = E.tostring(root)
        no_dim = self.root / "no-dim.xlsx"
        with zipfile.ZipFile(no_dim, "w") as z:
            for info in infos:
                z.writestr(info, data[info.filename])
        self.assertEqual(w.inspect_book(no_dim)["sheets"][0]["rows"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
