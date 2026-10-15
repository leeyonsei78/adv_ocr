"""규칙 기반 점검: 필수 문구 / 금지·과장 표현 / 수치 대조 / 시각(글자 크기) / OCR 품질.

중요한 전제
 - 이 모듈은 "위반 확정"이 아니라 "검토 필요 항목"을 뽑아낸다. 최종 판단은 심의 담당자의 몫이다.
 - 모든 패턴은 공백을 제거한 텍스트에서 검사한다 (OCR 이 공백을 넣거나 빼는 오류에 강하게).
 - 룰 내용(필수 문구·금지 표현·글자 크기 비율 등)은 config/*.yaml 에 있고, 코드는 그 파일을 해석만 한다.
"""
from __future__ import annotations

import difflib
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .models import AdPage, Finding, TextBlock, squash


# ----------------------------------------------------------------------------
# 설정 로딩
# ----------------------------------------------------------------------------
def load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ----------------------------------------------------------------------------
# 텍스트 그룹 (같은 출처·같은 이미지의 블록끼리 읽기 순서로 이어 붙임)
# ----------------------------------------------------------------------------
@dataclass
class TextGroup:
    key: tuple                     # (source, image, variant)
    blocks: list
    text: str = ""                 # 공백 제거한 전체 텍스트
    owner: list = field(default_factory=list)   # text 의 각 글자 → blocks 인덱스

    @classmethod
    def build(cls, key, blocks):
        g = cls(key=key, blocks=blocks)
        parts, owner = [], []
        for i, b in enumerate(blocks):
            s = squash(b.text)
            parts.append(s)
            owner.extend([i] * len(s))
        g.text = "".join(parts)
        g.owner = owner
        return g

    def block_at(self, pos: int) -> Optional[TextBlock]:
        if 0 <= pos < len(self.owner):
            return self.blocks[self.owner[pos]]
        return None


def page_groups(page: AdPage) -> list:
    """OCR 그룹(bbox 있음)을 먼저, native 그룹을 나중에 — 중복 제거 시 위치 정보가 있는 쪽이 남게."""
    buckets: "OrderedDict[tuple, list]" = OrderedDict()
    for b in page.blocks:
        buckets.setdefault((b.source, b.image, b.variant), []).append(b)
    vrank = {"page": 0, "sparse": 1, "bands": 2}   # 큰 글씨·본문에 강한 변형부터 (중복 제거 시 먼저 채택)
    ordered = sorted(buckets.items(), key=lambda kv: (kv[0][0] == "native", str(kv[0][1]), vrank.get(kv[0][2], 9)))
    return [TextGroup.build(k, v) for k, v in ordered]


def _snippet(block: Optional[TextBlock], limit: int = 90) -> str:
    if not block:
        return ""
    t = re.sub(r"\s+", " ", block.text).strip()
    return t if len(t) <= limit else t[:limit] + "…"


def _loc(block: Optional[TextBlock]) -> tuple:
    if block and block.bbox:
        return block.image, tuple(round(v) for v in block.bbox)
    return None, None


# ----------------------------------------------------------------------------
# 1) 필수 문구 (파일 단위)
# ----------------------------------------------------------------------------
def _fuzzy_find(text: str, keyword: str, thr: float = 0.72) -> Optional[str]:
    n = len(keyword)
    if n == 0 or len(text) < max(2, n - 1):
        return None
    best, best_s = 0.0, ""
    for size in {n - 1, n, n + 1}:
        if size < 2:
            continue
        for i in range(0, len(text) - size + 1):
            w = text[i:i + size]
            if keyword[0] not in w and keyword[-1] not in w:
                continue
            r = difflib.SequenceMatcher(None, keyword, w).ratio()
            if r > best:
                best, best_s = r, w
    return best_s if best >= thr else None


