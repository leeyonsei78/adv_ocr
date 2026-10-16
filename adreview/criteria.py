"""검수 기준(룰·점검표·상품 마스터)의 로드·검증·저장·이력 관리, 그리고 리포트에 표시할 '적용 기준' 요약.

검수 결과가 어느 기준으로 만들어졌는지 사용자가 알 수 있게 하는 것이 목적이다.
  - 기준 버전 = 세 파일 내용의 해시(앞 8자리). 기준을 고치면 버전이 바뀐다.
  - 기준을 저장할 때마다 이전 파일을 config/history/ 에 백업하고 변경 메모를 남긴다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# 키 -> (파일명, 화면 이름)
FILES = {
    "rules": ("rules.yaml", "검수 룰 (필수 문구·금지 표현·수치/시각 점검)"),
    "checklist": ("checklist.yaml", "광고심의점검표"),
    "master": ("product_master.yaml", "상품 마스터 (수치 대조용)"),
}
SEVERITIES = ("high", "medium", "low")
CATEGORIES = ("exaggeration", "absolute", "comparison", "guarantee", "urgency", "benefit")
CHECKLIST_TYPES = ("elements", "reuse", "prohibited", "visual", "validity", "product_name",
                   "company", "derived", "manual", "na")


def path_of(key: str, config_dir: Optional[Path] = None) -> Path:
    return Path(config_dir or CONFIG_DIR) / FILES[key][0]


def read_text(key: str, config_dir: Optional[Path] = None) -> str:
    p = path_of(key, config_dir)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load(key: str, config_dir: Optional[Path] = None) -> dict:
    t = read_text(key, config_dir)
    return (yaml.safe_load(t) or {}) if t.strip() else {}


# ----------------------------------------------------------------------------
# 검증
# ----------------------------------------------------------------------------
_NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d+,\d*\})")


def _check_regex(label: str, pat: str, errs: list) -> None:
    """정규식 문법 + 위험 패턴 검사. 중첩 반복 `(a+)+` 같은 패턴은 특정 입력에서 검수가 멈출 수 있어(ReDoS) 거부한다."""
    if len(pat) > 500:
        errs.append(f"{label}: 정규식이 너무 깁니다(500자 이하).")
        return
    try:
        re.compile(pat)
    except re.error as e:
        errs.append(f"{label}: 정규식 오류 “{pat}” ({e})")
        return
    if _NESTED_QUANT.search(pat):
        errs.append(f"{label}: 중첩 반복 “(…+)+” 형태는 검수를 멈추게 할 수 있어 허용하지 않습니다 — “{pat}”")


def validate_rules(d: dict) -> list:
    errs: list = []
    if not isinstance(d, dict):
        return ["rules: 최상위가 매핑(사전)이어야 합니다."]
    seen = set()
    for sec, need in (("required_phrases", ("any_of", "all_of")), ("prohibited_expressions", ("pattern",))):
        items = d.get(sec) or []
        if not isinstance(items, list):
            errs.append(f"{sec}: 목록이어야 합니다.")
            continue
        for i, r in enumerate(items, 1):
            if not isinstance(r, dict) or not r.get("id"):
                errs.append(f"{sec} #{i}: id 가 필요합니다.")
                continue
            rid = str(r["id"])
            if rid in seen:
                errs.append(f"{rid}: id 가 중복되었습니다.")
            seen.add(rid)
            if r.get("severity", "medium") not in SEVERITIES:
                errs.append(f"{rid}: severity 는 {'/'.join(SEVERITIES)} 중 하나여야 합니다.")
            if not any(r.get(k) for k in need):
                errs.append(f"{rid}: {' 또는 '.join(need)} 가 비어 있습니다.")
            for k in ("any_of", "all_of", "exceptions", "weak_any_of"):
                v = r.get(k) or []
                if not isinstance(v, list):
                    errs.append(f"{rid}: {k} 는 목록이어야 합니다.")
                    continue
                for p in v:
                    _check_regex(f"{rid}.{k}", str(p), errs)
            for k in ("pattern", "downgrade_if"):
                if r.get(k):
                    _check_regex(f"{rid}.{k}", str(r[k]), errs)
    return errs


_REGEX_KEYS = {"any_of", "when_any", "patterns", "company_regex", "agency_regex", "ranking_regex"}


def _walk_regex(label: str, o, errs: list, key: Optional[str] = None) -> None:
    """점검표 항목 안의 정규식 필드를 모두 컴파일해 본다."""
    if isinstance(o, dict):
        for k, v in o.items():
            _walk_regex(label, v, errs, k)
    elif isinstance(o, list):
        for v in o:
            _walk_regex(label, v, errs, key)
    elif isinstance(o, str) and key in _REGEX_KEYS:
        _check_regex(label, o, errs)


def validate_checklist(d: dict) -> list:
    errs: list = []
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return ["checklist: items 목록이 필요합니다."]
    nums = set()
    for i, it in enumerate(d["items"], 1):
        if not isinstance(it, dict):
            errs.append(f"items #{i}: 항목이 매핑이 아닙니다.")
            continue
        num = it.get("num")
        if num in (None, ""):
            errs.append(f"items #{i}: num(번호)이 필요합니다.")
        elif str(num) in nums:
            errs.append(f"{num}: 번호가 중복되었습니다.")
        nums.add(str(num))
        for k in ("group", "title", "type"):
            if not it.get(k):
                errs.append(f"{num}: {k} 가 비어 있습니다.")
        if it.get("type") and it["type"] not in CHECKLIST_TYPES:
            errs.append(f"{num}: type '{it['type']}' 은(는) 지원하지 않습니다.")
        _walk_regex(str(num), it, errs)
    return errs


def validate_master(d: dict) -> list:
    errs: list = []
    if not isinstance(d, dict):
        return ["master: 최상위가 매핑이어야 합니다."]
    ids = set()
    for i, p in enumerate(d.get("products") or [], 1):
        if not isinstance(p, dict) or not p.get("product_id"):
            errs.append(f"products #{i}: product_id 가 필요합니다.")
            continue
        if p["product_id"] in ids:
            errs.append(f"{p['product_id']}: product_id 가 중복되었습니다.")
        ids.add(p["product_id"])
    return errs


VALIDATORS = {"rules": validate_rules, "checklist": validate_checklist, "master": validate_master}


def validate_text(key: str, text: str) -> tuple:
    """(파싱 결과, 오류 목록). YAML 문법 → 구조 검증 순."""
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        return None, [f"YAML 문법 오류: {e}"]
    return d, VALIDATORS[key](d)


# ----------------------------------------------------------------------------
# 저장 · 이력
# ----------------------------------------------------------------------------
def history_dir(config_dir: Optional[Path] = None) -> Path:
    return Path(config_dir or CONFIG_DIR) / "history"


def save(key: str, text: str, note: str = "", user: str = "", config_dir: Optional[Path] = None) -> dict:
    """검증을 통과한 기준만 저장한다. 기존 파일은 history/ 로 백업하고 변경 메모를 남긴다."""
    d, errs = validate_text(key, text)
    if errs:
        raise ValueError("\n".join(errs))
    cfg = Path(config_dir or CONFIG_DIR)
    cfg.mkdir(parents=True, exist_ok=True)
    p = path_of(key, cfg)
    h = history_dir(cfg)
    h.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if p.exists():
        shutil.copy2(p, h / f"{p.stem}.{stamp}{p.suffix}")
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(p)
    entry = {"time": dt.datetime.now().isoformat(timespec="seconds"), "file": p.name,
             "note": note.strip(), "user": user.strip(), "backup": f"{p.stem}.{stamp}{p.suffix}"}
    with (h / "changes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_history(key: Optional[str] = None, limit: int = 30, config_dir: Optional[Path] = None) -> list:
    f = history_dir(config_dir) / "changes.jsonl"
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    if key:
        rows = [r for r in rows if r.get("file") == FILES[key][0]]
    return rows[-limit:][::-1]


def read_backup(name: str, config_dir: Optional[Path] = None) -> str:
    """history/ 안의 백업 파일 내용 (경로 탈출 방지)."""
    if not re.fullmatch(r"[\w.\-]+\.ya?ml", name):
        raise ValueError("잘못된 파일 이름")
    p = history_dir(config_dir) / name
    return p.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# 적용 기준 요약 (리포트·화면에 표시)
# ----------------------------------------------------------------------------
def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _pats(r: dict) -> list:
    out = []
    for k in ("any_of", "all_of"):
        out += [str(x) for x in (r.get(k) or [])]
    if r.get("pattern"):
        out.append(str(r["pattern"]))
    return out


def describe(rules: dict, checklist: dict, master: dict, paths: Optional[dict] = None,
             config_dir: Optional[Path] = None) -> dict:
    """리포트에 싣는 '이번 검수에 적용된 기준' 요약.
    paths 에 {'rules': 경로, ...} 를 주면 그 파일의 해시·수정시각을 쓰고, 없으면 config 폴더를 쓴다."""
    files, combo = [], ""
    for key, (fname, label) in FILES.items():
        p = Path(paths[key]) if paths and paths.get(key) else path_of(key, config_dir)
        if p and p.exists():
            txt = p.read_text(encoding="utf-8")
            sha = _sha(txt)
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            files.append({"key": key, "label": label, "file": p.name, "sha": sha, "modified": mtime})
            combo += sha
        else:
            files.append({"key": key, "label": label, "file": fname, "sha": "-", "modified": "-"})
    last = list_history(limit=1, config_dir=config_dir)
    rules = rules or {}
    req = [{"id": r.get("id"), "name": r.get("name"), "severity": r.get("severity", "medium"),
            "enabled": r.get("enabled", True) is not False, "applies_to": r.get("applies_to") or [],
            "patterns": _pats(r), "basis": r.get("basis", "")} for r in rules.get("required_phrases", []) or []]
    ban = [{"id": r.get("id"), "name": r.get("note", ""), "category": r.get("category", ""),
            "severity": r.get("severity", "medium"), "enabled": r.get("enabled", True) is not False,
            "patterns": _pats(r), "exceptions": r.get("exceptions") or [], "basis": r.get("basis", "")}
           for r in rules.get("prohibited_expressions", []) or []]
    chk = [{"num": it.get("num"), "group": it.get("group"), "title": it.get("title"), "type": it.get("type"),
            "enabled": it.get("enabled", True) is not False, "basis": it.get("basis", "")}
           for it in (checklist or {}).get("items", []) or []]
    prods = [{"id": p.get("product_id"), "name": p.get("name"), "facts": len(p.get("facts") or [])}
             for p in (master or {}).get("products", []) or []]
    vis = (rules.get("visual_check") or {})
    return {
        "version": _sha(combo) if combo else "-",
        "files": files,
        "last_change": last[0] if last else None,
        "required": req, "prohibited": ban, "checklist": chk, "products": prods,
        "visual": {"enabled": vis.get("enabled", True), "min_disclaimer_height_ratio": vis.get("min_disclaimer_height_ratio"),
                   "min_disclaimer_pt": vis.get("min_disclaimer_pt")},
        "counts": {
            "required": sum(1 for r in req if r["enabled"]), "prohibited": sum(1 for r in ban if r["enabled"]),
            "checklist": sum(1 for c in chk if c["enabled"]), "products": len(prods),
            "disabled": sum(1 for r in req + ban + chk if not r["enabled"]),
        },
    }
