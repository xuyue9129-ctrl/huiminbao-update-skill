"""Recalculate only a new disposable copy with a dedicated Excel COM instance."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

from openpyxl import load_workbook
from workflow import package, require, sha, write_new_json


def recalculate(source, copy_path, report_path):
    source, copy_path, report_path = (Path(p).resolve() for p in (source, copy_path, report_path))
    require(len({source, copy_path, report_path}) == 3, "Input/output paths overlap")
    require(not copy_path.exists() and not report_path.exists(), "Copy/report already exists")
    require(copy_path.suffix.lower() == ".xlsx", "Copy must be .xlsx")
    data, _, _ = package(source)
    require("xl/connections.xml" not in data
            and not any(n.startswith("xl/queryTables/") for n in data),
            "Workbook data connections require an explicit reviewed offline workflow")
    # CalculateFullRebuild can invoke data-returning functions even without
    # refreshing workbook links. Refuse these rather than claim offline safety.
    check = load_workbook(source, read_only=False, data_only=False, keep_links=True)
    try:
        for ws in check:
            for row in ws:
                for c in row:
                    if c.data_type == "f":
                        require(not re.search(r"(?i)(?:WEBSERVICE|RTD|SQL\.REQUEST|CUBE\w*|IMAGE)\s*\(|\|[^!]*!", str(c.value)),
                                "External-data formula requires reviewed offline handling")
    finally:
        check.close()
    source_sha = sha(source)
    require(sys.platform == "win32", "Excel COM requires Windows")
    import win32com.client
    excel, book = None, None
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting a file created concurrently.
    with source.open("rb") as src, copy_path.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 3
        excel.AskToUpdateLinks = False
        book = excel.Workbooks.Open(str(copy_path), UpdateLinks=0, ReadOnly=False,
                                    IgnoreReadOnlyRecommended=True, AddToMru=False)
        excel.CalculateFullRebuild()
        book.Save()
        book.Close(False)
        book = None
    finally:
        if book is not None:
            book.Close(False)
        if excel is not None:
            excel.Quit()
    require(sha(source) == source_sha, "Original workbook changed during recalculation")
    formulas = load_workbook(copy_path, read_only=False, data_only=False, keep_links=True)
    values = load_workbook(copy_path, read_only=False, data_only=True, keep_links=True)
    report = {"input": str(source), "input_sha256": source_sha,
              "recalculated_copy": str(copy_path), "copy_sha256": sha(copy_path),
              "sheets": {}, "note": "Caches read from saved file, not COM CVErr integers"}
    try:
        for ws in formulas:
            vs = values[ws.title]
            report["sheets"][ws.title] = {
                "formulas": {c.coordinate: {"formula": c.value, "value": vs[c.coordinate].value,
                                            "type": vs[c.coordinate].data_type}
                             for row in ws for c in row if c.data_type == "f"},
                "errors": {c.coordinate: c.value for row in vs for c in row if c.data_type == "e"}}
    finally:
        formulas.close()
        values.close()
    write_new_json(report_path, report)
    return {"report": str(report_path), "input_unchanged": True,
            "errors": sum(len(s["errors"]) for s in report["sheets"].values())}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--copy", required=True)
    p.add_argument("--report", required=True)
    a = p.parse_args()
    try:
        print(json.dumps(recalculate(a.input, a.copy, a.report), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