def check_required(pages: list, rules: dict, active_types: set, types_known: bool) -> tuple:
    findings, skipped = [], []
    file_name = pages[0].file if pages else ""
    all_groups = [(p, g) for p in pages for g in page_groups(p)]
    whole = "".join(g.text for _, g in all_groups)

    for rule in rules.get("required_phrases", []):
        applies = set(rule.get("applies_to") or [])
        sev = rule.get("severity", "medium")
        note = ""
        if applies:
            if types_known and not (applies & active_types):
                skipped.append(f"{rule['id']} {rule['name']} (상품군 불일치로 제외)")
                continue
            if not types_known:
                sev = "low"
                note = " (상품군 미지정 — 해당 상품군[" + ",".join(sorted(applies)) + "]이면 필수)"

        pats = [re.compile(p) for p in (rule.get("any_of") or [])]
        all_pats = [re.compile(p) for p in (rule.get("all_of") or [])]

        found = None  # (page, group, match)
        for p, g in all_groups:
            if pats:
                for pat in pats:
                    m = pat.search(g.text)
                    if m:
                        found = (p, g, m)
                        break
            if found:
                break
        if all_pats and not pats:
            ok = all(any(pat.search(g.text) for _, g in all_groups) for pat in all_pats)
            if ok:
                found = (None, None, None)

        if found:
            p, g, m = found
            if m is not None:
                blk = g.block_at(m.start())
                img, bb = _loc(blk)
                findings.append(Finding(
                    rule_id=rule["id"], category="required", severity="info", status="ok",
                    title=f"필수 문구 확인: {rule['name']}",
                    detail=f"{p.label} 에서 확인됨: “{m.group(0)}”",
                    page=p.page_id, matched_text=m.group(0), image=img, bbox=bb,
                    basis=rule.get("basis", "")))
            else:
                findings.append(Finding(
                    rule_id=rule["id"], category="required", severity="info", status="ok",
                    title=f"필수 문구 확인: {rule['name']}", detail="모든 필수 요소 확인됨",
                    page=file_name, basis=rule.get("basis", "")))
            continue

        # 못 찾았을 때: 유사 문구(OCR 오인식 가능성) 탐색
        fuzzy_hit = None
        for kw in rule.get("fuzzy", []) or []:
            hit = _fuzzy_find(whole, squash(kw))
            if hit:
                fuzzy_hit = (kw, hit)
                break
        if fuzzy_hit:
            findings.append(Finding(
                rule_id=rule["id"], category="required", severity="medium" if sev == "high" else sev,
                title=f"필수 문구 불확실: {rule['name']}",
                detail=f"정확히 일치하는 문구는 없으나 유사한 글자열 “{fuzzy_hit[1]}” 이 있습니다 "
                       f"('{fuzzy_hit[0]}' OCR 오인식 가능성). 원본에서 육안 확인하세요.{note}",
                page=file_name, matched_text=fuzzy_hit[1], basis=rule.get("basis", ""),
                query=rule["name"]))
        else:
            findings.append(Finding(
                rule_id=rule["id"], category="required", severity=sev,
                title=f"필수 문구 누락 의심: {rule['name']}",
                detail=f"검토 대상 {len(pages)}개 페이지(슬라이드) 어디에서도 해당 문구를 찾지 못했습니다. "
                       f"(OCR 누락 가능성이 있으니 원본 확인){note}",
                page=file_name, basis=rule.get("basis", ""), query=rule["name"]))
    return findings, skipped


# ----------------------------------------------------------------------------
# 2) 금지·과장 표현 (페이지 단위)
# ----------------------------------------------------------------------------
_CATEGORY_KO = {
    "exaggeration": "과장", "absolute": "단정·절대", "comparison": "비교",
    "guarantee": "보장·확정", "urgency": "조급 유발",
}


