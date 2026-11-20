"""Offline helpers. No network, credential access, or workbook row insertion."""
import argparse
from datetime import date, datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import posixpath
import re
import subprocess
import sys
import tempfile
from urllib.parse import parse_qsl, urlsplit
import zipfile

from lxml import etree as E
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.utils.datetime import to_excel

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
T = lambda name: "{%s}%s" % (S, name)
SECRET_KEYS = {"exportkey", "pass_ticket", "uin", "wxtoken", "access_token",
               "authkey", "ticket", "poc_token", "token", "key"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        def encode(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise TypeError("Unsupported JSON value type")
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False, default=encode)
        f.write("\n")


def xml(raw):
    require(b"<!DOCTYPE" not in raw.upper(), "DTD is not supported")
    return E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True))


def package(path):
    path = Path(path)
    require(path.suffix.lower() == ".xlsx", "Only .xlsx is supported")
    with zipfile.ZipFile(path) as z:
        require(z.testzip() is None, "ZIP CRC failure")
        names = z.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP entry")
        data = {i.filename: z.read(i) for i in z.infolist()}
        infos = z.infolist()
    for name, raw in data.items():
        if name.endswith((".xml", ".rels")):
            xml(raw)
    wb = xml(data["xl/workbook.xml"])
    rels = xml(data["xl/_rels/workbook.xml.rels"])
    targets = {r.get("Id"): r.get("Target") for r in rels
               if r.get("TargetMode") != "External"}
    sheets = {}
    for s in wb.find(T("sheets")):
        target = targets[s.get("{%s}id" % R)]
        part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        require(part.startswith("xl/") and part in data, "Invalid worksheet target")
        sheets[s.get("name")] = part
    return data, infos, sheets


def payload(c):
    if c is None:
        return None
    value = c.findtext(T("v"))
    if c.get("t") == "inlineStr":
        value = "".join(c.itertext()) if c.find(T("is")) is not None else ""
    return {"type": c.get("t", "n"), "value": value,
            "formula": c.findtext(T("f")), "style": c.get("s", "0")}


def get_cells(data, part):
    root = xml(data[part])
    cells = {c.get("r"): c for row in root.find(T("sheetData")) for c in row
             if c.tag == T("c")}
    return root, cells


def inspect_book(path, selected=()):
    data, _, sheets = package(path)
    wb = load_workbook(path, read_only=False, data_only=False, keep_links=True)
    result = {"path": str(Path(path).resolve()), "sha256": sha(path),
              "sheets": [], "cells": {}, "external_relationships": 0}
    try:
        for name, part in sheets.items():
            _, cells = get_cells(data, part)
            ws = wb[name]
            result["sheets"].append({
                "name": name, "part": part, "rows": ws.max_row,
                "columns": ws.max_column,
                "formulas": sum(c.find(T("f")) is not None for c in cells.values()),
                "cached_errors": {a: c.findtext(T("v")) for a, c in cells.items() if c.get("t") == "e"}})
        for token in selected:
            name, addr = token.rsplit("!", 1)
            require(name in sheets, "Unknown sheet in --cells")
            _, cells = get_cells(data, sheets[name])
            result["cells"][token] = payload(cells.get(addr))
        for name, raw in data.items():
            if name.endswith(".rels"):
                result["external_relationships"] += sum(r.get("TargetMode") == "External" for r in xml(raw))
    finally:
        wb.close()
    return result


def secret_url(url):
    try:
        p = urlsplit(url)
        return bool(p.username or p.password or any(k.lower() in SECRET_KEYS for k, _ in parse_qsl(p.query)))
    except ValueError:
        return True


