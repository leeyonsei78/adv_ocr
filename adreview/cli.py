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

from .checks import load_yaml
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
    from .runner import run_check
    if a.reference_index and not os.path.exists(a.reference_index):
        print(f"[경고] 기준 문서 색인을 찾을 수 없어 관련 조항 검색을 건너뜁니다: {a.reference_index}")
    types = [t.strip() for t in a.product_type.split(",")] if a.product_type else None
    today = None
    if a.today:
        import datetime as _dt
        today = _dt.date.fromisoformat(a.today)
    engine = _engine_from_args(a)
    r = run_check(a.files, a.out, engine, a.rules, a.master, a.checklist, a.reference_index or "",
                  a.product, types, today, a.keep_work)
    if not r["ok"]:
        print("처리된 파일이 없습니다.")
        return 1
    p = r["paths"]
    print(f"\n리포트: {p['html']}\nJSON  : {p['json']}\n엑셀  : {p['xlsx']}")
    return 0


def cmd_web(a) -> int:
    from .webapp import serve
    return serve(a.host, a.port, a.engine, a.ocr_opts, a.password or "", a.admin_password or "")


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
    p3.add_argument("--checklist", default=str(ROOT / "config" / "checklist.yaml"),
                    help="광고심의점검표 정의(yaml). 빈 값이면 점검표 판정을 건너뜁니다")
    p3.add_argument("--today", help="광고 유효기간 비교 기준일 YYYY-MM-DD (기본: 오늘)")
    p3.add_argument("--keep-work", action="store_true", help="중간 산출물(렌더링 이미지 등) 보존")
    add_ocr_args(p3)
    p3.set_defaults(fn=cmd_check)

    p4 = sub.add_parser("web", help="웹 화면 실행 (PPT/이미지 업로드 검수 + 검수 기준 관리)")
    p4.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1(본인 PC만). 사내망 공유 시 0.0.0.0 (인증이 없으니 내부망에서만)")
    p4.add_argument("--port", type=int, default=8080)
    p4.add_argument("--password", help="검수자 비밀번호 (환경변수 ADREVIEW_PASSWORD 도 가능). 지정하면 로그인이 필요")
    p4.add_argument("--admin-password", help="관리자 비밀번호 (환경변수 ADREVIEW_ADMIN_PASSWORD). 지정하면 기준 수정은 관리자만")
    add_ocr_args(p4)
    p4.set_defaults(fn=cmd_web)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