def check_prohibited(page: AdPage, groups: list, rules: dict) -> list:
    findings, seen = [], set()
    for rule in rules.get("prohibited_expressions", []):
        pat = re.compile(rule["pattern"])
        exc = [re.compile(e) for e in rule.get("exceptions", []) or []]
        for g in groups:
            for m in pat.finditer(g.text):
                window = g.text[max(0, m.start() - 6): m.end() + 8]
                if any(e.search(window) for e in exc):
                    continue
                key = (rule["id"], squash(m.group(0)), squash(_snippet(g.block_at(m.start()), 30)))
                if key in seen:
                    continue
                seen.add(key)
                blk = g.block_at(m.start())
                img, bb = _loc(blk)
                cat = _CATEGORY_KO.get(rule.get("category", ""), rule.get("category", ""))
                findings.append(Finding(
                    rule_id=rule["id"], category="prohibited", severity=rule.get("severity", "medium"),
                    title=f"{cat} 표현 의심: “{m.group(0)}”",
                    detail=f"{rule.get('note', '')}  | 문맥: {_snippet(blk)}",
                    page=page.page_id, matched_text=m.group(0), image=img, bbox=bb,
                    basis=rule.get("basis", ""), query=f"{m.group(0)} {rule.get('note', '')}"))
    return _dedupe(findings)


def _dedupe(findings: list) -> list:
    """같은 페이지에서 같은 룰·같은 문구는 하나만 (위치 정보가 있는 것 우선)."""
    best: dict = {}
    for f in findings:
        k = (f.rule_id, f.page, squash(f.matched_text), f.category)
        cur = best.get(k)
        if cur is None or (cur.bbox is None and f.bbox is not None):
            best[k] = f
    return list(best.values())


# ----------------------------------------------------------------------------
# 3) 수치 대조
# ----------------------------------------------------------------------------
_MONEY_UNIT = {"억": 1e8, "천만": 1e7, "백만": 1e6, "만": 1e4, "천": 1e3, "백": 1e2}
_MONEY_RE = re.compile(
    r"((?:\d[\d,]*(?:\.\d+)?(?:억|천만|백만|만|천|백))+)(\d[\d,]*)?(원)?|(\d[\d,]*)(원)"
)
_UNIT_PART = re.compile(r"(\d[\d,]*(?:\.\d+)?)(억|천만|백만|만|천|백)")
_NOT_MONEY_FOLLOW = re.compile(r"^(명|건|개|회|배|세|년|부|가지|곳|위|일|%|월|주)")
_AGE_RE = re.compile(r"(\d{1,3})(?:[~∼～\-–](\d{1,3}))?세")
_YEAR_RE = re.compile(r"(\d{1,2})년")
_DAY_RE = re.compile(r"(\d{1,3})일")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")


@dataclass
class NumMention:
    unit: str                # 만원 / 세 / 년 / 일 / %
    values: list             # 값 1개 또는 범위 [lo, hi]
    raw: str
    start: int
    end: int


_DOT_THOUSANDS = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{3})(?=(?:억|천만|백만|만|천|백|원))")


def extract_numbers(text: str) -> list:
    out = []
    # OCR 이 천 단위 쉼표(1,000)를 마침표(1.000)로 읽는 경우가 흔하다. 소수점 뒤가 정확히 3자리인 금액은 쉼표로 보정.
    money_text = _DOT_THOUSANDS.sub(r"\1,\2", text)
    for m in _MONEY_RE.finditer(money_text):
        if m.group(1):
            won = sum(float(a.replace(",", "")) * _MONEY_UNIT[u] for a, u in _UNIT_PART.findall(m.group(1)))
            if m.group(2):
                won += float(m.group(2).replace(",", ""))
            has_won = bool(m.group(3))
            if not has_won and _NOT_MONEY_FOLLOW.match(money_text[m.end():m.end() + 2]):
                continue
        else:
            won = float(m.group(4).replace(",", ""))
        out.append(NumMention("만원", [won / 1e4], m.group(0), m.start(), m.end()))
    for m in _AGE_RE.finditer(text):
        vals = [float(m.group(1))] + ([float(m.group(2))] if m.group(2) else [])
        out.append(NumMention("세", sorted(vals), m.group(0), m.start(), m.end()))
    for m in _YEAR_RE.finditer(text):
        out.append(NumMention("년", [float(m.group(1))], m.group(0), m.start(), m.end()))
    for m in _DAY_RE.finditer(text):
        out.append(NumMention("일", [float(m.group(1))], m.group(0), m.start(), m.end()))
    for m in _PCT_RE.finditer(text):
        out.append(NumMention("%", [float(m.group(1))], m.group(0), m.start(), m.end()))
    return out


