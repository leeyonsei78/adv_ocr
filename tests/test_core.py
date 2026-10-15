"""핵심 로직 단위 테스트.  실행:  python3 -m pytest -q tests   (pytest 없으면  python3 tests/test_core.py)"""
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adreview.checks import check_file, extract_numbers, load_yaml
from adreview.models import AdPage, TextBlock
from adreview.reference import (ReferenceIndex, _decode_para_text, parse_hwp_records, split_clauses)

ROOT = Path(__file__).resolve().parent.parent
RULES = load_yaml(str(ROOT / "config" / "rules.yaml"))
MASTER = load_yaml(str(ROOT / "config" / "product_master.yaml"))


def page(*lines, source="native"):
    return AdPage(file="t.pptx", label="slide 1", blocks=[TextBlock(text=t, source=source) for t in lines])


# ---------------- 수치 추출 ----------------
def test_money_parsing():
    vals = {n.raw: n.values[0] for n in extract_numbers("5천만원1억5,000만원3,000만원500원")}
    assert vals["5천만원"] == 5000
    assert vals["1억5,000만원"] == 15000
    assert vals["3,000만원"] == 3000
    assert vals["500원"] == 0.05


def test_money_not_counted_for_people():
    assert extract_numbers("3만명이가입") == []


def test_age_range_and_units():
    n = {x.unit: x for x in extract_numbers("가입연령20~65세20년납90일3.5%")}
    assert n["세"].values == [20.0, 65.0]
    assert n["년"].values == [20.0]
    assert n["일"].values == [90.0]
    assert n["%"].values == [3.5]


def test_dot_as_thousands_separator():
    # OCR 이 1,000 을 1.000 으로 읽은 경우
    v = {n.raw: n.values[0] for n in extract_numbers("소액암진단비1.000만원암진단비7.000만원")}
    assert v["1,000만원"] == 1000 and v["7,000만원"] == 7000   # raw 는 보정된 표기
    assert [n.values[0] for n in extract_numbers("연3.5%이자")] == [3.5]      # 소수점은 그대로


def test_numeric_mismatch_hint_when_other_fact_matches():
    # '소액암' 이 인식되지 않아 진단비만 남은 경우: 1,000만원은 소액암진단비 기준과는 일치 → 중요도 낮추고 안내
    res = check_file([page("진단비 1,000만원")], RULES, MASTER, product_id="DEMO-CANCER-01")
    f = [x for x in res.findings if x.rule_id == "NUM-암진단비"][0]
    assert f.severity == "medium" and "소액암진단비" in f.detail


# ---------------- 금지 표현 ----------------
def test_prohibited_with_ocr_spacing():
    res = check_file([page("대한민국 최 고 의 암 보 험", "무 조 건 100 %")], RULES, {})
    ids = {f.rule_id for f in res.findings if f.status == "review"}
    assert "BAN-001" in ids and "BAN-002" in ids


def test_prohibited_exception_for_official_term():
    res = check_file([page("최저보증이율 1.0% 적용")], RULES, {})
    assert not [f for f in res.findings if f.rule_id == "BAN-001"]


# ---------------- 필수 문구 ----------------
def test_required_missing_and_found():
    res = check_file([page("든든암보험", "준법감시인 심의필 제2026-1호")], RULES, {}, product_types=["renewable"])
    status = {f.rule_id: f.status for f in res.findings if f.category == "required"}
    assert status["REQ-001"] == "ok"
    assert status["REQ-004"] == "review"          # 갱신형 안내 없음


def test_required_applies_to_filter():
    res = check_file([page("광고")], RULES, {}, product_types=["renewable"])
    assert any("REQ-002" in s for s in res.skipped_rules)   # 예금자보호는 저축성만


def test_required_fuzzy_ocr_error():
    res = check_file([page("예금자보오법에 따라 보호됩니다")], RULES, {}, product_types=["savings"])
    f = [x for x in res.findings if x.rule_id == "REQ-002"][0]
    assert f.status == "review" and "불확실" in f.title   # 누락이 아니라 '유사 문구' 로 구분


# ---------------- 수치 대조 ----------------
def test_numeric_mismatch_and_match():
    res = check_file([page("소액암 진단비 1,000만원", "암 진단비 최대 7,000만원", "가입연령 20~70세")],
                     RULES, MASTER, product_id="DEMO-CANCER-01")
    num = {f.title: f.status for f in res.findings if f.category == "numeric"}
    assert any("소액암진단비" in t and s == "ok" for t, s in num.items())
    assert any("암진단비 7,000만원" in t and s == "review" for t, s in num.items())
    assert any("가입연령" in t and s == "review" for t, s in num.items())
    # 다음 줄 항목명이 앞 줄 숫자에 붙지 않아야 한다 (회귀 방지)
    assert not any("소액암진단비 7,000만원" in t for t in num)


# ---------------- HWP 레코드 파서 (합성 데이터) ----------------
def _rec(tag, payload: bytes, level=0):
    size = len(payload)
    if size >= 0xFFF:
        return struct.pack("<I", (tag & 0x3FF) | (level << 10) | (0xFFF << 20)) + struct.pack("<I", size) + payload
    return struct.pack("<I", (tag & 0x3FF) | (level << 10) | (size << 20)) + payload


def test_hwp_record_parser():
    ctrl = struct.pack("<H", 2) + b"\x00" * 14           # 확장 제어(구역/단 정의 등): 16바이트 건너뜀
    text = "제1조(목적) 광고 심의".encode("utf-16le") + struct.pack("<H", 13)
    stream = _rec(66, b"\x00" * 8) + _rec(67, ctrl + text) + _rec(67, "제2조(표기) 심의필".encode("utf-16le") + struct.pack("<H", 13))
    assert parse_hwp_records(stream) == ["제1조(목적) 광고 심의", "제2조(표기) 심의필"]
    assert parse_hwp_records(zlib.decompress(zlib.compress(stream)[2:-4], -15)) == parse_hwp_records(stream)


def test_hwp_large_record_header():
    big = ("가" * 3000).encode("utf-16le")
    assert parse_hwp_records(_rec(67, big)) == ["가" * 3000]


# ---------------- 조항 분할/검색 ----------------
def test_split_and_search():
    paras = ["제1장 총칙", "제1조(목적) 광고 심의 기준을 정한다.", "제2조(심의필 표기) 광고물에는 심의필 번호를 표기한다.",
             "제3조(예금자보호) 저축성 보험은 예금자보호 여부를 안내한다."]
    clauses = split_clauses(paras, "x.hwp")
    assert [c["title"] for c in clauses][1].startswith("제2조")
    idx = ReferenceIndex(clauses)
    assert idx.search("예금자보호 안내", k=1, min_score=0.1)[0]["title"].startswith("제3조")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:
                fails += 1
                print("FAIL", name, "->", repr(e))
    sys.exit(1 if fails else 0)
