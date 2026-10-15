"""명령행 진입점.

  # 1) 기준 문서(HWP/DOCX/PDF) 색인 만들기 (규정이 바뀔 때만 다시)
  python -m adreview build-reference reference_docs/ --out output/ref_index.json

  # 2) 광고물 점검 (이미지 / PPTX / PDF 여러 개 가능)
  python -m adreview check ad1.pptx ad2.png \
      --reference-index output/ref_index.json --product DEMO-CANCER-01 --out output/run1

  # OCR 결과만 확인
  python -m adreview ocr ad.png
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .checks import check_file, load_yaml
from .extract import extract_any
from .ocr import build_engine
from .reference import ReferenceIndex, build_reference_index
from .report import annotate_images, write_html, write_json, write_xlsx

ROOT = Path(__file__).resolve().parent.parent


def _engine_from_args(a):
    opts = json.loads(a.ocr_opts) if getattr(a, "ocr_opts", None) else {}
    try:
        return build_engine(a.engine, opts)
    except ImportError as e:
        hint = {"tesseract": "pip install pytesseract 및 tesseract 바이너리(+kor 데이터) 설치가 필요합니다.",
                "paddle": "pip install paddlepaddle paddleocr 및 모델 파일 반입이 필요합니다."}.get(a.engine, "")
        sys.exit(f"[오류] OCR 엔진 '{a.engine}' 을(를) 불러올 수 없습니다: {e}\n  {hint}")


def cmd_build_reference(a) -> int:
    idx = build_reference_index(a.folder)
    idx.save(a.out)
    print(f"조항 {len(idx.clauses)}개 색인 완료 → {a.out}")
    for w in idx.warnings:
        print("  [경고]", w)
    return 0


def cmd_ocr(a) -> int:
    engine = _engine_from_args(a)
    wd = tempfile.mkdtemp(prefix="adreview_")
    try:
        for f in a.files:
            for page in extract_any(f, engine, wd):
                print(f"=== {page.page_id} ===")
                for b in page.blocks:
                    tag = "N" if b.source == "native" else f"O:{b.image}/{b.variant or '-'}"
                    print(f"[{tag:16s} {b.conf:5.1f}] {b.text}")
                for w in page.warnings:
                    print("  [경고]", w)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    return 0


def cmd_check(a) -> int:
    rules = load_yaml(a.rules)
    master = load_yaml(a.master) if a.master and os.path.exists(a.master) else {}
    ref = ReferenceIndex.load(a.reference_index) if a.reference_index and os.path.exists(a.reference_index) else None
    if a.reference_index and ref is None:
        print(f"[경고] 기준 문서 색인을 찾을 수 없어 관련 조항 검색을 건너뜁니다: {a.reference_index}")
    engine = _engine_from_args(a)
    types = [t.strip() for t in a.product_type.split(",")] if a.product_type else None

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(exist_ok=True)

    results = []
    for f in a.files:
        print(f"처리 중: {f}")
        wd = str(work / Path(f).stem)
        os.makedirs(wd, exist_ok=True)
        try:
            pages = extract_any(f, engine, wd)
        except Exception as e:
            print(f"  [오류] {f}: {e}")
            continue
        res = check_file(pages, rules, master, ref, product_id=a.product, product_types=types)
        results.append(res)
        n = sum(1 for x in res.findings if x.status == "review")
        print(f"  → 검토 필요 {n}건 (페이지 {len(pages)}개)")

    if not results:
        print("처리된 파일이 없습니다.")
        return 1

    img_dir = out / "images"
    maps = {}
    for r in results:
        maps.update(annotate_images(r, str(img_dir)))
    html_path = write_html(results, str(out), maps)
    json_path = write_json(results, str(out))
    xlsx_path = write_xlsx(results, str(out))
    if not a.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n리포트: {html_path}\nJSON  : {json_path}\n엑셀  : {xlsx_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="adreview", description="보험 광고물 1차 점검 PoC (OCR + 룰 기반)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_ocr_args(p):
        p.add_argument("--engine", default="paddle", choices=["tesseract", "paddle"],
                       help="OCR 엔진 (기본: paddle. 모델 반입이 어렵거나 paddle 미설치 시 tesseract)")
        p.add_argument("--ocr-opts", help='엔진 옵션 JSON. 예) {"psm": 6} 또는 Paddle 모델 경로')

    p1 = sub.add_parser("build-reference", help="기준 문서 폴더를 조항 단위로 색인")
    p1.add_argument("folder")
    p1.add_argument("--out", default=str(ROOT / "output" / "ref_index.json"))
    p1.set_defaults(fn=cmd_build_reference)

    p2 = sub.add_parser("ocr", help="OCR 결과만 출력")
    p2.add_argument("files", nargs="+")
    add_ocr_args(p2)
    p2.set_defaults(fn=cmd_ocr)

    p3 = sub.add_parser("check", help="광고물 점검")
    p3.add_argument("files", nargs="+", help="이미지 / .pptx / .pdf")
    p3.add_argument("--rules", default=str(ROOT / "config" / "rules.yaml"))
    p3.add_argument("--master", default=str(ROOT / "config" / "product_master.yaml"))
    p3.add_argument("--reference-index", help="build-reference 로 만든 색인(JSON)")
    p3.add_argument("--product", help="상품 마스터의 product_id (미지정 시 키워드로 자동 식별)")
    p3.add_argument("--product-type", help="상품군 콤마 구분. 예) renewable,savings")
    p3.add_argument("--out", default=str(ROOT / "output" / "run"))
    p3.add_argument("--keep-work", action="store_true", help="중간 산출물(렌더링 이미지 등) 보존")
    add_ocr_args(p3)
    p3.set_defaults(fn=cmd_check)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