def detect_products(pages: list, master: dict, forced_id: Optional[str]) -> list:
    prods = master.get("products", [])
    if forced_id:
        return [p for p in prods if p["product_id"] == forced_id]
    whole = "".join(g.text for p in pages for g in page_groups(p))
    found = []
    for p in prods:
        kws = [squash(k) for k in p.get("keywords", [])] + [squash(p.get("name", ""))]
        if any(k and k in whole for k in kws):
            found.append(p)
    return found


def _fact_aliases(fact: dict) -> list:
    al = [squash(a) for a in fact.get("aliases", [])]
    al.append(squash(fact["key"]))
    return [a for a in al if a]


def _fact_accepts(fact: dict, values: list) -> bool:
    if "allowed" in fact:
        return all(any(abs(v - a) < 1e-9 for a in fact["allowed"]) for v in values)
    lo = fact.get("min", float("-inf"))
    hi = fact.get("max", float("inf"))
    return all(lo <= v <= hi for v in values)


def _fact_expect_text(fact: dict) -> str:
    u = fact.get("unit", "")
    if "allowed" in fact:
        return "/".join(f"{a:g}{u}" for a in fact["allowed"])
    lo, hi = fact.get("min"), fact.get("max")
    if lo is not None and hi is not None:
        return f"{lo:g}~{hi:g}{u}"
    if hi is not None:
        return f"{hi:g}{u} 이하"
    if lo is not None:
        return f"{lo:g}{u} 이상"
    return "-"


