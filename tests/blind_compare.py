"""블라인드 24장: LLM 직접 판독 vs PaddleOCR vs Tesseract (정답은 판독 후 열람)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import compare_diverse as cd
from blind_transcripts import LLM
from adreview.models import TextBlock
man = json.loads((ROOT / "samples/blind/manifest.json").read_text(encoding="utf-8"))
cache = json.loads((ROOT / "output/blind/ocr_cache.json").read_text(encoding="utf-8"))
res = []
for m in man:
    per = {"llm": cd.score(m, [TextBlock(text=l, source="native") for l in LLM[m["template"]]])}
    for e in ("paddle", "tesseract"):
        per[e] = cd.score(m, cd.to_blocks(cache[m["file"]][e]["blocks"])); per[e]["time"] = cache[m["file"]][e]["time"]
    res.append({"file": m["file"], "w": m["size"][0], "per": per})
(ROOT / "output/blind/results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
N = {"llm": "LLM(직접 판독)", "paddle": "PaddleOCR", "tesseract": "Tesseract"}
def agg(rows, e):
    p = [r["per"][e] for r in rows]; n = len(p)
    return (sum(x["sim"] for x in p) / n, sum(x["good"] for x in p) / n, sum(x["num_ok"] for x in p) / max(1, sum(x["num_total"] for x in p)),
            sum(x["TP"] for x in p), sum(x["n_gt"] for x in p), sum(len(x["FN"]) for x in p), sum(len(x["FP"]) for x in p))
L = ["# 블라인드 비교 — 신규 이미지 24장 (폭 600/450/340/260px)", "", "| 폭 | 장수 | 방식 | 줄 유사도 | 줄 양호(≥90) | 숫자 | 정탐 | 누락 | 오탐 |", "|---|---|---|---|---|---|---|---|---|"]
for w in (600, 450, 340, 260, "전체"):
    rows = [r for r in res if w == "전체" or r["w"] == w]
    for e in N:
        s, g, n, tp, gt, fn, fp = agg(rows, e)
        L.append(f"| {w} | {len(rows)} | {N[e]} | {s:.0%} | {g:.0%} | {n:.0%} | {tp}/{gt} | {fn} | {fp} |")
L += ["", "## 이미지별 줄 유사도 (LLM / Paddle / Tesseract)", ""]
for r in sorted(res, key=lambda r: -r["w"]):
    L.append(f"- {r['file']} ({r['w']}px): " + " / ".join(f"{r['per'][e]['sim']:.0%}" for e in N))
L += ["", "## 놓친 위반 / LLM이 틀린 줄", ""]
for e in ("llm", "paddle"):
    L.append(f"### {N[e]}")
    for r in res:
        if r["per"][e]["FN"]: L.append(f"- {r['file']}({r['w']}px) 누락: " + ", ".join(k[0] for k in r["per"][e]["FN"]))
    if e == "llm":
        for r in res:
            for s, it in r["per"]["llm"]["worst"]:
                if s < 90: L.append(f"- {r['file']} 정답 줄 미판독({s:.0f}): “{it}”")
L.append("")
(ROOT / "output/blind/report.md").write_text("\n".join(L), encoding="utf-8")
print("\n".join(L))
