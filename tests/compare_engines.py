"""화질이 나쁜 이미지에서 Tesseract 와 PaddleOCR 을 같은 조건으로 비교한다.

측정 항목
  - 문구 재현율 : 핵심 문구 11개가 (공백 제거 후) 정확히 들어 있는 비율
  - 글자 적중률 : 정답 텍스트의 글자 중 OCR 결과에서 순서대로 찾아진 비율 (difflib 매칭)
  - 점검 결과   : '완벽한 OCR' 로 얻은 정답 점검 결과(검토 필요 항목)와 비교
                  정탐(TP) / 누락(FN: 걸려야 하는데 못 건 것) / 오탐(FP: 안 걸려야 하는데 건 것)
사용:  python3 tests/compare_engines.py
"""
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from adreview.checks import check_file, load_yaml
from adreview.extract import extract_image
from adreview.models import AdPage, TextBlock, squash
from adreview.ocr import PaddleOCREngine, TesseractEngine

RULES = load_yaml(str(ROOT / "config" / "rules.yaml"))
MASTER = load_yaml(str(ROOT / "config" / "product_master.yaml"))

GT_LINES = [
    "든든암보험",
    "대한민국 최고의 암보험! 무조건 100% 보장",
    "타사보다 저렴한 보험료, 지금 바로 가입하세요",
    "암 진단비 최대 7,000만원",
    "소액암 진단비 1,000만원 · 가입연령 20~70세",
    "20년납 20년만기 · 보장개시 후 90일 면책",
    "※ 자세한 보장내용은 약관을 확인하시기 바랍니다.",
    "※ 갱신형 상품으로 갱신 시 보험료가 인상될 수 있습니다.",
]
KEY_PHRASES = ["든든암보험", "최고", "무조건100%", "타사보다저렴", "최대7,000만원", "소액암진단비1,000만원",
               "가입연령20~70세", "20년납20년만기", "90일면책", "약관을확인", "갱신시보험료가인상될수있습니다"]
GT_TEXT = squash("".join(GT_LINES))
NUM_TOKENS = ["7,000만원", "1,000만원", "20~70세", "20년납", "20년만기", "90일", "100%"]   # 광고 속 핵심 숫자 7개
_NUM_RE = re.compile(r"\d[\d,.]*\s*(?:만원|세|년|일|%)")


def review_keys(result):
    """수치 항목은 OCR 표기 차이(20~70세 / 20-70세)로 같은 위반이 다른 키가 되지 않게 룰 ID 만 쓴다."""
    keys = set()
    for f in result.findings:
        if f.status != "review" or f.category == "ocr_quality":
            continue
        keys.add((f.rule_id, "") if f.rule_id.startswith("NUM") else (f.rule_id, squash(f.matched_text)))
    return keys


def ground_truth_keys():
    page = AdPage(file="gt", label="image", blocks=[TextBlock(text=t, source="native") for t in GT_LINES])
    return review_keys(check_file([page], RULES, MASTER, product_id="DEMO-CANCER-01"))


def coverage(ocr_text: str) -> float:
    sm = difflib.SequenceMatcher(None, GT_TEXT, ocr_text, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(GT_TEXT)


def evaluate(engine, path, gt):
    t = time.time()
    pages = extract_image(str(path), engine)
    dt = time.time() - t
    ocr_text = "".join(squash(b.text) for b in pages[0].blocks)
    res = check_file(pages, RULES, MASTER, product_id="DEMO-CANCER-01")
    got = review_keys(res)
    # 숫자: 7개 중 정확히 읽은 개수, 그리고 '신뢰도 85 이상인데 정답에 없는 숫자' (확신하며 틀린 읽기) 개수
    gt_nums = {squash(n) for n in NUM_TOKENS} | {"20년", "70세", "20세"}   # 20~70세 는 정규식이 70세 로 잘라 잡으므로 함께 허용
    confident_wrong, wrong_detail = 0, []
    for b in pages[0].blocks:
        for m in _NUM_RE.findall(squash(b.text)):
            if m not in gt_nums:
                wrong_detail.append((m, round(b.conf)))
                if b.conf >= 85:
                    confident_wrong += 1
    return {
        "num_ok": sum(1 for n in NUM_TOKENS if squash(n) in ocr_text), "num_total": len(NUM_TOKENS),
        "confident_wrong_num": confident_wrong, "wrong_num_detail": wrong_detail,
        "time": round(dt, 1),
        "phrase_recall": sum(1 for k in KEY_PHRASES if k in ocr_text) / len(KEY_PHRASES),
        "char_cov": coverage(ocr_text),
        "TP": len(gt & got), "FN": sorted(gt - got), "FP": sorted(got - gt),
        "ocr_warn": sum(1 for f in res.findings if f.category == "ocr_quality" and f.status == "review"),
        "n_blocks": len(pages[0].blocks),
    }


def main():
    gt = ground_truth_keys()
    print(f"정답 점검 결과(검토 필요): {len(gt)}건\n", sorted(gt))
    images = [ROOT / "samples" / "ad_cancer_bad.png"] + sorted((ROOT / "samples" / "degraded").iterdir())
    want = sys.argv[1:] or ["tesseract", "paddle"]          # 예: python3 tests/compare_engines.py paddle
    engines = {n: (TesseractEngine() if n == "tesseract" else PaddleOCREngine()) for n in want}
    out = ROOT / "output" / "engine_comparison"
    prev = json.loads((out / "results.json").read_text(encoding="utf-8"))["results"] if (out / "results.json").exists() and len(want) < 2 else {}
    results = {k: dict(v) for k, v in prev.items()}
    for img in images:
        results.setdefault(img.name, {})
        for name, eng in engines.items():
            try:
                results[img.name][name] = evaluate(eng, img, gt)
            except Exception as e:  # 한 이미지 실패가 전체를 막지 않게
                results[img.name][name] = {"error": repr(e)}
            r = results[img.name][name]
            if "error" in r:
                print(f"{img.name:28s} {name:9s} ERROR {r['error']}")
            else:
                print(f"{img.name:28s} {name:9s} 문구 {r['phrase_recall']:4.0%} 글자 {r['char_cov']:4.0%} "
                      f"숫자 {r['num_ok']}/{r['num_total']} 확신오독 {r['confident_wrong_num']} "
                      f"TP {r['TP']}/{len(gt)} FN {len(r['FN'])} FP {len(r['FP'])} {r['time']}s")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"ground_truth": sorted(gt), "results": results},
                                                 ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return results, gt


if __name__ == "__main__":
    main()