def check_numeric(page: AdPage, groups: list, products: list, rules: dict) -> list:
    cfg = rules.get("numeric_check", {})
    if not cfg.get("enabled", True) or not products:
        return []
    findings = []
    CTX_BEFORE, CTX_AFTER = 16, 8
    for g in groups:
        for nm in extract_numbers(g.text):
            # 문맥은 "같은 줄(블록)" 안으로 제한한다. 다음 줄의 항목명이 앞 줄 숫자에 잘못 붙는 것을 방지.
            bi = g.owner[nm.start] if nm.start < len(g.owner) else None
            if bi is None:
                continue
            bstart = g.owner.index(bi)
            bend = bstart + len(squash(g.blocks[bi].text))
            ctx_b = g.text[max(bstart, nm.start - CTX_BEFORE): nm.start]
            ctx_a = g.text[nm.end: min(bend, nm.end + CTX_AFTER)]
            prev_tail = ""
            if bi > 0:  # 항목명이 바로 윗줄에 있는 레이아웃 대비
                prev_tail = squash(g.blocks[bi - 1].text)[-CTX_BEFORE:]

            def find_cands(cb, ca):
                found = []
                for prod in products:
                    for fact in prod.get("facts", []):
                        if fact.get("unit") != nm.unit:
                            continue
                        best = None  # (-별칭 길이, 거리) : 더 구체적인(긴) 별칭, 더 가까운 것 우선
                        for al in _fact_aliases(fact):
                            i = cb.rfind(al)
                            if i >= 0:
                                cand = (-len(al), len(cb) - (i + len(al)))
                                best = cand if best is None else min(best, cand)
                            j = ca.find(al)
                            if j >= 0:
                                cand = (-len(al), j)
                                best = cand if best is None else min(best, cand)
                        if best is not None:
                            found.append((best, prod, fact))
                return found

            cands = find_cands(ctx_b, ctx_a)
            if not cands and prev_tail and len(ctx_b) < 4:
                cands = find_cands(prev_tail + ctx_b, ctx_a)
            blk = g.block_at(nm.start)
            img, bb = _loc(blk)
            if cands:
                cands.sort(key=lambda t: t[0])
                nearest_key = cands[0][2]["key"]
                same = [(p, f) for d, p, f in cands if f["key"] == nearest_key]
                ok = any(_fact_accepts(f, nm.values) for p, f in same)
                exp = ", ".join(f"{p['name']}: {_fact_expect_text(f)}" for p, f in same)
                if ok:
                    findings.append(Finding(
                        rule_id=f"NUM-{nearest_key}", category="numeric", severity="info", status="ok",
                        title=f"수치 일치: {nearest_key} {nm.raw}",
                        detail=f"상품 마스터와 일치 ({exp})  | 문맥: {_snippet(blk)}",
                        page=page.page_id, matched_text=nm.raw, image=img, bbox=bb))
                else:
                    desc = same[0][1].get("description", nearest_key)
                    # 같은 단위의 '다른 항목' 기준에는 맞는 값이면, 숫자가 아니라 항목명(예: 소액암) 인식 오류일 수 있다
                    others = sorted({f["key"] for prod in products for f in prod.get("facts", [])
                                     if f.get("unit") == nm.unit and f["key"] != nearest_key and _fact_accepts(f, nm.values)})
                    hint = (f" ※ 이 값은 다른 항목({', '.join(others)}) 기준과는 일치합니다 — 항목명 OCR 오인식 여부를 원본에서 확인하세요."
                            if others else "")
                    findings.append(Finding(
                        rule_id=f"NUM-{nearest_key}", category="numeric",
                        severity="medium" if others else "high",
                        title=f"수치 불일치 의심: {nearest_key} {nm.raw}",
                        detail=f"광고 표기 {nm.raw} ↔ 상품 마스터 기준 [{exp}] ({desc}). "
                               f"OCR 숫자 오인식 가능성도 함께 확인하세요.{hint}  | 문맥: {_snippet(blk)}",
                        page=page.page_id, matched_text=nm.raw, image=img, bbox=bb,
                        query=f"{nearest_key} {desc}"))
            elif nm.unit == "만원" and cfg.get("flag_unmatched_money", True):
                findings.append(Finding(
                    rule_id="NUM-UNMATCHED-MONEY", category="numeric", severity="low",
                    title=f"금액 표기 확인 필요: {nm.raw}",
                    detail=f"마스터에 대응 항목이 없는 금액입니다. 보장금액·보험료 등이 약관/기초서류와 일치하는지 확인하세요.  | 문맥: {_snippet(blk)}",
                    page=page.page_id, matched_text=nm.raw, image=img, bbox=bb,
                    query="보험금 보장금액 보험료 표기"))
    return _dedupe_numeric(findings)


def _dedupe_numeric(findings: list) -> list:
    best: dict = {}
    for f in findings:
        k = (f.rule_id, f.page, squash(f.matched_text))
        cur = best.get(k)
        if cur is None or (cur.bbox is None and f.bbox is not None):
            best[k] = f
    return list(best.values())