def validate_evidence(path, run_dir):
    d = read_json(path)
    base = Path(run_dir).resolve()
    require(bool(d.get("product_id")) and bool(d.get("product")), "Missing product identity")
    year = d.get("target_year")
    require(type(year) is int and 2000 <= year <= 2200, "Invalid target_year")
    sources = d.get("sources")
    require(isinstance(sources, list) and bool(sources), "Missing sources")
    allowed = {"official_account", "official_miniprogram", "official_h5",
               "government", "insurer_official", "official_profile"}
    ids = {}
    for src in sources:
        sid = src.get("id")
        require(isinstance(sid, str) and sid and sid not in ids, "Missing/duplicate source id")
        ids[sid] = src
        require(src.get("kind") in allowed, "Unsupported source kind")
        require(src.get("official") is True and bool(src.get("official_reason")), "Official identity not reviewed")
        require(bool(src.get("title")) and bool(src.get("accessed_at")), "Missing source metadata")
        datetime.fromisoformat(src["accessed_at"])
        if src.get("published_at"):
            date.fromisoformat(src["published_at"])
        url = src.get("url", "")
        require(not secret_url(url), "Source URL contains credentials/session parameters")
        require(not url or urlsplit(url).scheme in {"http", "https"}, "Unsupported source URL")
        rel = Path(src.get("file", ""))
        evidence = (base / rel).resolve()
        require(not rel.is_absolute() and evidence.is_relative_to(base), "Evidence path escapes run directory")
        require(evidence.is_file(), "Evidence file missing: " + str(rel))
    for src in sources:
        if src["kind"] == "official_h5":
            parent = ids.get(src.get("parent_source_id"))
            require(parent is not None and parent["id"] != src["id"]
                    and parent["kind"] in {"official_account", "government", "insurer_official"},
                    "Official H5 lacks verified parent article")
            require(bool(src.get("parent_link_quote")), "H5 parent link quote missing")
    basis = d.get("year_basis", {})
    require(basis.get("source_id") in ids and bool(basis.get("quote")), "Year evidence missing")
    kind = basis.get("kind")
    if kind == "named_year":
        require(str(year) in basis["quote"], "Named-year quote does not mention target year")
    elif kind == "full_calendar_coverage":
        start, end = date.fromisoformat(basis["start"]), date.fromisoformat(basis["end"])
        require(start <= date(year, 1, 1) and end >= date(year, 12, 31), "Coverage does not cover the calendar year")
    elif kind == "user_exception":
        require(bool(basis.get("user_authorization_quote")), "User exception lacks authorization")
    else:
        raise ValueError("Unknown year_basis kind")
    decisions = d.get("decisions", [])
    require(bool(decisions), "No decisions")
    cols = set()
    for item in decisions:
        col = item.get("col", "")
        require(bool(re.fullmatch(r"[A-Z]{1,3}", col)), "Invalid column")
        require(col not in cols, "Conflicting duplicate column decisions")
        cols.add(col)
        action = item.get("action")
        require(action in {"set", "confirm", "withdraw", "not_found"}, "Unknown decision action")
        require(bool(item.get("reason")), "Missing reason")
        if action in {"set", "confirm"}:
            require("value" in item and bool(item.get("quote")) and item.get("source_id") in ids,
                    "Value decision lacks source/quote")
        if action in {"set", "withdraw"}:
            require("old" in item, "Modification lacks old value")
        if action == "withdraw":
            require(bool(item.get("prior_evidence_review")), "Withdrawal needs prior evidence review")
    return {"valid": True, "product_id": d["product_id"], "sources": len(ids), "decisions": len(decisions)}


def cell_address(addr):
    m = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", addr or "")
    require(m is not None and column_index_from_string(m[1]) <= 16384
            and int(m[2]) <= 1048576, "Invalid cell address")


def append_value(c, value, wb):
    if isinstance(value, dict) and set(value) == {"date"}:
        value = to_excel(datetime.combine(date.fromisoformat(value["date"]), datetime.min.time()), wb.epoch)
    if value is None:
        return
    if isinstance(value, bool):
        c.set("t", "b")
        E.SubElement(c, T("v")).text = "1" if value else "0"
    elif isinstance(value, (int, float)):
        require(math.isfinite(value), "Non-finite number")
        E.SubElement(c, T("v")).text = str(value)
    else:
        require(isinstance(value, str), "Unsupported cell value")
        c.set("t", "inlineStr")
        txt = E.SubElement(E.SubElement(c, T("is")), T("t"))
        txt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        txt.text = value


