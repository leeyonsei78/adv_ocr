"""광고심의점검표(변액보험 이외 보험) 자동 1차 점검.

config/checklist.yaml 에 정의된 점검표 항목(No.)마다 ○ / × / △ / - / ? 를 매긴다.
  ○ 적합  × 부적합(문구 누락·금지 표현 검출)  △ 미흡(일부만 충족·불확실)  - 해당사항 없음  ? 자동판정 불가(담당자 확인)

원칙
 - 이것은 심의 담당자의 점검표 작성을 돕는 "초안"이다. 특히 × 는 OCR 누락일 수 있고, ○ 도 패턴이 포착한 범위 안에서만 의미가 있다.
 - 모든 정규식은 공백을 제거한 텍스트에 적용한다.
 - 기존 룰(config/rules.yaml 의 REQ/BAN)·수치 대조·글자 크기 점검 결과를 재사용해 중복 판정을 피한다.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Optional

from .checks import _fuzzy_find, _snippet, page_groups
from .models import squash

OK, NG, PART, NA, MAN = "○", "×", "△", "-", "?"
MARK_KO = {OK: "적합", NG: "부적합", PART: "미흡", NA: "해당없음", MAN: "담당자 확인"}


@dataclass
class ChecklistRow:
    no: str
    group: str
    title: str
    basis: str
    sample: str
    mark: str
    mode: str                      # auto(자동 판정) / manual(담당자 확인 항목)
    detail: str = ""
    evidence: list = field(default_factory=list)   # 근거가 된 문구 [“…” (위치)]
    elems: dict = field(default_factory=dict)      # 요소별 상태 {이름: ok/fuzzy/missing/na}

    def to_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------------
class _Ctx:
    def __init__(self, pages: list):
        self.groups = [(p, g) for p in pages for g in page_groups(p)]
        self.whole = "".join(g.text for _, g in self.groups)

    def find(self, pats: list, strip: Optional[list] = None):
        """첫 매칭 (page_id, 매칭 문자열, 블록 문맥) 또는 None."""
        for p, g in self.groups:
            text = g.text
            for s in strip or []:
                text = re.sub(s, "", text)
            for pat in pats:
                m = re.search(pat, text)
                if m:
                    blk = g.block_at(m.start()) if not strip else None
                    return p.page_id, m.group(0), _snippet(blk, 60) if blk else ""
        return None

    def has(self, pats: list, strip: Optional[list] = None) -> bool:
        return self.find(pats, strip) is not None


def _short(page_id: str) -> str:
    return page_id.split(" / ")[-1] if " / " in page_id else page_id


def _ev(name: str, hit) -> str:
    txt = hit[1] if len(hit[1]) <= 40 else hit[1][:40] + "…"
    return f"{name}: “{txt}” ({_short(hit[0])})"


# ----------------------------------------------------------------------------
# 적용 여부
# ----------------------------------------------------------------------------
def _gate(spec: dict, ctx: _Ctx, types: set, types_known: bool):
    """('yes'|'no'|'unknown', 트리거 문구 or None)"""
    ap = spec.get("applies")
    if not ap:
        return "yes", None
    trig = ctx.find(ap["when_any"]) if ap.get("when_any") else None
    if trig:
        return "yes", trig
    pts = set(ap.get("product_types") or [])
    if pts and types_known and (pts & types):
        return "yes", None
    if pts and not types_known:
        return "unknown", None
    return "no", None


# ----------------------------------------------------------------------------
# 요소(elements) 점검
# ----------------------------------------------------------------------------
def _eval_elements(spec: dict, ctx: _Ctx) -> tuple:
    strip = spec.get("strip")
    elems, evidence = {}, []
    for el in spec.get("elements", []):
        name = el["name"]
        if el.get("when_any") and not ctx.has(el["when_any"]):
            elems[name] = "na"
            continue
        hit = ctx.find(el["any_of"], strip)
        if hit:
            elems[name] = "ok"
            evidence.append(_ev(name, hit))
            continue
        fz = None
        for kw in el.get("fuzzy", []) or []:
            fz = _fuzzy_find(ctx.whole, squash(kw))
            if fz:
                break
        if fz:
            elems[name] = "fuzzy"
            evidence.append(f"{name}: 유사 글자열 “{fz}” (OCR 오인식 가능성)")
        else:
            elems[name] = "missing"
    return elems, evidence


def _mark_from_elems(elems: dict, ok_mark: str = OK) -> str:
    live = [s for s in elems.values() if s != "na"]
    if not live:
        return NA
    n_ok = sum(1 for s in live if s == "ok")
    n_fz = sum(1 for s in live if s == "fuzzy")
    if n_ok == len(live):
        return ok_mark
    if n_ok == 0 and n_fz == 0:
        return NG
    return PART


def _missing_text(elems: dict) -> str:
    miss = [n for n, s in elems.items() if s == "missing"]
    fz = [n for n, s in elems.items() if s == "fuzzy"]
    parts = []
    if miss:
        parts.append("미확인: " + ", ".join(miss))
    if fz:
        parts.append("불확실(유사 글자열만): " + ", ".join(fz))
    return " / ".join(parts)


# ----------------------------------------------------------------------------
# 개별 항목 유형
# ----------------------------------------------------------------------------
def _do_reuse(spec: dict, findings: list, skipped: list) -> tuple:
    """rules.yaml 필수 문구 룰(REQ) 결과를 재사용."""
    marks, ev, det = [], [], []
    for rid in spec["rules"]:
        if any(s.startswith(rid + " ") for s in skipped):
            marks.append(NA)
            det.append(f"{rid}: 상품군 불일치로 적용 제외")
            continue
        fs = [f for f in findings if f.rule_id == rid and f.category == "required"]
        if any(f.status == "ok" for f in fs):
            marks.append(OK)
            ev += [f.detail for f in fs if f.status == "ok"][:1]
        elif any(f.status == "review" and f.title.startswith("필수 문구 불확실") for f in fs):
            marks.append(PART)
            det.append(next(f.detail for f in fs if f.title.startswith("필수 문구 불확실")))
        elif any(f.status == "review" and f.severity == "low" for f in fs):
            marks.append(MAN)
            det.append("상품군 미지정 — 해당 상품이면 필수 (--product / --product-type 지정 시 확정)")
        elif fs:
            marks.append(NG)
            det.append("해당 문구를 찾지 못했습니다 (OCR 누락 가능성은 원본에서 확인)")
        else:
            marks.append(MAN)
    for m in (NG, PART, MAN, OK, NA):          # 가장 나쁜 판정 우선
        if m in marks:
            return m, "; ".join(det) or ("필수 문구 확인됨" if m == OK else ""), ev
    return MAN, "", ev


def _do_prohibited(spec: dict, ctx: _Ctx, findings: list) -> tuple:
    rules, cats = set(spec.get("rules") or []), set(spec.get("categories") or [])
    hits, seen = [], set()

    def add(text: str, where: str):
        k = squash(text)
        if k and k not in seen:
            seen.add(k)
            hits.append(f"“{text}” ({where})")

    for f in findings:
        if f.status != "review" or f.severity == "info":
            continue
        if (f.category == "prohibited" and f.rule_id in rules) or f.category in cats:
            add(f.matched_text or f.title, _short(f.page))
    for pat in spec.get("patterns") or []:
        for p, g in ctx.groups:
            for m in re.finditer(pat, g.text):
                add(m.group(0), _short(p.page_id))
    if hits:
        return NG, "검출: " + ", ".join(hits[:6]) + (f" 외 {len(hits) - 6}건" if len(hits) > 6 else ""), hits[:6]
    msg = "자동 패턴 미검출 (패턴 범위 밖의 위반은 걸러내지 못합니다)"
    if spec.get("hint"):
        msg += " — " + spec["hint"]
    return spec.get("no_hit", OK), msg, []


def _do_visual(spec: dict, findings: list) -> tuple:
    vs = [f for f in findings if f.category == "visual" and f.status == "review"]
    if vs:
        return PART, f"글자 크기 의심 {len(vs)}건 — " + "; ".join(f.title for f in vs[:3]), []
    return OK, "글자 크기 자동 점검에서 이상 없음. " + spec.get("hint", ""), []


def _parse_date(y, m, d) -> Optional[dt.date]:
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


_RANGE = re.compile(r"(\d{4})[.\-/년](\d{1,2})[.\-/월](\d{1,2})일?\.?[~∼～\-–](\d{4})[.\-/년](\d{1,2})[.\-/월](\d{1,2})일?")


def _do_validity(spec: dict, ctx: _Ctx, today: dt.date, expired_mark: str) -> tuple:
    for p, g in ctx.groups:
        m = _RANGE.search(g.text)
        if not m:
            continue
        a, b = _parse_date(*m.group(1, 2, 3)), _parse_date(*m.group(4, 5, 6))
        if not a or not b or a > b:
            return PART, f"유효기간 표기를 해석할 수 없거나 앞뒤가 바뀌었습니다: “{m.group(0)}” (OCR 오독 가능성)", [m.group(0)]
        ev = [f"유효기간 “{a} ~ {b}” ({_short(p.page_id)})"]
        if b < today:
            return expired_mark, f"유효기간이 {b} 에 종료되었습니다 (기준일 {today}).", ev
        if a > today:
            return PART, f"유효기간 시작일({a})이 기준일({today}) 이후입니다.", ev
        return OK, f"유효기간 내({a} ~ {b}, 기준일 {today}).", ev
    if ctx.has(["심의필", "준법감시인"]):
        return PART, "심의필 표기는 있으나 ‘시작일 ~ 종료일’ 형식의 유효기간을 찾지 못했습니다.", []
    return NG, "심의필 번호와 유효기간을 찾지 못했습니다.", []


def _do_company(spec: dict, ctx: _Ctx, products: list) -> tuple:
    names = [squash(n) for p in products for n in ([p["company"]] if isinstance(p.get("company"), str) else p.get("company") or [])]
    if names:
        for n in names:
            hit = ctx.find([re.escape(n)])
            if hit:
                msg, mark = "상품 마스터의 회사명과 일치", OK
                break
        else:
            return NG, f"상품 마스터의 회사명({', '.join(names)})을 찾지 못했습니다.", []
    else:
        hit = ctx.find([spec["company_regex"]])
        if not hit:
            return NG, "회사명(보험사·보험대리점)으로 볼 만한 문구를 찾지 못했습니다.", []
        msg, mark = "회사명으로 보이는 문구가 있습니다. 자사 명칭과 일치하는지 확인하세요 (상품 마스터에 company 를 넣으면 자동 대조).", MAN
    ev = [_ev("회사명", hit)]
    if ctx.has([spec["agency_regex"]]) and not ctx.has([spec["agency_reg_no"]]):
        return PART, "보험대리점으로 보이나 협회 등록번호를 찾지 못했습니다. " + msg, ev
    return mark, msg, ev


def _do_product_name(ctx: _Ctx, products: list) -> tuple:
    if not products:
        return MAN, "상품 식별 실패 — --product 로 상품을 지정하면 약관상 명칭과 대조합니다.", []
    best = None
    for p in products:
        full = squash(re.sub(r"^\(.*?\)", "", p.get("name", "")))
        if full and full in ctx.whole:
            return OK, f"상품명 확인: {p['name']}", [f"상품명 “{full}”"]
        kws = [squash(k) for k in p.get("keywords", [])]
        for k in kws:
            if k and k in ctx.whole:
                best = (p, k)
    if best:
        return PART, f"약관상 명칭({best[0]['name']}) 전체가 아니라 일부(“{best[1]}”)만 보입니다. 동일성 인정 범위인지 확인하세요.", [f"“{best[1]}”"]
    return NG, "상품 마스터의 상품명을 찾지 못했습니다.", []


def _do_derived(spec: dict, row_by_no: dict, ctx: _Ctx, findings: list) -> tuple:
    d = spec["derive"]
    kind = d["kind"]
    if kind == "elements_of":
        src = row_by_no.get(d["item"])
        if not src or src.mark == NA:
            return NA, f"{d['item']} 가 해당 없음이므로 해당 없음", []
        sub = {n: src.elems.get(n, "na") for n in d["names"]}
        mark = _mark_from_elems(sub)
        if mark == NA:
            return NA, f"해당 요소가 노출되지 않아 해당 없음 (항목 {d['item']} 기준)", []
        return mark, (_missing_text(sub) or "관련 요소 확인됨") + f" (항목 {d['item']} 의 요소 점검 결과)", []
    if kind == "source_citation":
        src = row_by_no.get(d["source_item"])
        rank = [f for f in findings if f.rule_id == d["ranking_rule"] and f.status == "review"
                and re.search(d["ranking_regex"], squash(f.matched_text))]
        if src and src.mark in (OK, PART, NG):
            return src.mark, f"통계 인용 출처 점검 결과({d['source_item']}) 반영: {src.detail}", src.evidence
        if rank and not ctx.has(["출처", "기준일", "조사기관", "발표"]):
            ex = ", ".join(f"“{f.matched_text}”" for f in rank[:3])
            return PART, f"최상급·순위 표현 {ex} 의 근거(출처·기준일) 표기를 찾지 못했습니다.", [f.matched_text for f in rank[:3]]
        if rank:
            return MAN, "최상급·순위 표현이 있고 출처 관련 문구가 보입니다. 근거의 적정성을 확인하세요.", []
        return NA, "통계·순위 인용이 없어 해당 없음", []
    if kind == "any_fail":
        rows = [row_by_no[n] for n in d["items"] if n in row_by_no]
        bad = [r for r in rows if r.mark in (NG, PART)]
        if bad:
            return PART, "필수안내 미비로 권리·의무 안내가 부족할 수 있습니다: " + ", ".join(f"{r.no} {r.title}({r.mark})" for r in bad), []
        if any(r.mark == MAN for r in rows):
            return MAN, "일부 필수안내 항목을 자동 판정하지 못했습니다.", []
        return OK, "권리·의무 관련 필수안내 항목(" + ", ".join(d["items"]) + ")이 모두 확인됨", []
    return MAN, "", []


# ----------------------------------------------------------------------------
# 진입점
# ----------------------------------------------------------------------------
def evaluate_checklist(cfg: dict, pages: list, findings: list, skipped: list, types: set,
                       types_known: bool, products: list, today: Optional[dt.date] = None) -> list:
    today = today or dt.date.today()
    ctx = _Ctx(pages)
    settings = cfg.get("settings", {})
    rows, row_by_no = [], {}

    for spec in cfg.get("items", []):
        t = spec["type"]
        mode = "manual" if t in ("manual", "na") else "auto"
        row = ChecklistRow(no=spec["num"], group=spec["group"], title=spec["title"], basis=spec.get("basis", ""),
                           sample=spec.get("sample", ""), mark=MAN, mode=mode)

        gate, trig = ("yes", None) if t in ("na",) else _gate(spec, ctx, types, types_known)
        if spec.get("enabled", True) is False:
            row.mark, row.mode = NA, "auto"
            row.detail = "기준 관리에서 비활성화된 항목 (검수 제외)"
        elif gate == "no":
            row.mark, row.mode = NA, "auto"
            row.detail = spec.get("not_applicable_note") or "적용 조건(상품군·해당 문구)에 해당하지 않아 해당 없음으로 처리"
        elif gate == "unknown" and t in ("elements", "reuse"):
            pts = ", ".join(spec["applies"].get("product_types", []))
            row.mark, row.mode = MAN, "manual"
            row.detail = f"상품군 미지정 — [{pts}] 상품이면 점검 필요 (--product / --product-type 지정 시 확정)"
        elif t == "elements":
            elems, ev = _eval_elements(spec, ctx)
            row.elems, row.evidence = elems, ev
            row.mark = _mark_from_elems(elems, spec.get("ok_mark", OK))
            if row.mark == NA:
                row.detail = "적용되는 요소가 없어 해당 없음"
            elif row.mark in (OK, MAN):
                row.detail = spec.get("ok_note", "필요 요소가 모두 확인됨")
            else:
                row.detail = _missing_text(elems) + " (OCR 누락 가능성은 원본에서 확인)"
            if trig:
                row.detail += f" | 적용 근거: “{trig[1][:30]}”"
        elif t == "reuse":
            row.mark, row.detail, row.evidence = _do_reuse(spec, findings, skipped)
        elif t == "prohibited":
            row.mark, row.detail, row.evidence = _do_prohibited(spec, ctx, findings)
        elif t == "visual":
            row.mark, row.detail, row.evidence = _do_visual(spec, findings)
        elif t == "validity":
            row.mark, row.detail, row.evidence = _do_validity(spec, ctx, today, settings.get("expired_mark", NG))
        elif t == "company":
            row.mark, row.detail, row.evidence = _do_company(spec, ctx, products)
        elif t == "product_name":
            row.mark, row.detail, row.evidence = _do_product_name(ctx, products)
        elif t == "derived":
            row.mark, row.detail, row.evidence = _do_derived(spec, row_by_no, ctx, findings)
        elif t == "na":
            row.mark, row.detail = NA, spec.get("reason", "")
        else:                                       # manual
            row.mark, row.detail = MAN, spec.get("hint", "자동 판정하지 않는 항목입니다.")
            if trig:
                row.evidence = [f"“{trig[1][:30]}” ({_short(trig[0])})"]
        rows.append(row)
        row_by_no[row.no] = row
    return rows


def summarize(rows: list) -> dict:
    c = Counter(r.mark for r in rows)
    return {m: c.get(m, 0) for m in (OK, NG, PART, MAN, NA)}
