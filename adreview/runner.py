"""검수 실행 공통 모듈 — CLI(`check`)와 웹 화면이 같은 경로로 검수한다."""
from __future__ import annotations

import datetime as _dt
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from .checks import check_file, load_yaml
from .criteria import describe
from .extract import extract_any
from .reference import ReferenceIndex
from .report import annotate_images, write_html, write_json, write_xlsx


def run_check(files: list, out_dir: str, engine, rules_path: str, master_path: str = "", checklist_path: str = "",
              reference_index: str = "", product: Optional[str] = None, product_types: Optional[list] = None,
              today: Optional[_dt.date] = None, keep_work: bool = False,
              log: Callable[[str], None] = print, display_names: Optional[dict] = None) -> dict:
    """files 를 검수해 out_dir 에 report.html / result.json / result.xlsx / criteria.json 을 만든다.
    반환: {"ok": bool, "criteria": dict, "paths": {...}, "n_review": {파일: 검토필요 건수}, "errors": [..]}"""
    rules = load_yaml(rules_path)
    master = load_yaml(master_path) if master_path and os.path.exists(master_path) else {}
    ref = ReferenceIndex.load(reference_index) if reference_index and os.path.exists(reference_index) else None
    cl_cfg = load_yaml(checklist_path) if checklist_path and os.path.exists(checklist_path) else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(exist_ok=True)
    names = display_names or {}

    results, n_review, errors = [], {}, []
    for i, f in enumerate(files, 1):
        shown = names.get(f, f)
        log(f"[{i}/{len(files)}] 처리 중: {shown}")
        wd = str(work / f"{i}_{Path(f).stem}")
        os.makedirs(wd, exist_ok=True)
        try:
            pages = extract_any(f, engine, wd)
            if shown != f:                      # 업로드 임시 이름 대신 원래 파일명을 리포트에 표시
                for p in pages:
                    p.file = shown
        except Exception as e:
            errors.append(f"{shown}: {e}")
            log(f"  [오류] {shown}: {e}")
            continue
        res = check_file(pages, rules, master, ref, product_id=product, product_types=product_types,
                         checklist_cfg=cl_cfg, today=today)
        results.append(res)
        n_review[shown] = sum(1 for x in res.findings if x.status == "review")
        log(f"  → 검토 필요 {n_review[shown]}건 (페이지 {len(pages)}개)")
        if res.checklist:
            from .checklist import summarize
            log("  → 점검표 " + " ".join(f"{k}{v}" for k, v in summarize(res.checklist).items()))

    if not results:
        shutil.rmtree(work, ignore_errors=True)
        return {"ok": False, "criteria": None, "paths": {}, "n_review": {}, "errors": errors}

    maps = {}
    for r in results:
        maps.update(annotate_images(r, str(out / "images")))
    crit = describe(rules, cl_cfg or {}, master, {"rules": rules_path, "checklist": checklist_path, "master": master_path})
    log(f"적용 기준 버전 {crit['version']} (필수 {crit['counts']['required']} · 금지 {crit['counts']['prohibited']} "
        f"· 점검표 {crit['counts']['checklist']})")
    paths = {"html": write_html(results, str(out), maps, criteria=crit),
             "json": write_json(results, str(out), criteria=crit),
             "xlsx": write_xlsx(results, str(out), criteria=crit)}
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "criteria": crit, "paths": paths, "n_review": n_review, "errors": errors}
