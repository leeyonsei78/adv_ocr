"""samples/blind 이미지에 PaddleOCR / Tesseract 를 돌려 output/blind/ocr_cache.json 에 저장."""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
from adreview.ocr import PaddleOCREngine, TesseractEngine
src, out = ROOT / "samples/blind", ROOT / "output/blind"; out.mkdir(parents=True, exist_ok=True)
files = sorted(p.name for p in src.glob("B*.jpg")); cache = {}
for name, E in (("paddle", PaddleOCREngine), ("tesseract", TesseractEngine)):
    eng = E()
    for f in files:
        t = time.time(); bl = eng.recognize(str(src / f))
        cache.setdefault(f, {})[name] = {"time": round(time.time() - t, 2), "blocks": [b.to_dict() for b in bl]}
    print(name, "done", flush=True)
(out / "ocr_cache.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
