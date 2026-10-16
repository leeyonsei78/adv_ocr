"""LLM(Claude 비전) 직접 판독 vs OCR(PaddleOCR/Tesseract) — 저해상도 45장(폭 400/300/220). 같은 채점 코드(compare_diverse.score) 사용."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import compare_diverse as cd
from llm_transcripts import T
from adreview.models import TextBlock

man = json.loads((ROOT / "samples/lowres/manifest.json").read_text(encoding="utf-8"))
cache = json.loads((ROOT / "output/lowres/ocr_cache.json").read_text(encoding="utf-8"))
W = [400, 300, 220]
res = []
for m in man:
    w = m["size"][0]
    if w not in W:
        continue
    per = {"llm": cd.score(m, [TextBlock(text=l, source="native") for l in T[m["template"]][w]])}
    for e in ("paddle", "tesseract"):
        per[e] = cd.score(m, cd.to_blocks(cache[m["file"]][e]["blocks"]))
    res.append({"file": m["file"], "template": m["template"], "w": w, "per": per})
(ROOT / "output/llm_compare/results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=list), encoding="utf-8")

def row(rows, e):
    p = [r["per"][e] for r in rows]; n = len(p)
    return (sum(x["sim"] for x in p) / n, sum(x["good"] for x in p) / n,
            sum(x["num_ok"] for x in p) / max(1, sum(x["num_total"] for x in p)),
            sum(x["TP"] for x in p), sum(x["n_gt"] for x in p), sum(len(x["FN"]) for x in p), sum(len(x["FP"]) for x in p))
N = {"llm": "LLM(직접 판독)", "paddle": "PaddleOCR", "tesseract": "Tesseract"}
L = ["# LLM 직접 판독 vs OCR — 저해상도 (원본 1400px → 폭 400/300/220px, JPEG q70)", "",
     "| 폭 | 방식 | 줄 유사도 | 줄 양호(≥90) | 숫자 | 정탐 | 누락 | 오탐 |", "|---|---|---|---|---|---|---|---|"]
for w in W + ["전체"]:
    rows = [r for r in res if w == "전체" or r["w"] == w]
    for e in ("llm", "paddle", "tesseract"):
        s, g, n, tp, gt, fn, fp = row(rows, e)
        L.append(f"| {w} | {N[e]} | {s:.0%} | {g:.0%} | {n:.0%} | {tp}/{gt} | {fn} | {fp} |")
L += ["", "## 유형별 줄 유사도 (LLM / Paddle), 폭 400·300·220", "", "| 유형 | 400 | 300 | 220 |", "|---|---|---|---|"]
for t in sorted({r['template'] for r in res}):
    c = []
    for w in W:
        r = next(r for r in res if r["template"] == t and r["w"] == w)
        c.append(f"{r['per']['llm']['sim']:.0%} / {r['per']['paddle']['sim']:.0%}")
    L.append(f"| {t} | " + " | ".join(c) + " |")
L += ["", "## 놓친 위반", ""]
for e in ("llm", "paddle"):
    L.append(f"### {N[e]}")
    for r in res:
        fn = r["per"][e]["FN"]
        if fn:
            L.append(f"- {r['file']}: " + ", ".join(k[0] for k in fn))
    L.append("")
(ROOT / "output/llm_compare/report.md").write_text("\n".join(L), encoding="utf-8")
print("\n".join(L))