# ----------------------------------------------------------------------------
# 4) 시각 점검 (글자 크기)
# ----------------------------------------------------------------------------
def _image_height(path: str) -> Optional[int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.height
    except Exception:
        return None


def check_visual(page: AdPage, groups: list, rules: dict) -> list:
    cfg = rules.get("visual_check", {})
    if not cfg.get("enabled", True):
        return []
    ratio_thr = cfg.get("min_disclaimer_height_ratio", 0.12)
    min_pt = cfg.get("min_disclaimer_pt")
    kws = [squash(k) for k in cfg.get("disclaimer_keywords", [])]
    findings = []

    def is_disclaimer(b: TextBlock) -> bool:
        s = squash(b.text)
        return any(k in s for k in kws)

    # OCR: 같은 이미지의 모든 변형을 합쳐서 판단 (큰 제목은 page, 작은 각주는 bands 에서 잡히기 때문)
    by_image: dict = {}
    for b in page.blocks:
        if b.source == "ocr":
            by_image.setdefault(b.image, []).append(b)
    for image, blks in by_image.items():
        heights = [b.height_px for b in blks if b.height_px and b.conf >= 60 and len(squash(b.text)) >= 2
                   and b.variant != "bands"]
        if len(heights) < 3:
            continue
        head = max(heights)
        for b in blks:
            if not b.height_px or not is_disclaimer(b) or b.conf < 40:
                continue
            ratio = b.height_px / head
            if ratio < ratio_thr:
                img, bb = _loc(b)
                findings.append(Finding(
                    rule_id="VIS-001", category="visual", severity="medium",
                    title="유의·단서 문구 글자가 매우 작음",
                    detail=f"가장 큰 글자 대비 약 {ratio:.0%} (기준 {ratio_thr:.0%} 미만, 글자 높이 약 {b.height_px:.0f}px / 최대 {head:.0f}px). "
                           f"규정상 글자 크기 기준에 맞는지 확인  | 문구: {_snippet(b)}",
                    page=page.page_id, matched_text=_snippet(b, 40), image=img, bbox=bb,
                    basis="rules.yaml visual_check (사내 규정 기준으로 조정 필요)",
                    query="유의사항 글자 크기 표기 불리한 내용"))

    for g in groups:
        if g.key[0] != "native":
            continue
        sizes = [b.font_pt for b in g.blocks if b.font_pt]
        head = max(sizes) if sizes else None
        for b in g.blocks:
            if not b.font_pt or not is_disclaimer(b):
                continue
            low_ratio = head and (b.font_pt / head) < ratio_thr
            low_abs = min_pt is not None and b.font_pt < min_pt
            if low_ratio or low_abs:
                why = []
                if low_ratio:
                    why.append(f"최대 글자({head:g}pt) 대비 {b.font_pt / head:.0%}")
                if low_abs:
                    why.append(f"{b.font_pt:g}pt < 기준 {min_pt:g}pt")
                findings.append(Finding(
                    rule_id="VIS-002", category="visual", severity="medium",
                    title="유의·단서 문구 글자 크기 작음 (PPT 텍스트)",
                    detail=" / ".join(why) + f"  | 문구: {_snippet(b)}",
                    page=page.page_id, matched_text=_snippet(b, 40),
                    basis="rules.yaml visual_check (사내 규정 기준으로 조정 필요)",
                    query="유의사항 글자 크기 표기 불리한 내용"))
    return _collapse_overlapping(findings)


def _box_iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua else 0.0


def _collapse_overlapping(findings: list) -> list:
    """같은 위치에 대해 OCR 변형별로 중복된 결과를 하나로 (글자 수가 많은 쪽 유지)."""
    kept: list = []
    for f in sorted(findings, key=lambda x: -len(x.matched_text)):
        dup = False
        for k in kept:
            if f.bbox and k.bbox and f.image == k.image and f.rule_id == k.rule_id and _box_iou(f.bbox, k.bbox) > 0.3:
                dup = True
                break
            if not f.bbox and not k.bbox and f.rule_id == k.rule_id and squash(f.matched_text) == squash(k.matched_text):
                dup = True
                break
        if not dup:
            kept.append(f)
    return kept


# ----------------------------------------------------------------------------
# 5) OCR 품질
# ----------------------------------------------------------------------------
def check_ocr_quality(page: AdPage, groups: list) -> list:
    findings = []
    all_ocr = [b for b in page.blocks if b.source == "ocr"]
    # 신뢰도는 띠(bands) 변형의 잘린 조각을 제외하고 계산 (잘린 제목 조각이 평균을 깎음)
    ocr_blocks = [b for b in all_ocr if b.variant != "bands"] or all_ocr
    native_blocks = [b for b in page.blocks if b.source == "native"]
    if not ocr_blocks and not native_blocks:
        findings.append(Finding(
            rule_id="OCR-000", category="ocr_quality", severity="medium",
            title="텍스트를 전혀 추출하지 못함",
            detail="OCR 결과가 비어 있습니다. 해상도·대비·글꼴 문제이거나 텍스트가 없는 이미지일 수 있어 육안 검토가 필요합니다.",
            page=page.page_id))
    elif ocr_blocks:
        mean_conf = sum(b.conf for b in ocr_blocks) / len(ocr_blocks)
        if mean_conf < 60:
            findings.append(Finding(
                rule_id="OCR-001", category="ocr_quality", severity="medium",
                title=f"OCR 평균 신뢰도 낮음 ({mean_conf:.0f})",
                detail="이 페이지의 점검 결과(특히 누락 판정)는 신뢰하기 어렵습니다. 고해상도 원본 사용 또는 육안 검토를 권장합니다.",
                page=page.page_id))
    seen = set()
    good = [o for o in all_ocr if o.conf >= 80 and o.bbox]

    def covered(b) -> bool:
        if not b.bbox:
            return False
        bx0, by0, bx1, by1 = b.bbox
        area = max(1.0, (bx1 - bx0) * (by1 - by0))
        for o in good:
            ix0, iy0 = max(bx0, o.bbox[0]), max(by0, o.bbox[1])
            ix1, iy1 = min(bx1, o.bbox[2]), min(by1, o.bbox[3])
            if max(0, ix1 - ix0) * max(0, iy1 - iy0) / area >= 0.5:
                return True
        return False

    for b in ocr_blocks:
        if re.search(r"\d", b.text) and b.conf < 70 and not covered(b):
            k = squash(b.text)
            if k in seen:
                continue
            seen.add(k)
            img, bb = _loc(b)
            findings.append(Finding(
                rule_id="OCR-002", category="ocr_quality", severity="low",
                title="숫자 포함 문구의 OCR 신뢰도 낮음",
                detail=f"숫자 한 글자 오인식이 판정을 바꿀 수 있습니다. 원본 대조 필요  | 인식: {_snippet(b)} (신뢰도 {b.conf:.0f})",
                page=page.page_id, matched_text=_snippet(b, 40), image=img, bbox=bb))
    for w in page.warnings:
        findings.append(Finding(
            rule_id="SYS-WARN", category="ocr_quality", severity="info", status="info",
            title="처리 경고", detail=w, page=page.page_id))
    return findings


# ----------------------------------------------------------------------------
# 파일 단위 실행
# ----------------------------------------------------------------------------
@dataclass
class FileResult:
    file: str
    pages: list
    findings: list
    products: list
    product_types: list
    skipped_rules: list


def check_file(pages: list, rules: dict, master: dict, ref_index=None,
               product_id: Optional[str] = None, product_types: Optional[list] = None,
               related_k: int = 3) -> FileResult:
    products = detect_products(pages, master, product_id)
    types = set(product_types or [])
    for p in products:
        types |= set(p.get("product_type", []))
    types_known = bool(types)

    findings, skipped = check_required(pages, rules, types, types_known)
    for page in pages:
        groups = page_groups(page)
        findings += check_prohibited(page, groups, rules)
        findings += check_numeric(page, groups, products, rules)
        findings += check_visual(page, groups, rules)
        findings += check_ocr_quality(page, groups)

    if not products and master.get("products"):
        findings.append(Finding(
            rule_id="SYS-PRODUCT", category="numeric", severity="info", status="info",
            title="상품 식별 실패 — 수치 대조 생략",
            detail="광고 문구에서 상품 마스터의 키워드를 찾지 못했습니다. --product <product_id> 로 상품을 지정하세요.",
            page=pages[0].file if pages else ""))

    if ref_index is not None:
        for f in findings:
            if f.status == "review" and f.category in ("required", "prohibited", "numeric", "visual"):
                q = f.query or f"{f.matched_text} {f.title}"
                f.related = ref_index.search(q, k=related_k, min_score=3.0)

    findings.sort(key=lambda f: (f.status != "review", ["high", "medium", "low", "info"].index(f.severity)
                                 if f.severity in ("high", "medium", "low", "info") else 9))
    return FileResult(file=pages[0].file if pages else "", pages=pages, findings=findings,
                      products=[p["product_id"] for p in products], product_types=sorted(types),
                      skipped_rules=skipped)
