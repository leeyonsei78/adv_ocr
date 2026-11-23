"""표준 라이브러리만으로 xlsx 를 읽어 시트별 행을 출력한다 (openpyxl 미설치 환경용)."""
import sys, zipfile, re
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def col_to_idx(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    letters = m.group(1)
    n = 0
    for c in letters:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def load(path):
    z = zipfile.ZipFile(path)
    # shared strings
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    # workbook sheet names + rId
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {r.get("Id"): r.get("Target") for r in rels}
    sheets = []
    for s in wb.find(f"{NS}sheets"):
        name = s.get("name")
        rid = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rid_to_target[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        target = target.replace("xl/xl/", "xl/")
        sheets.append((name, target))
    result = {}
    for name, target in sheets:
        root = ET.fromstring(z.read(target))
        rows = []
        for row in root.iter(f"{NS}row"):
            cells = {}
            maxc = 0
            for c in row.findall(f"{NS}c"):
                ref = c.get("r")
                ci = col_to_idx(ref)
                maxc = max(maxc, ci)
                t = c.get("t")
                v = c.find(f"{NS}v")
                isel = c.find(f"{NS}is")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif isel is not None:
                    val = "".join(x.text or "" for x in isel.iter(f"{NS}t"))
                elif v is not None:
                    val = v.text
                else:
                    val = ""
                cells[ci] = val
            rows.append([cells.get(i, "") for i in range(maxc + 1)])
        result[name] = rows
    return result


if __name__ == "__main__":
    path = sys.argv[1]
    only = sys.argv[2] if len(sys.argv) > 2 else None
    data = load(path)
    for name, rows in data.items():
        if only and name != only:
            continue
        print(f"\n===== SHEET: {name} ({len(rows)} rows) =====")
        for i, r in enumerate(rows):
            print(i, "|".join(str(x) for x in r))