def apply_plan(workbook, plan_path, output, log_path):
    source, output, log_path = map(lambda p: Path(p).resolve(), (workbook, output, log_path))
    require(len({source, output, log_path, Path(plan_path).resolve()}) == 4, "Input/output paths overlap")
    require(not output.exists() and not log_path.exists(), "Refusing to overwrite output/log")
    require(output.suffix.lower() == ".xlsx", "Output must be .xlsx")
    plan = read_json(plan_path)
    source_sha = sha(source)
    require(plan.get("base_sha256") == source_sha, "Baseline SHA256 mismatch")
    changes = plan.get("changes")
    require(isinstance(changes, list) and bool(changes), "No changes")
    data, infos, sheets = package(source)
    before = dict(data)
    require(not any("digitalSignature" in n or n.startswith("_xmlsignatures/") for n in data),
            "Digitally signed workbook requires a separate approved workflow")
    trees, all_cells = {}, {}
    for name, part in sheets.items():
        trees[name], all_cells[name] = get_cells(data, part)
    wb = load_workbook(source, read_only=False, data_only=False, keep_links=True)
    style_count = len(xml(data["xl/styles.xml"]).find(T("cellXfs")))
    seen, log = set(), []
    try:
        for item in changes:
            name, addr = item.get("sheet"), item.get("cell")
            require(name in sheets, "Unknown sheet")
            cell_address(addr)
            key = (name, addr)
            require(key not in seen, "Duplicate cell modification")
            seen.add(key)
            c = all_cells[name].get(addr)
            require(c is not None, "Only existing cells are supported")
            require("expect" in item and payload(c) == item["expect"], "Cell precondition mismatch: " + addr)
            require(bool(item.get("reason")) and isinstance(item.get("evidence_refs"), list)
                    and all(isinstance(v, str) and v for v in item["evidence_refs"])
                    and bool(item["evidence_refs"]), "Reason/evidence references required")
            op = item.get("op")
            require(op in {"set", "clear", "formula", "style"}, "Unsupported operation")
            require(c.find(T("f")) is None or not c.find(T("f")).attrib,
                    "Shared/array/data-table formula needs separate migration")
            require(not any(child.tag not in {T("f"), T("v"), T("is")} for child in c),
                    "Unsupported extended cell content")
            old = payload(c)
            if op != "style":
                for child in list(c):
                    c.remove(child)
                c.attrib.pop("t", None)
            if op == "set":
                require("value" in item, "Set needs value")
                append_value(c, item["value"], wb)
            elif op == "formula":
                formula = item.get("formula", "")
                require(isinstance(formula, str) and formula and not formula.startswith("="), "Invalid formula")
                E.SubElement(c, T("f")).text = formula
                if "cache" in item:
                    typ = item.get("cache_type", "n")
                    require(typ in {"n", "str", "b", "e"}, "Invalid cache type")
                    value = item["cache"]
                    if typ == "e":
                        require(value in {"#N/A", "#VALUE!", "#REF!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!", "#SPILL!", "#CALC!"},
                                "Invalid Excel error cache")
                    elif typ == "n":
                        require(type(value) in {int, float} and math.isfinite(value)
                                and not (-2146828288 <= value <= -2146826000), "Invalid numeric cache/CVErr")
                    elif typ == "b":
                        require(value in {0, 1}, "Invalid Boolean cache")
                    else:
                        require(isinstance(value, str), "Invalid string cache")
                    c.set("t", typ)
                    E.SubElement(c, T("v")).text = str(value)
            if "style_id" in item:
                sid = item["style_id"]
                require(type(sid) is int and 0 <= sid < style_count, "Invalid style_id")
                c.set("s", str(sid))
            require(op != "style" or "style_id" in item, "Style operation needs style_id")
            log.append({"sheet": name, "cell": addr, "op": op, "old": old,
                        "new": payload(c), "reason": item["reason"], "evidence_refs": item["evidence_refs"]})
    finally:
        wb.close()
    for name, root in trees.items():
        if any(key[0] == name for key in seen):
            data[sheets[name]] = E.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
    changed_parts = sorted(n for n in data if data[n] != before[n])
    require(set(changed_parts).issubset({sheets[n] for n, _ in seen}), "Unexpected part modification")
    # All cell changes must be covered by the plan, including serialization effects.
    for name in sheets:
        _, a = get_cells(before, sheets[name])
        _, b = get_cells(data, sheets[name])
        for addr in set(a) | set(b):
            require(payload(a.get(addr)) == payload(b.get(addr)) or (name, addr) in seen,
                    "Unplanned cell modification")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(suffix=".xlsx", dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for info in infos:
                z.writestr(info, data[info.filename])
        summary = inspect_book(temp)
        require(sha(source) == source_sha, "Baseline changed during write")
        # Hard-link creates destination only if absent, preserving concurrent user work.
        os.link(temp, output)
    finally:
        Path(temp).unlink(missing_ok=True)
    report = {"base": str(source), "base_sha256": source_sha, "output": str(output),
              "sha256": sha(output), "changed_parts": changed_parts, "changes": log,
              "verified_sheets": [s["name"] for s in summary["sheets"]]}
    write_new_json(log_path, report)
    return report


def package_files(root):
    """Files a publish would include: git-visible files when root is a repository, else every file."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True).stdout
        return [root / p.decode("utf-8") for p in out.split(b"\0") if p]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if ".git" not in p.relative_to(root).parts]


def reviewed_gate_dll(path):
    """The activation-gate DLL is the one binary allowed: it must match GATE_VERSION of its C source."""
    source = path.with_name("focus_gate.c")
    if path.parent.name != "wechat" or not source.is_file():
        return False
    m = re.search(r"#define GATE_VERSION (\d+)", source.read_text(encoding="utf-8"))
    return bool(m) and path.name == "focus_gate_v%s.dll" % m.group(1)


def scan_package(root):
    root = Path(root).resolve()
    findings = []
    blocked = {".xlsx", ".xlsm", ".xls", ".png", ".jpg", ".jpeg", ".dll", ".lib", ".pdb", ".pem", ".key", ".log", ".zip"}
    for path in sorted(package_files(root)):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(root))
        if path.suffix.lower() == ".dll" and reviewed_gate_dll(path):
            continue
        if path.suffix.lower() in blocked:
            findings.append({"file": rel, "issue": "Private data/binary extension"})
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            findings.append({"file": rel, "issue": "Unreviewed binary file"})
            continue
        if re.search(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", text):
            findings.append({"file": rel, "issue": "Possible access token"})
        if re.search(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!<|示例|YOUR_)[^\\/\s\"']+", text):
            findings.append({"file": rel, "issue": "Personal absolute path"})
        for url in re.findall(r"https?://[^\s<>\"')`]+", text):
            if secret_url(url):
                findings.append({"file": rel, "issue": "Possible credential/session URL"})
    return {"passed": not findings, "findings": findings}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight")
    for cmd in ("inspect", "verify"):
        s = sub.add_parser(cmd)
        s.add_argument("--workbook", required=True)
        s.add_argument("--cells", nargs="*", default=[])
    s = sub.add_parser("init")
    s.add_argument("--workbook", required=True)
    s.add_argument("--run-dir", required=True)
    s.add_argument("--year", type=int, required=True)
    s = sub.add_parser("validate-evidence")
    s.add_argument("--decision", required=True)
    s.add_argument("--run-dir", required=True)
    s = sub.add_parser("apply")
    for name in ("workbook", "plan", "output", "log"):
        s.add_argument("--" + name, required=True)
    s = sub.add_parser("scan-package")
    s.add_argument("--root", required=True)
    a = p.parse_args()
    if a.cmd == "preflight":
        return {"python": sys.version.split()[0], "platform": platform.system(),
                "wechat_requires_windows_and_user_login": True,
                "dependencies": {n: importlib.util.find_spec(n) is not None for n in ("openpyxl", "lxml", "PIL", "win32com")},
                "note": "No GUI, network, login or installation actions performed"}
    if a.cmd in {"inspect", "verify"}:
        return inspect_book(a.workbook, a.cells)
    if a.cmd == "init":
        require(2000 <= a.year <= 2200, "Invalid target year")
        report = inspect_book(a.workbook)
        run = Path(a.run_dir)
        run.mkdir(parents=True, exist_ok=False)
        for child in ("evidence", "decisions", "plans", "reports"):
            (run / child).mkdir()
        record = {"created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "target_year": a.year, "base": report, "state": "research_pending", "products": []}
        write_new_json(run / "run.json", record)
        return {"run_dir": str(run.resolve()), "baseline_sha256": report["sha256"]}
    if a.cmd == "validate-evidence":
        return validate_evidence(a.decision, a.run_dir)
    if a.cmd == "apply":
        return apply_plan(a.workbook, a.plan, a.output, a.log)
    result = scan_package(a.root)
    require(result["passed"], json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
