"""광고심의점검표 자동 판정 단위 테스트.  실행: python3 -m pytest -q tests  또는  python3 tests/test_checklist.py"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adreview.checks import check_file, load_yaml
from adreview.models import AdPage, TextBlock

ROOT = Path(__file__).resolve().parent.parent
RULES = load_yaml(str(ROOT / "config" / "rules.yaml"))
MASTER = load_yaml(str(ROOT / "config" / "product_master.yaml"))
CL = load_yaml(str(ROOT / "config" / "checklist.yaml"))
TODAY = dt.date(2026, 10, 16)

# 점검표 필수안내사항을 거의 다 갖춘 (가상) 광고 문구
GOOD = [
    "든든암보험", "암 진단비 5,000만원 지급 / 소액암 진단비 1,000만원", "가입연령 20~65세 · 20년납 20년만기",
    "(주)예시생명보험  보험가입 전에 본 상품설명서 및 약관을 확인하시기 바랍니다.",
    "보험계약자가 기존 보험계약을 해지하고 새로운 보험계약을 체결할 경우 인수거절, 보험료 인상, 보장내용 축소 등 불이익이 생길 수 있습니다.",
    "※ 갱신형 상품으로 갱신 시 보험료가 인상될 수 있습니다. 가입 후 90일 이내 면책, 1년 이내 진단 시 50% 감액 지급",
    "예시생명보험 및 모집종사자는 해당 상품에 대해 충분히 설명할 의무가 있으며, 가입자는 가입에 앞서 이에 대한 충분한 설명을 받으시기 바랍니다.",
    "이 보험계약은 예금자보호법에 따라 예금보험공사가 보호하되, 보호한도는 1인당 최고 5천만원이며, 5천만원을 초과하는 나머지 금액은 보호하지 않습니다.",
    "해당 모집종사자는 예시생명보험과 전속계약을 체결한 보험설계사입니다.",
    "보험증권을 받은 날부터 15일 이내에 청약철회 가능, 품질보증해지는 계약 성립일부터 3개월 이내 가능합니다.",
    "보험계약자 및 피보험자는 직업, 질병사항 등 중요한 사항을 반드시 알려야 하며 알리지 않은 경우 계약이 해지되거나 보험금을 지급받지 못할 수도 있습니다.",
    "준법감시인 심의필 제2026-0001호 (2026.09.01. ~ 2027.08.31.)",
]


def run(lines, **kw):
    p = AdPage(file="t.pptx", label="slide 1", blocks=[TextBlock(text=t, source="native") for t in lines])
    r = check_file([p], RULES, MASTER, checklist_cfg=CL, today=kw.pop("today", TODAY), **kw)
    return {c.no: c for c in r.checklist}


def test_all_items_present_and_marks_valid():
    rows = run(GOOD)
    assert len(rows) == 46 and all(c.mark in "○×△-?" for c in rows.values())


def test_good_ad_passes_required_items():
    rows = run(GOOD)
    for no in ("2-1", "2-3", "2-4", "2-5", "2-7", "2-8", "2-9", "2-10", "2-11", "2-15", "2-16", "2-17", "1-3", "3-2"):
        assert rows[no].mark == "○", (no, rows[no].mark, rows[no].detail)
    assert rows["4-3"].mark == "○" and rows["4-9"].mark == "○"


def test_missing_required_items_are_flagged():
    rows = run(["든든암보험", "암 진단비 5,000만원 지급", "가입연령 20~65세"])
    assert rows["2-4"].mark == "×" and rows["2-9"].mark == "×" and rows["2-11"].mark == "×"
    assert rows["2-1"].mark == "×"


def test_prohibited_expressions_map_to_items():
    rows = run(GOOD + ["대한민국 최고! 무조건 보장, 타사보다 저렴, 지금 바로 가입"])
    assert rows["4-3"].mark == "×" and "최고" in rows["4-3"].detail
    assert rows["4-5"].mark == "×" and rows["4-9"].mark == "×" and rows["4-7"].mark == "×"
    assert rows["4-8"].mark == "△"          # 순위 표현의 근거 표기 없음


def test_validity_period():
    ex = [l for l in GOOD if "심의필" not in l] + ["준법감시인 심의필 제2026-0001호 (2025.01.01. ~ 2025.12.31.)"]
    assert run(ex)["2-11"].mark == "×"
    fut = [l for l in GOOD if "심의필" not in l] + ["준법감시인 심의필 제2026-0001호 (2027.01.01. ~ 2027.12.31.)"]
    assert run(fut)["2-11"].mark == "△"
    noperiod = [l for l in GOOD if "심의필" not in l] + ["준법감시인 심의필 제2026-0001호"]
    assert run(noperiod)["2-11"].mark == "△"


def test_conditional_items_not_applicable_vs_applicable():
    rows = run(GOOD)
    assert rows["2-12"].mark == "-" and rows["2-13"].mark == "-" and rows["4-13"].mark == "-"
    rows = run(GOOD + ["2026년 통계청 발표 자료에 따르면 암 환자는 27만명", "제휴 서비스 증정 이벤트"])
    assert rows["2-12"].mark in ("△", "×") and rows["2-13"].mark in ("?", "×") and rows["4-13"].mark == "?"
    ok = GOOD + ["(자료: 「암등록통계」, 중앙암등록본부, 2024.12) 암 환자 27만명 통계"]
    assert run(ok)["2-12"].mark == "○"


def test_savings_items_depend_on_product_type():
    sav = ["차곡차곡저축보험", "공시이율 연 3.0% (변동)", "가입연령 0~70세 · 10년납"]
    rows = run(sav, product_id="DEMO-SAVING-01")
    assert rows["2-6"].mark == "○" and rows["1-1"].mark == "○"
    assert rows["1-3"].mark == "-"            # 갱신형 아님 → REQ-004 적용 제외
    assert rows["2-3"].mark in ("○", "△")


def test_unknown_product_type_gives_manual_mark():
    rows = run(["예시 광고 문구"])
    assert rows["1-1"].mark in ("?", "-")


def test_derived_items():
    rows = run(["든든암보험", "월 보험료 12,300원 해약환급금 예시표", "암 진단비 5,000만원"])
    assert rows["2-14"].mark in ("△", "×") and rows["3-5"].mark in ("△", "×") and rows["3-6"].mark in ("△", "×")
    assert rows["4-11"].mark == "△"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
