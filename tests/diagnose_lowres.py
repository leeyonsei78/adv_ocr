"""저해상도 진단: samples/diverse 의 원본(clean) 15장을 폭 1000~220px 로 줄여(+JPEG q70) 기능 전체가 어디까지 버티는지 본다.

  python3 tests/diagnose_lowres.py [make|ocr|score|all]   (기본 all)

산출: samples/lowres/*.jpg + manifest.json, output/lowres/ocr_cache.json · results.json · report.md
지표는 tests/compare_diverse.py 와 동일(줄 유사도, 숫자, 정탐/누락/오탐). 추가로 해상도별 '못 읽은 문구' 집계.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from PIL import Image
from rapidfuzz import fuzz

import compare_diverse as cd
from adreview.models import squash

SRC = ROOT / "samples" / "diverse"
DST = ROOT / "samples" / "lowres"
OUT = ROOT / "output" / "lowres"
CACHE = OUT / "ocr_cache.json"
WIDTHS = [1000, 700, 500, 400, 300, 220]       # 원본 폭 1400px
ENGINES = ["paddle", "tesseract"]


def make():
    DST.mkdir(parents=True, exist_ok=True)
    man = [m for m in json.loads((SRC / "manifest.json").read_text(encoding="utf-8")) if m["level"] == "clean"]
    out = []
    for m in man:
        im = Image.open(SRC / m["file"]).convert("RGB")
        for w in WIDTHS:
            h = round(im.height * w / im.width)
            name = f"{m['template']}__w{w}.jpg"
            im.resize((w, h), Image.LANCZOS).save(DST / name, quality=70)
            out.append({**m, "file": name, "level": f"w{w}", "size": [w, h]})
    (DST / "manifest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)}장 생성 → {DST}")


def run_ocr():
    from adreview.ocr import PaddleOCREngine, TesseractEngine
    OUT.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    man = json.loads((DST / "manifest.json").read_text(encoding="utf-8"))
    eng = {}
    todo = [(m, e) for e in ENGINES for m in man if e not in cache.get(m["file"], {})]
    print(f"OCR {len(todo)}건", flush=True)
    for i, (m, e) in enumerate(todo, 1):
        if e not in eng:
            eng[e] = PaddleOCREngine() if e == "paddle" else TesseractEngine()
        t = time.time()
        try:
            bl = eng[e].recognize(str(DST / m["file"]))
            rec = {"time": round(time.time() - t, 2), "blocks": [b.to_dict() for b in bl]}
        except Exception as ex:
            rec = {"time": round(time.time() - t, 2), "blocks": [], "error": repr(ex)}
        cache.setdefault(m["file"], {})[e] = rec
        print(f"[{i}/{len(todo)}] {m['file']:34s} {e:9s} {rec['time']:5.1f}s 블록 {len(rec['blocks'])}", flush=True)
        if i % 5 == 0 or i == len(todo):
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def score_all():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    man = json.loads((DST / "manifest.json").read_text(encoding="utf-8"))
    res = []
    for m in man:
        c = cache.get(m["file"], {})
        per = {}
        for e in ENGINES:
            if e in c:
                bl = cd.to_blocks(c[e]["blocks"])
                per[e] = cd.score(m, bl)
                per[e]["time"] = c[e]["time"]
                ocr_text = "".join(squash(b.text) for b in bl)
                per[e]["fails"] = [it for it in m["items"] if not ocr_text or fuzz.partial_ratio(squash(it), ocr_text) < 90]
        res.append({"file": m["file"], "template": m["template"], "level": m["level"], "w": m["size"][0], "per": per})
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return res


def report(res):
    L = ["# 저해상도 진단 — 원본 1400px 광고 15종을 폭별로 축소(JPEG q70)", "",
         f"{len(res)}장. 정답 문구·정답 위반 목록은 합성 시 기록한 값. 글자 크기(visual) 점검은 제외.", ""]
    L += ["## 해상도별 (15장 평균)", "",
          "| 폭(px) | 엔진 | 줄 유사도 | 줄 양호(≥90) | 숫자 | 정탐 | 누락 | 오탐 | 시간 중앙값(s) |", "|---|---|---|---|---|---|---|---|---|"]
    for w in WIDTHS:
        rows = [r for r in res if r["w"] == w]
        for e in ENGINES:
            p = [r["per"][e] for r in rows if e in r["per"]]
            if not p:
                continue
            n = len(p)
            L.append(f"| {w} | {e} | {sum(x['sim'] for x in p)/n:.0%} | {sum(x['good'] for x in p)/n:.0%} | "
                     f"{sum(x['num_ok'] for x in p)/max(1,sum(x['num_total'] for x in p)):.0%} | "
                     f"{sum(x['TP'] for x in p)}/{sum(x['n_gt'] for x in p)} | {sum(len(x['FN']) for x in p)} | "
                     f"{sum(len(x['FP']) for x in p)} | {sorted(x['time'] for x in p)[n//2]:.1f} |")
    L += ["", "## 광고 유형 × 폭 (PaddleOCR 줄 유사도)", "", "| 유형 | " + " | ".join(str(w) for w in WIDTHS) + " |",
          "|---|" + "---|" * len(WIDTHS)]
    for t in sorted({r["template"] for r in res}):
        cells = []
        for w in WIDTHS:
            r = next((r for r in res if r["template"] == t and r["w"] == w and "paddle" in r["per"]), None)
            cells.append(f"{r['per']['paddle']['sim']:.0%}" if r else "-")
        L.append(f"| {t} | " + " | ".join(cells) + " |")
    L += ["", "## 폭별로 못 읽은 문구(PaddleOCR, 유사도<90) 샘플", ""]
    for w in WIDTHS:
        fails = [(r["template"], it) for r in res if r["w"] == w and "paddle" in r["per"] for it in r["per"]["paddle"]["fails"]]
        tot = sum(r["per"]["paddle"]["n_items"] for r in res if r["w"] == w and "paddle" in r["per"])
        L.append(f"- **{w}px**: {len(fails)}/{tot} 문구 실패 · 예) " + " / ".join(f"“{it}”" for _, it in fails[:4]))
    L += ["", "## 놓친 위반(PaddleOCR)", ""]
    for w in WIDTHS:
        L.append(f"- {w}px: " + "; ".join(f"{r['template'][:3]}:" + ",".join(k[0] for k in r["per"]["paddle"]["FN"])
                                           for r in res if r["w"] == w and "paddle" in r["per"] and r["per"]["paddle"]["FN"]) or f"- {w}px: 없음")
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    return "\n".join(L)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("make", "all"):
        make()
    if mode in ("ocr", "all"):
        run_ocr()
    if mode in ("score", "all"):
        print(report(score_all()))
