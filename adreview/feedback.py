"""준법·심의 담당자 의견(오탐 사례) 반영 — config/rules.yaml 의 reviewer_feedback 섹션을 적용한다.

세 종류의 보정을 한다.
  accepted_expressions : 심의에서 허용된 표현. 금지·주의 표현 검출을 '참고(info)'로 낮춘다.
  media_exemptions     : 매체 특성상 감독당국 협의·심의 경험으로 용인되는 항목. 매체 키워드가 있으면
                         해당 필수문구 검출(REQ)과 점검표 항목을 해당 없음 처리한다.
  context_rules        : 후속 페이지에서 세부 조건을 안내하는 구조(이벤트 배너 등). 연결 안내 문구가 있으면
                         해당 지적을 낮음으로 낮추고 연결 화면 확인으로 바꾼다.
모두 '무엇을 왜 보정했는지'를 detail/비고에 남겨 담당자가 추적할 수 있게 한다.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import squash


def _page_text(pages: list) -> str:
    out = []
    for p in pages:
        for b in getattr(p, "blocks", []) or []:
            out.append(getattr(b, "text", "") or "")
    return squash("".join(out))


def media_hits(pages: list, fb: dict) -> list:
    text = _page_text(pages)
    hits = []
    for m in fb.get("media_exemptions", []) or []:
        if any(re.search(k, text) for k in m.get("media_any", [])):
            hits.append(m)
    return hits


def context_hits(pages: list, fb: dict) -> list:
    text = _page_text(pages)
    return [c for c in fb.get("context_rules", []) or []
            if any(re.search(k, text) for k in c.get("link_any", []))]


def apply_to_findings(findings: list, pages: list, rules: dict) -> list:
    """findings 를 제자리에서 보정하고, 적용 내역(목록)을 반환."""
    fb = rules.get("reviewer_feedback") or {}
    if not fb:
        return []
    log = []
    accepted = [(a, re.compile(a["pattern"])) for a in fb.get("accepted_expressions", []) or []]
    media = media_hits(pages, fb)
    ctx = context_hits(pages, fb)
    media_rules = {r: m for m in media for r in m.get("rule_ids", [])}
    ctx_rules = {r: c for c in ctx for r in c.get("rule_ids", [])}

    for f in findings:
        if f.status != "review":
            continue
        probe = squash(f.matched_text) + " " + squash(f.detail)
        done = False
        for a, pat in accepted:
            if f.rule_id in (a.get("rule_ids") or [f.rule_id]) and pat.search(probe):
                f.status, f.severity = "info", "info"
                f.title = f"[준법 의견 반영·허용 표현] {f.title}"
                f.detail = f"{a['reason']} (의견 {a['id']})  | 원래 사유: {f.detail}"
                log.append((a["id"], f.rule_id, f.matched_text or f.title, f.page))
                done = True
                break
        if done:
            continue
        m = media_rules.get(f.rule_id)
        if m:
            f.status, f.severity = "info", "info"
            f.title = f"[준법 의견 반영·매체 예외] {f.title}"
            f.detail = f"{m['reason']} (의견 {m['id']})  | 원래 사유: {f.detail}"
            log.append((m["id"], f.rule_id, f.title, f.page))
            continue
        c = ctx_rules.get(f.rule_id)
        if c:
            f.severity = "low"
            f.title = f"[연결 화면 확인] {f.title}"
            f.detail = f"{c['reason']} (의견 {c['id']})  | 원래 사유: {f.detail}"
            log.append((c["id"], f.rule_id, f.title, f.page))
    return log


def apply_to_checklist(rows: list, pages: list, rules: dict) -> list:
    fb = rules.get("reviewer_feedback") or {}
    if not fb:
        return []
    log = []
    for m in media_hits(pages, fb):
        for r in rows:
            if r.no in (m.get("items") or []) and r.mark in ("×", "△", "?"):
                r.detail = f"[매체 예외] {m['reason']} (의견 {m['id']})  | 원래 판정 {r.mark}: {r.detail}"
                r.mark = "-"
                log.append((m["id"], r.no))
    for c in context_hits(pages, fb):
        for r in rows:
            if r.no in (c.get("items") or []) and r.mark in ("×", "△"):
                r.detail = f"[연결 화면 확인] {c['reason']} (의견 {c['id']})  | 원래 판정 {r.mark}: {r.detail}"
                r.mark = "?"
                log.append((c["id"], r.no))
    for r in rows:   # 허용 표현으로 내려간 건은 점검표 prohibited 항목이 이미 info 를 무시하므로 별도 처리 없음
        pass
    return log
