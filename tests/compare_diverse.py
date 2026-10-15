"""다양한 광고 이미지(samples/diverse)에서 Tesseract / PaddleOCR / 병행(both)을 비교한다.

1단계 OCR 실행(느림): 결과를 output/diverse/ocr_cache.json 에 저장 (이미 있으면 건너뜀 → 이어서 실행 가능)
2단계 채점(빠름)   : 캐시만으로 지표 계산, output/diverse/results.json · report.md 생성

지표
  줄 유사도   : 정답 문구 각각이 OCR 전체 텍스트(공백 제거) 안에서 얼마나 비슷하게 발견되는지 (rapidfuzz partial_ratio, 0~100)
  줄 정확     : 위 유사도 ≥ 99 (완전 일치) 인 정답 문구의 비율     /  줄 양호 : ≥ 90 인 비율
  숫자 정확   : 정답 문구 속 숫자 토큰(5,000만원, 20~65세, 90일, 2026-0777 등)이 그대로 나온 비율
  정탐/누락/오탐 : 정답 텍스트로 점검한 위반 목록(정답)과 OCR 텍스트로 점검한 결과를 비교
                   누락(FN)=걸려야 하는데 못 건 것(가장 위험) / 오탐(FP)=안 걸려야 하는데 건 것
  쓰레기 블록 : 정답 문구 어디에도 해당하지 않는 OCR 블록 수 (가짜 텍스트 지표)
사용:  python3 tests/compare_diverse.py [ocr|score|all]      (기본 all)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from rapidfuzz import fuzz

from adreview.checks import check_file, load_yaml
from adreview.models import AdPage, TextBlock, squash

SRC = ROOT / "samples" / "diverse"
OUT = ROOT / "output" / "diverse"
CACHE = OUT / "ocr_cache.json"
RULES = load_yaml(str(ROOT / "config" / "rules.yaml"))
MASTER = load_yaml(str(ROOT / "config" / "product_master.yaml"))
ENGINES = ["tesseract", "paddle"]            # both = 두 결과의 합집합 (시간은 합산)
_NUM = re.compile(r"\d[\d,.]*(?:[~\-]\d[\d,.]*)?(?:만원|억원|천만원|원|세|년|일|%|호)?")


# ------------------------------------------------------------------ 1단계: OCR
def run_ocr():
    from adreview.ocr import PaddleOCREngine, TesseractEngine
    OUT.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    engines = {"tesseract": TesseractEngine(), "paddle": PaddleOCREngine()}
    todo = [(m, e) for m in manifest for e in ENGINES if e not in cache.get(m["file"], {})]
    print(f"OCR 실행 {len(todo)}건 (캐시 {len(manifest) * len(ENGINES) - len(todo)}건 재사용)", flush=True)
    for i, (m, e) in enumerate(todo, 1):
        t = time.time()
        try:
            blocks = engines[e].recognize(str(SRC / m["file"]))
            rec = {"time": round(time.time() - t, 2), "blocks": [b.to_dict() for b in blocks]}
        except Exception as ex:   # 한 장의 실패가 전체를 막지 않게
            rec = {"time": round(time.time() - t, 2), "blocks": [], "error": repr(ex)}
        cache.setdefault(m["file"], {})[e] = rec
        print(f"[{i}/{len(todo)}] {m['file']:38s} {e:9s} {rec['time']:6.1f}s 블록 {len(rec['blocks'])}"
              + (f" ERROR {rec['error']}" if "error" in rec else ""), flush=True)
        if i % 5 == 0 or i == len(todo):
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ 2단계: 채점
def to_blocks(dicts):
    return [TextBlock(**d) for d in dicts]


def review_keys(blocks, product, source):
    page = AdPage(file="x", label="image", blocks=blocks)
    res = check_file([page], RULES, MASTER, product_id=product)
    keys = set()
    for f in res.findings:
        # 글자 크기(visual)는 제외: 정답 쪽은 순수 텍스트라 크기 정보가 없어 비교할 수 없다(넣으면 전부 오탐으로 잡힘)
        if f.status != "review" or f.category in ("ocr_quality", "visual"):
            continue
        keys.add((f.rule_id, "") if f.rule_id.startswith("NUM") else (f.rule_id, squash(f.matched_text)))
    return keys


def score(m, blocks):
    ocr_text = "".join(squash(b.text) for b in blocks)
    sims = [fuzz.partial_ratio(squash(it), ocr_text) if ocr_text else 0.0 for it in m["items"]]
    toks = [t for it in m["items"] for t in _NUM.findall(squash(it))]
    num_ok = sum(1 for t in toks if t in ocr_text)
    all_items = "".join(squash(it) for it in m["items"])
    junk = sum(1 for b in blocks if len(squash(b.text)) >= 3 and fuzz.partial_ratio(squash(b.text), all_items) < 60)
    gt = review_keys([TextBlock(text=l, source="native") for l in m["check_lines"]], m["product"], "gt")
    got = review_keys(blocks, m["product"], "ocr")
    return {
        "sim": sum(sims) / len(sims) / 100, "exact": sum(s >= 99 for s in sims) / len(sims),
        "good": sum(s >= 90 for s in sims) / len(sims), "num_ok": num_ok, "num_total": len(toks),
        "junk": junk, "n_items": len(sims), "worst": sorted(zip(sims, m["items"]))[:3],
        "TP": len(gt & got), "n_gt": len(gt), "FN": sorted(gt - got), "FP": sorted(got - gt),
    }


def score_all():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for m in manifest:
        c = cache.get(m["file"], {})
        if not all(e in c for e in ENGINES):
            continue
        per = {}
        for e in ENGINES:
            per[e] = score(m, to_blocks(c[e]["blocks"]))
            per[e]["time"] = c[e]["time"]
        both_blocks = to_blocks(c["tesseract"]["blocks"]) + to_blocks(c["paddle"]["blocks"])
        per["both"] = score(m, both_blocks)
        per["both"]["time"] = round(c["tesseract"]["time"] + c["paddle"]["time"], 2)
        results.append({"file": m["file"], "template": m["template"], "tags": m["tags"], "level": m["level"], "per": per})
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return results


def agg(rows, e):
    n = len(rows)
    if not n:
        return None
    p = [r["per"][e] for r in rows]
    return {
        "n": n, "sim": sum(x["sim"] for x in p) / n, "exact": sum(x["exact"] for x in p) / n,
        "good": sum(x["good"] for x in p) / n,
        "num": sum(x["num_ok"] for x in p) / max(1, sum(x["num_total"] for x in p)),
        "TP": sum(x["TP"] for x in p), "n_gt": sum(x["n_gt"] for x in p),
        "FN": sum(len(x["FN"]) for x in p), "FP": sum(len(x["FP"]) for x in p),
        "junk": sum(x["junk"] for x in p) / n,
        "t_med": sorted(x["time"] for x in p)[n // 2], "t_max": max(x["time"] for x in p),
    }


def report(results):
    E = ["tesseract", "paddle", "both"]
    names = {"tesseract": "Tesseract", "paddle": "PaddleOCR", "both": "병행(합집합)"}
    L = ["# Tesseract vs PaddleOCR — 다양한 광고 이미지 비교", "",
         f"광고 15종 × 3단계(원본 clean / 약한 열화 mild / 강한 열화 heavy) = {len(results)}장. "
         "정답 문구·정답 위반 목록은 광고 생성 시 기록한 값입니다(합성 이미지).", "",
         "- **줄 유사도**: 정답 문구가 OCR 텍스트에서 얼마나 비슷하게 발견되는지(평균) / **줄 정확·양호**: 유사도 99↑ / 90↑ 인 문구 비율",
         "- **숫자**: 정답 숫자 토큰을 그대로 읽은 비율 / **정탐·누락·오탐**: 위반 점검 결과를 정답과 비교 (누락=놓친 위반)",
         "- 글자 크기(visual) 점검은 정답 쪽에 크기 정보가 없어 채점에서 제외했습니다.",
         "- **쓰레기**: 정답에 없는 가짜 OCR 블록 평균 개수 / **시간**: 이미지 1장 처리 시간 중앙값(최대) — 병행은 두 엔진 합산", ""]

    def table(title, groups):
        L.extend([f"## {title}", "", "| 구분 | 엔진 | 장수 | 줄 유사도 | 줄 정확 | 줄 양호 | 숫자 | 정탐 | 누락 | 오탐 | 쓰레기 | 시간(s) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for g, rows in groups:
            for e in E:
                a = agg(rows, e)
                if a:
                    L.append(f"| {g} | {names[e]} | {a['n']} | {a['sim']:.0%} | {a['exact']:.0%} | {a['good']:.0%} | {a['num']:.0%} | "
                             f"{a['TP']}/{a['n_gt']} | {a['FN']} | {a['FP']} | {a['junk']:.1f} | {a['t_med']:.1f} ({a['t_max']:.0f}) |")
        L.append("")

    table("1. 화질 단계별", [(lv, [r for r in results if r["level"] == lv]) for lv in ("clean", "mild", "heavy")]
          + [("전체", results)])
    table("2. 광고 유형별 (3단계 합산)", [(t, [r for r in results if r["template"] == t])
                                       for t in sorted({r["template"] for r in results})])
    tags = sorted({t for r in results for t in r["tags"]})
    table("3. 특성(태그)별 (3단계 합산)", [(t, [r for r in results if t in r["tags"]]) for t in tags])

    def wl(rows_by_key, a, b, thr=0.02):
        w = t = l = 0
        for rows in rows_by_key:
            x = sum(r["per"][a]["sim"] for r in rows) / len(rows)
            y = sum(r["per"][b]["sim"] for r in rows) / len(rows)
            if x - y > thr: w += 1
            elif y - x > thr: l += 1
            else: t += 1
        return w, t, l
    tmpl = [[r for r in results if r["template"] == t] for t in sorted({r["template"] for r in results})]
    L.extend(["## 승패 요약 (줄 유사도 기준, 2%p 이내는 무승부)", "",
              f"- 이미지 {len(results)}장 단위: PaddleOCR 우세 {wl([[r] for r in results], 'paddle', 'tesseract')[0]} / 무승부 {wl([[r] for r in results], 'paddle', 'tesseract')[1]} / Tesseract 우세 {wl([[r] for r in results], 'paddle', 'tesseract')[2]}",
              f"- 광고 레이아웃 {len(tmpl)}종 단위: PaddleOCR 우세 {wl(tmpl, 'paddle', 'tesseract')[0]} / 무승부 {wl(tmpl, 'paddle', 'tesseract')[1]} / Tesseract 우세 {wl(tmpl, 'paddle', 'tesseract')[2]}", ""])
    L.extend(["## 4. 엔진별로 가장 못 읽은 문구 (heavy 제외, 유사도 낮은 순)", ""])
    for e in ("tesseract", "paddle"):
        L.append(f"### {names[e]}")
        worst = []
        for r in results:
            if r["level"] == "heavy":
                continue
            for s, it in r["per"][e]["worst"]:
                if s < 90:
                    worst.append((s, r["file"], it))
        for s, f, it in sorted(worst)[:15]:
            L.append(f"- {s:.0f}점 · {f} · “{it}”")
        L.append("")
    L.extend(["## 5. 놓친 위반(누락) 목록", ""])
    for e in E:
        L.append(f"### {names[e]}")
        for r in results:
            fn = r["per"][e]["FN"]
            if fn:
                L.append(f"- {r['file']}: " + ", ".join(k[0] + ("/" + k[1] if k[1] else "") for k in fn))
        L.append("")
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    return "\n".join(L)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("ocr", "all"):
        run_ocr()
    if mode in ("score", "all"):
        print(report(score_all()))
