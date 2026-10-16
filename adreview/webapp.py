"""웹 화면: PPT/이미지를 올리면 검수하고, 검수 기준(룰·점검표·상품 마스터)을 화면에서 수정한다.

  python -m adreview web [--host 127.0.0.1] [--port 8080]

  · 인터넷 없이 동작한다(외부 CDN·폰트 미사용). Flask 만 있으면 된다.
  · 검수 결과(HTML/엑셀/JSON)에는 '이번에 적용된 기준 버전·룰 목록'이 함께 들어간다.
  · 기준을 저장하면 이전 파일이 config/history/ 에 백업되고 변경 메모가 남는다.
  · 기본은 127.0.0.1(본인 PC)에서만 열린다. 사내망에 공유할 때는 --password(검수자) / --admin-password(기준 수정) 로
    로그인을 켜고, 검수·기준 변경은 output/web/audit.log 에 기록된다. (https 는 사내 프록시 등으로 별도 구성)
"""
from __future__ import annotations

import datetime as dt
import difflib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import yaml
from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, send_from_directory, session

from . import criteria as C
from .extract import IMAGE_EXTS
from .runner import run_check

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_EXTS = set(IMAGE_EXTS) | {".pptx", ".pdf"}
MAX_UPLOAD = 300 * 1024 * 1024
PRODUCT_TYPE_LABELS = {"renewable": "갱신형", "savings": "저축성", "annuity": "연금", "whole_life": "종신"}


def _safe_name(name: str) -> str:
    base = Path(name or "file").name
    base = re.sub(r"[^\w.\-가-힣]+", "_", base).strip("._") or "file"
    return base[:120]


# ----------------------------------------------------------------------------
# 화면 템플릿
# ----------------------------------------------------------------------------
BASE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} — 광고 1차 점검</title>
<style>
:root{--bg:#f6f7f9;--fg:#1f2430;--mut:#667085;--line:#d9dde5;--card:#fff;--pri:#2457d6;--bad:#c62828;--ok:#1b7f3b;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e8ee;--mut:#9aa3b2;--line:#2c323d;--card:#1c2027;--pri:#6b9bff;--bad:#ff7b72;--ok:#56d364;--warn:#e3a008}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 'Noto Sans CJK KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif}
header{background:var(--card);border-bottom:1px solid var(--line);padding:0 20px;display:flex;align-items:center;gap:22px;flex-wrap:wrap}
header b{font-size:16px;padding:12px 0}nav a{display:inline-block;padding:14px 4px;margin-right:14px;color:var(--mut);text-decoration:none;border-bottom:2px solid transparent}
nav a.on{color:var(--fg);border-color:var(--pri)}main{max-width:1180px;margin:0 auto;padding:18px 20px 60px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:14px 0}
h2{font-size:18px;margin:6px 0 10px}h3{font-size:15px;margin:4px 0 8px}
button,.btn{background:var(--pri);color:#fff;border:0;border-radius:6px;padding:8px 16px;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button.sec,.btn.sec{background:transparent;color:var(--fg);border:1px solid var(--line)}button.del{background:transparent;color:var(--bad);border:1px solid var(--line);padding:4px 10px}
button:disabled{opacity:.5;cursor:default}
input[type=text],input[type=date],select,textarea{width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit}
textarea{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;min-height:70px}
label{display:block;font-size:12px;color:var(--mut);margin:8px 0 3px}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{color:var(--mut);font-weight:600;font-size:12px}
.row{display:grid;gap:10px}.c2{grid-template-columns:1fr 1fr}.c3{grid-template-columns:1fr 1fr 1fr}.c4{grid-template-columns:repeat(4,1fr)}
@media (max-width:760px){.c2,.c3,.c4{grid-template-columns:1fr}}
.pill{display:inline-block;border-radius:10px;padding:1px 9px;font-size:12px;border:1px solid var(--line);color:var(--mut)}
.pill.ver{background:var(--pri);color:#fff;border-color:var(--pri)}.pill.off{color:var(--warn);border-color:var(--warn)}
.mut{color:var(--mut)}.small{font-size:12px}.err{color:var(--bad);white-space:pre-wrap}.okmsg{color:var(--ok)}
.crit{border-left:4px solid var(--pri)}
.rule{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0;background:var(--card)}.rule.off{opacity:.6}
.drop{border:2px dashed var(--line);border-radius:10px;padding:26px;text-align:center;color:var(--mut)}.drop.hl{border-color:var(--pri);color:var(--fg)}
pre.log{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px;max-height:240px;overflow:auto;font-size:12px;white-space:pre-wrap}
iframe{width:100%;height:78vh;border:1px solid var(--line);border-radius:8px;background:#fff}
.diff{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;white-space:pre-wrap}.diff .a{background:#16a34a22}.diff .d{background:#dc262622}
</style></head><body>
<header><b>보험 광고 1차 점검</b><nav>
<a href="/" class="{{ 'on' if tab=='check' }}">검수</a>
<a href="/jobs" class="{{ 'on' if tab=='jobs' }}">검수 이력</a>
<a href="/criteria" class="{{ 'on' if tab=='criteria' }}">검수 기준 관리</a>
</nav><span class="mut small" style="margin-left:auto">{% if who %}{{ who }} ({{ role }}) · <a href="/logout">로그아웃</a> · {% endif %}1차 점검 보조 도구 — 최종 판단은 담당자</span></header>
<main>{{ body|safe }}</main>
<script>
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
function who(){return localStorage.getItem('adr_user')||''}
async function post(url,data){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});return r.json()}
</script></body></html>"""


def page(title: str, tab: str, body: str) -> str:
    return render_template_string(BASE, title=title, tab=tab, body=body,
                                  who=getattr(g, "who", ""), role=getattr(g, "role_ko", ""))


LOGIN = """<div class="card" style="max-width:420px;margin:60px auto"><h2>로그인</h2>
<form method="post"><label>이름 (검수·변경 이력에 기록됩니다)</label><input type="text" name="name" required maxlength="30" autofocus>
<label>비밀번호</label><input type="password" name="pw" required style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:7px 9px">
<p class="err">{err}</p><button type="submit">로그인</button></form></div>"""



def _crit_panel(c: dict, link: bool = True) -> str:
    e = lambda s: (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    cnt, last = c["counts"], c.get("last_change")
    lc = (f"최근 변경 {e(last['time'])} {e(last.get('user', ''))} — {e(last.get('note') or '(메모 없음)')}" if last
          else "변경 이력 없음 (기본 제공 기준)")
    files = " · ".join(f"{e(f['file'])} <span class='mut'>{e(f['sha'])}</span>" for f in c["files"])
    off = f" · <span class='pill off'>비활성 {cnt['disabled']}개 검수 제외</span>" if cnt["disabled"] else ""
    return (f"<div class='card crit'><h3>이번 검수에 적용되는 기준 &nbsp;<span class='pill ver'>버전 {e(c['version'])}</span></h3>"
            f"<div>필수 문구 <b>{cnt['required']}</b> · 금지/주의 표현 <b>{cnt['prohibited']}</b> · 점검표 <b>{cnt['checklist']}</b>항목 · "
            f"상품 마스터 <b>{cnt['products']}</b>개{off}</div>"
            f"<div class='small mut'>{lc}<br>{files}</div>"
            + ("<div style='margin-top:8px'><a class='btn sec' href='/criteria'>기준 보기·수정</a></div>" if link else "") + "</div>")


# ----------------------------------------------------------------------------
# 앱
# ----------------------------------------------------------------------------
class State:
    def __init__(self, engine_name: str, ocr_opts: Optional[dict], config_dir: Optional[Path] = None,
                 out_root: Optional[Path] = None, engine_factory=None,
                 password: str = "", admin_password: str = ""):
        self.engine_name, self.ocr_opts = engine_name, ocr_opts or {}
        self.password = password or os.environ.get("ADREVIEW_PASSWORD", "")
        self.admin_password = admin_password or os.environ.get("ADREVIEW_ADMIN_PASSWORD", "")
        self.fails: dict = {}
        self.config_dir = Path(config_dir or C.CONFIG_DIR)
        self.out_root = Path(out_root or ROOT / "output" / "web")
        self.out_root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.out_root / "audit.log"
        self.retention_days = int(os.environ.get("ADREVIEW_RETENTION_DAYS", "0") or 0)
        self.engine_factory = engine_factory
        self._engines: dict = {}
        self._elock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)      # OCR 은 무거워 한 번에 한 건씩
        self.jobs: dict = {}

    def engine(self, name: str):
        with self._elock:
            if name not in self._engines:
                if self.engine_factory:
                    self._engines[name] = self.engine_factory(name)
                else:
                    from .ocr import build_engine
                    self._engines[name] = build_engine(name, self.ocr_opts if name == self.engine_name else {})
            return self._engines[name]

    def cfg(self, key: str) -> Path:
        return C.path_of(key, self.config_dir)

    @property
    def auth(self) -> bool:
        return bool(self.password or self.admin_password)

    def secret(self) -> bytes:
        f = self.out_root / ".secret"          # 재시작해도 로그인이 풀리지 않도록 보관
        if not f.exists():
            f.write_text(secrets.token_hex(32))
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
        return f.read_text().encode()

    def purge_old(self) -> int:
        """보관기간(일)이 지난 검수 결과 폴더를 삭제한다. 0 이면 삭제하지 않는다. (감사 로그는 유지)"""
        if self.retention_days <= 0:
            return 0
        import shutil
        cutoff, n = time.time() - self.retention_days * 86400, 0
        for d in self.out_root.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", d.name) and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        return n

    def audit(self, who: str, role: str, action: str, detail: str = "") -> None:
        rec = {"time": dt.datetime.now().isoformat(timespec="seconds"), "ip": request.remote_addr, "user": who,
               "role": role, "action": action, "detail": detail[:300]}
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def create_app(state: State) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    S = state
    app.secret_key = S.secret()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    PUBLIC = {"login", "static"}
    app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(hours=8)
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("ADREVIEW_SECURE_COOKIE", "") == "1"   # https 프록시 뒤에서 1

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        if request.endpoint == "job_file":      # 결과 리포트: 스크립트·외부 연결 전부 차단 (OCR 문구가 섞여 있어도 실행되지 않게)
            resp.headers["Content-Security-Policy"] = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
                                                       "frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
            if request.path.endswith((".xlsx", ".json")):
                resp.headers["Content-Disposition"] = "attachment"
        else:
            resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; "
                                                       "script-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; "
                                                       "frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp

    @app.before_request
    def gate():
        role = session.get("role", "")
        g.who, g.role, g.role_ko = session.get("name", ""), role, {"admin": "관리자", "user": "검수자"}.get(role, "")
        if not S.auth:
            g.role, g.role_ko = "admin", ""
            return None
        if request.endpoint in PUBLIC:
            return None
        if not g.role:
            if request.path.startswith(("/api/", "/check")) or request.path.endswith("/status"):
                return jsonify(ok=False, error="로그인이 필요합니다."), 401
            return redirect("/login")
        if request.path.startswith("/api/criteria") and request.method == "POST":
            if S.admin_password and g.role != "admin":
                return jsonify(ok=False, error="검수 기준은 관리자만 수정할 수 있습니다."), 403
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not S.auth:
            return redirect("/")
        err = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            n, until = S.fails.get(ip, (0, 0))
            if until > time.time():
                err = "시도 횟수를 초과했습니다. 잠시 후 다시 시도하세요."
            else:
                pw, name = request.form.get("pw", ""), (request.form.get("name", "").strip() or "이름없음")[:30]
                role = ""
                if S.admin_password and hmac.compare_digest(pw.encode(), S.admin_password.encode()):
                    role = "admin"
                elif S.password and hmac.compare_digest(pw.encode(), S.password.encode()):
                    role = "user" if S.admin_password else "admin"      # 비밀번호가 하나뿐이면 모두 기준 수정 가능
                if role:
                    session.clear()
                    session.permanent = True
                    session.update(name=name, role=role)
                    S.fails.pop(ip, None)
                    S.audit(name, role, "login")
                    return redirect("/")
                n += 1
                S.fails[ip] = (n, time.time() + 60 if n >= 5 else 0)
                S.audit(name, "", "login_fail")
                err = "비밀번호가 올바르지 않습니다."
        g.who = g.role_ko = ""
        return page("로그인", "", LOGIN.format(err=err))

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect("/login" if S.auth else "/")

    def current_criteria() -> dict:
        return C.describe(C.load("rules", S.config_dir), C.load("checklist", S.config_dir),
                          C.load("master", S.config_dir), config_dir=S.config_dir)

    # ------------------------------------------------------------ 검수
    @app.get("/")
    def home():
        crit = current_criteria()
        master = C.load("master", S.config_dir)
        rules = C.load("rules", S.config_dir)
        types = sorted({t for r in rules.get("required_phrases", []) or [] for t in (r.get("applies_to") or [])} |
                       {t for p in master.get("products", []) or [] for t in (p.get("product_type") or [])})
        prods = "".join(f"<option value='{p['product_id']}'>{p.get('name', '')} ({p['product_id']})</option>"
                        for p in master.get("products", []) or [])
        tchk = "".join(f"<label style='display:inline-block;margin-right:14px;color:var(--fg)'><input type='checkbox' name='ptype' value='{t}'> "
                       f"{PRODUCT_TYPE_LABELS.get(t, t)}</label>" for t in types)
        body = _crit_panel(crit) + f"""
<div class="card"><h2>광고물 업로드</h2>
<form id="f" enctype="multipart/form-data">
<div class="drop" id="drop">PPTX · 이미지(PNG/JPG 등) · PDF 파일을 끌어다 놓거나 <a href="#" onclick="$('#files').click();return false">선택</a>하세요 (여러 개 가능)
<input type="file" id="files" name="files" multiple hidden accept=".pptx,.pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.gif"></div>
<div id="flist" class="small mut" style="margin:6px 0"></div>
<div class="row c4">
<div><label>OCR 엔진</label><select name="engine"><option value="paddle" {'selected' if S.engine_name == 'paddle' else ''}>PaddleOCR (기본·정확)</option><option value="tesseract" {'selected' if S.engine_name == 'tesseract' else ''}>Tesseract (경량)</option></select></div>
<div><label>상품 (모르면 자동 식별)</label><select name="product"><option value="">자동 식별</option>{prods}</select></div>
<div><label>유효기간 비교 기준일</label><input type="date" name="today" value="{dt.date.today().isoformat()}"></div>
<div><label>검수 요청자 (이력용)</label><input type="text" name="user" id="user" placeholder="이름"></div>
</div>
<label>상품군 (해당하는 것만 — 필수 문구 적용 범위가 달라집니다)</label><div>{tchk or '<span class="mut">정의된 상품군 없음</span>'}</div>
<div style="margin-top:14px"><button id="go" type="submit" disabled>검수 시작</button> <span id="msg" class="err"></span></div>
</form></div>
<script>
const inp=$('#files'),drop=$('#drop');let picked=[];
function show(){{$('#flist').textContent=picked.length?picked.map(f=>f.name).join(' · '):'';$('#go').disabled=!picked.length}}
inp.onchange=()=>{{picked=[...inp.files];show()}};
['dragover','dragenter'].forEach(e=>drop.addEventListener(e,ev=>{{ev.preventDefault();drop.classList.add('hl')}}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{{ev.preventDefault();drop.classList.remove('hl')}}));
drop.addEventListener('drop',ev=>{{picked=[...ev.dataTransfer.files];show()}});
$('#user').value=who();
$('#f').onsubmit=async ev=>{{ev.preventDefault();localStorage.setItem('adr_user',$('#user').value);
 const fd=new FormData();picked.forEach(f=>fd.append('files',f));
 for(const [k,v] of new FormData($('#f')).entries()) if(k!=='files') fd.append(k,v);
 $('#go').disabled=true;$('#msg').textContent='';
 const r=await fetch('/check',{{method:'POST',body:fd}});const j=await r.json();
 if(j.error){{$('#msg').textContent=j.error;$('#go').disabled=false}}else location=j.url}};
</script>"""
        return page("검수", "check", body)

    @app.post("/check")
    def start_check():
        files = request.files.getlist("files")
        if not files or not any(f.filename for f in files):
            return jsonify(error="파일을 선택하세요.")
        jid = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        jdir = S.out_root / jid
        up = jdir / "uploads"
        up.mkdir(parents=True)
        saved, names, bad = [], {}, []
        for i, f in enumerate(files, 1):
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_EXTS:
                bad.append(f.filename)
                continue
            p = up / f"{i:02d}_{_safe_name(f.filename)}"
            f.save(p)
            saved.append(str(p))
            names[str(p)] = Path(f.filename).name
        if not saved:
            return jsonify(error="지원하지 않는 형식입니다. (PPTX, PDF, PNG/JPG 등만 가능 — .ppt 는 .pptx 로 저장 후 올려 주세요)")
        eng = request.form.get("engine") or S.engine_name
        if eng not in ("paddle", "tesseract"):
            return jsonify(error="알 수 없는 OCR 엔진")
        today = None
        if request.form.get("today"):
            try:
                today = dt.date.fromisoformat(request.form["today"])
            except ValueError:
                return jsonify(error="기준일 형식이 잘못되었습니다.")
        types = request.form.getlist("ptype") or None
        form = {"ref": request.form.get("ref", ""), "product": request.form.get("product") or None}
        job = {"id": jid, "state": "queued", "log": [], "files": list(names.values()), "skipped": bad,
               "user": request.form.get("user", "")[:40], "created": dt.datetime.now().isoformat(timespec="seconds"),
               "engine": eng, "criteria": None, "n_review": {}, "errors": []}
        S.jobs[jid] = job
        if S.auth and g.who:
            job["user"] = g.who
        S.audit(job["user"] or g.who, g.role, "check", f"{jid}: {', '.join(job['files'])[:200]}")

        def work():
            job["state"] = "running"
            try:
                engine = S.engine(eng)
                r = run_check(saved, str(jdir / "out"), engine, str(S.cfg("rules")), str(S.cfg("master")),
                              str(S.cfg("checklist")), form["ref"] or str(ROOT / "output" / "ref_index.json"),
                              form["product"], types, today,
                              log=lambda m: job["log"].append(m), display_names=names)
                job.update(state="done" if r["ok"] else "failed", criteria=r["criteria"], n_review=r["n_review"], errors=r["errors"])
            except Exception as e:          # 엔진 로딩 실패 등
                job["log"].append(f"[오류] {e}")
                job["state"] = "failed"
            (jdir / "job.json").write_text(json.dumps({k: v for k, v in job.items() if k != "log"} | {"log": job["log"]},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
            for f in up.glob("*"):          # 업로드 원본은 검수 후 보관하지 않는다
                f.unlink(missing_ok=True)

        S.pool.submit(work)
        return jsonify(url=f"/job/{jid}")

    def load_job(jid: str) -> dict:
        if not re.fullmatch(r"[\w\-]+", jid):
            abort(404)
        if jid in S.jobs:
            return S.jobs[jid]
        f = S.out_root / jid / "job.json"
        if not f.exists():
            abort(404)
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/job/<jid>")
    def job_page(jid):
        j = load_job(jid)
        body = f"""<div class="card"><h2>검수 진행 <span class="pill" id="st">{j['state']}</span></h2>
<div class="small mut">{_esc(', '.join(j['files']))}</div><pre class="log" id="log"></pre>
<div id="links" style="display:none;margin-top:8px"><a class="btn" href="/job/{jid}/file/report.html" target="_blank">리포트 새 창</a>
<a class="btn sec" href="/job/{jid}/file/result.xlsx">엑셀 받기</a> <a class="btn sec" href="/job/{jid}/file/result.json">JSON 받기</a>
<a class="btn sec" href="/job/{jid}/file/criteria.json">적용 기준(JSON)</a></div></div>
<div id="crit"></div><div id="rep"></div>
<script>
const jid="{jid}";let shown=false;
async function tick(){{const j=await (await fetch('/job/'+jid+'/status')).json();
 $('#st').textContent={{queued:'대기 중',running:'검수 중',done:'완료',failed:'실패'}}[j.state]||j.state;
 $('#log').textContent=j.log.join('\\n');$('#log').scrollTop=1e9;
 if(j.state==='done'&&!shown){{shown=true;$('#links').style.display='block';$('#crit').innerHTML=j.crit_html;
   $('#rep').innerHTML='<iframe src="/job/'+jid+'/file/report.html"></iframe>'}}
 if(j.state==='queued'||j.state==='running')setTimeout(tick,1500)}}
tick();
</script>"""
        return page("검수 결과", "check", body)

    @app.get("/job/<jid>/status")
    def job_status(jid):
        j = load_job(jid)
        out = {"state": j["state"], "log": j["log"], "files": j["files"]}
        if j.get("criteria"):
            out["crit_html"] = _crit_panel(j["criteria"], link=False).replace(
                "이번 검수에 적용되는 기준", "이 결과에 적용된 기준")
        return jsonify(out)

    @app.get("/job/<jid>/file/<path:name>")
    def job_file(jid, name):
        load_job(jid)
        return send_from_directory((S.out_root / jid / "out").resolve(), name)

    @app.get("/jobs")
    def jobs():
        rows = []
        for f in sorted(S.out_root.glob("*/job.json"), reverse=True)[:60]:
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            c = j.get("criteria") or {}
            rows.append(f"<tr><td><a href='/job/{j['id']}'>{j['created'].replace('T', ' ')}</a></td><td>{_esc(', '.join(j['files'])[:90])}</td>"
                        f"<td>{_esc(j.get('user', ''))}</td><td>{_esc(j.get('engine', ''))}</td>"
                        f"<td>{('<span class=\"pill ver\">' + c['version'] + '</span>') if c else '-'}</td><td>{j['state']}</td></tr>")
        body = ("<div class='card'><h2>검수 이력</h2><table><tr><th>시각</th><th>파일</th><th>요청자</th><th>OCR</th><th>적용 기준 버전</th><th>상태</th></tr>"
                + ("".join(rows) or "<tr><td colspan=6 class='mut'>아직 검수 이력이 없습니다.</td></tr>") + "</table>"
                "<p class='small mut'>적용 기준 버전이 같으면 같은 기준으로 검수된 결과입니다. 업로드 원본 파일은 보관하지 않고 결과만 보관합니다.</p></div>")
        return page("검수 이력", "jobs", body)

    # ------------------------------------------------------------ 기준 관리
    @app.get("/criteria")
    def criteria_home():
        crit = current_criteria()
        tab = request.args.get("t", "rules")
        tabs = "".join(f"<a href='/criteria?t={k}' class='btn {'' if tab == k else 'sec'}' style='margin-right:6px'>{n}</a>"
                       for k, n in (("rules", "필수·금지 룰"), ("checklist", "광고심의점검표"), ("master", "상품 마스터"), ("history", "변경 이력")))
        body = _crit_panel(crit, link=False) + f"<div style='margin:10px 0'>{tabs}</div>"
        if tab == "rules":
            body += _rules_editor(C.load("rules", S.config_dir), C.read_text("rules", S.config_dir))
        elif tab == "checklist":
            body += _checklist_editor(C.load("checklist", S.config_dir), C.read_text("checklist", S.config_dir))
        elif tab == "master":
            body += _text_editor("master", C.read_text("master", S.config_dir),
                                 "상품별 확정 수치(가입연령·보험기간·보장금액 등). 광고 속 숫자와 대조합니다. YAML 형식입니다.")
        else:
            body += _history_view(S.config_dir)
        return page("검수 기준 관리", "criteria", body)

    def _save(key: str, text: str, d: dict):
        if S.auth and g.who:
            d["user"] = g.who                  # 로그인한 이름으로 변경자를 기록 (화면 입력값 무시)
        try:
            e = C.save(key, text, d.get("note", ""), d.get("user", ""), S.config_dir)
        except ValueError as ex:
            return jsonify(ok=False, error=str(ex))
        S.audit(d.get("user", ""), g.role, "criteria_save", f"{e['file']} {e.get('note', '')}")
        return jsonify(ok=True, version=current_criteria()["version"], entry=e)

    def _header_comment(key: str) -> str:
        head = []
        for line in C.read_text(key, S.config_dir).splitlines():
            if line.startswith("#") or not line.strip():
                head.append(line)
            else:
                break
        return "\n".join(head).rstrip() + "\n\n" if head else ""

    def _dump(key: str, d: dict) -> str:
        return _header_comment(key) + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)

    @app.post("/api/criteria/<key>/text")
    def api_text(key):
        if key not in C.FILES:
            abort(404)
        d = request.get_json(force=True)
        return _save(key, d.get("text", ""), d)

    @app.post("/api/criteria/rules/structured")
    def api_rules():
        d = request.get_json(force=True)
        rules = C.load("rules", S.config_dir)

        def clean(lst, list_keys):
            out = []
            for r in lst or []:
                r = {k: v for k, v in r.items() if v not in ("", None, [])}
                for k in list_keys:
                    if k in r and isinstance(r[k], str):
                        r[k] = [x for x in (s.strip() for s in r[k].splitlines()) if x]
                if r.get("enabled", True) is not False:
                    r.pop("enabled", None)
                out.append(r)
            return out
        rules["required_phrases"] = clean(d.get("required_phrases"), ["any_of", "all_of", "weak_any_of", "fuzzy", "applies_to"])
        rules["prohibited_expressions"] = clean(d.get("prohibited_expressions"), ["exceptions"])
        for r in rules["required_phrases"]:
            if isinstance(r.get("applies_to"), list):
                r["applies_to"] = [x for y in r["applies_to"] for x in re.split(r"[,\s]+", y) if x]
        vc = d.get("visual_check")
        if isinstance(vc, dict):
            cur = rules.setdefault("visual_check", {})
            for k in ("min_disclaimer_height_ratio", "min_disclaimer_pt"):
                if vc.get(k) not in ("", None):
                    try:
                        cur[k] = float(vc[k])
                    except ValueError:
                        return jsonify(ok=False, error=f"{k}: 숫자가 아닙니다.")
            if "enabled" in vc:
                cur["enabled"] = bool(vc["enabled"])
        return _save("rules", _dump("rules", rules), d)

    @app.post("/api/criteria/checklist/apply")
    def api_checklist():
        d = request.get_json(force=True)
        cl = C.load("checklist", S.config_dir)
        items = {str(i["num"]): i for i in cl.get("items", [])}
        for num, on in (d.get("enabled") or {}).items():
            if num in items:
                if on:
                    items[num].pop("enabled", None)
                else:
                    items[num]["enabled"] = False
        for num, txt in (d.get("items") or {}).items():
            try:
                new = yaml.safe_load(txt)
            except yaml.YAMLError as e:
                return jsonify(ok=False, error=f"{num}: YAML 문법 오류 {e}")
            if not isinstance(new, dict) or str(new.get("num")) != str(num):
                return jsonify(ok=False, error=f"{num}: 항목은 매핑이어야 하며 num 은 {num} 이어야 합니다.")
            items[num] = new
        cl["items"] = [items[str(i["num"])] for i in cl.get("items", [])]
        return _save("checklist", _dump("checklist", cl), d)

    @app.get("/api/criteria/checklist/item/<num>")
    def api_item(num):
        for i in C.load("checklist", S.config_dir).get("items", []):
            if str(i["num"]) == num:
                return jsonify(text=yaml.safe_dump(i, allow_unicode=True, sort_keys=False, width=1000))
        abort(404)

    @app.get("/criteria/diff")
    def criteria_diff():
        name = request.args.get("name", "")
        try:
            old = C.read_backup(name, S.config_dir)
        except Exception:
            abort(404)
        key = next((k for k, (fn, _) in C.FILES.items() if name.startswith(Path(fn).stem + ".")), None)
        if not key:
            abort(404)
        cur = C.read_text(key, S.config_dir)
        lines = []
        for l in difflib.unified_diff(old.splitlines(), cur.splitlines(), f"{name} (과거)", "현재", lineterm="", n=2):
            cls = "a" if l.startswith("+") and not l.startswith("+++") else "d" if l.startswith("-") and not l.startswith("---") else ""
            lines.append(f"<div class='{cls}'>{(l or ' ').replace('&', '&amp;').replace('<', '&lt;')}</div>")
        body = (f"<div class='card'><h2>{name} ↔ 현재</h2><div class='diff'>{''.join(lines) or '변경 없음'}</div>"
                f"<p><a class='btn sec' href='/criteria?t=history'>돌아가기</a></p></div>")
        return page("기준 비교", "criteria", body)

    @app.post("/api/criteria/restore")
    def api_restore():
        d = request.get_json(force=True)
        name = d.get("name", "")
        try:
            text = C.read_backup(name, S.config_dir)
        except Exception:
            return jsonify(ok=False, error="백업 파일을 찾을 수 없습니다.")
        key = next((k for k, (fn, _) in C.FILES.items() if name.startswith(Path(fn).stem + ".")), None)
        if not key:
            return jsonify(ok=False, error="알 수 없는 기준 파일입니다.")
        d["note"] = f"복원: {name}" + (f" — {d['note']}" if d.get("note") else "")
        return _save(key, text, d)

    return app


# ----------------------------------------------------------------------------
# 기준 관리 화면 조각
# ----------------------------------------------------------------------------
_SAVE_BAR = """<div class="card"><div class="row c3"><div><label>변경자</label><input type="text" id="who" placeholder="이름"></div>
<div style="grid-column:span 2"><label>변경 메모 (왜 바꾸는지 — 이력에 남습니다)</label><input type="text" id="note" placeholder="예: 심의규정 개정(2026.10) 반영"></div></div>
<div style="margin-top:10px"><button id="save">저장</button> <span id="res"></span></div>
<p class="small mut">저장하면 문법·정규식을 먼저 검사하고, 오류가 있으면 저장되지 않습니다. 이전 파일은 자동 백업되며 '변경 이력'에서 복원할 수 있습니다.
저장 즉시 이후 검수부터 새 기준이 적용되고 기준 버전이 바뀝니다.</p></div>
<script>$('#who').value=who();$('#who').onchange=()=>localStorage.setItem('adr_user',$('#who').value);
function report(j){$('#res').className=j.ok?'okmsg':'err';$('#res').textContent=j.ok?('저장됨 — 새 기준 버전 '+j.version):j.error;if(j.ok)setTimeout(()=>location.reload(),900)}</script>"""


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _text_editor(key: str, text: str, hint: str) -> str:
    return (f"<div class='card'><h2>{_esc(C.FILES[key][1])}</h2><p class='small mut'>{_esc(hint)}</p>"
            f"<textarea id='txt' style='min-height:60vh'>{_esc(text)}</textarea></div>{_SAVE_BAR}"
            f"<script>$('#save').onclick=async()=>report(await post('/api/criteria/{key}/text',{{text:$('#txt').value,note:$('#note').value,user:$('#who').value}}))</script>")


def _rules_editor(rules: dict, raw: str = "") -> str:
    data = json.dumps({"req": rules.get("required_phrases") or [], "ban": rules.get("prohibited_expressions") or [],
                       "vis": rules.get("visual_check") or {}}, ensure_ascii=False).replace("</", "<\\/")
    return """<div class="card"><h2>필수 문구 룰 <button class="sec" onclick="addR('req')">+ 추가</button></h2>
<p class="small mut">광고에 반드시 있어야 하는 문구입니다. 검출 패턴은 정규식이며 한 줄에 하나씩 쓰고, 하나라도 맞으면 충족입니다. 공백은 무시하고 비교합니다.</p><div id="req"></div></div>
<div class="card"><h2>금지·주의 표현 룰 <button class="sec" onclick="addR('ban')">+ 추가</button></h2>
<p class="small mut">검출되면 ‘검토 필요’로 표시합니다. 예외 패턴(정식 용어 등)이 근처에 있으면 제외하고, ‘근거 표기 패턴’이 같은 화면에 있으면 중요도를 낮음으로 낮춥니다.</p><div id="ban"></div></div>
<div class="card"><h2>글자 크기 점검</h2><div class="row c3">
<div><label>단서 문구 최소 높이 비율 (본문 최대 글자 대비)</label><input type="text" id="v_ratio"></div>
<div><label>PPT 최소 글자 크기(pt)</label><input type="text" id="v_pt"></div>
<div><label>사용</label><select id="v_on"><option value="true">사용</option><option value="false">끔</option></select></div></div></div>
""" + _SAVE_BAR + """<script>
const D=""" + data + """;
const L=a=>(a||[]).join('\\n'),SEV=['high','medium','low'],SEVK={high:'높음',medium:'중간',low:'낮음'},CAT=['exaggeration','absolute','comparison','guarantee','urgency','benefit'];
const CATK={exaggeration:'과장',absolute:'단정',comparison:'비교',guarantee:'보장·확정',urgency:'조급',benefit:'특별이익·경품'};
const opts=(a,k,v)=>a.map(x=>`<option value="${x}" ${x===v?'selected':''}>${k[x]||x}</option>`).join('');
const e=s=>String(s??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
function card(kind,r){const off=r.enabled===false;
 const f=(k,lab,rows)=>`<div><label>${lab}</label><textarea data-k="${k}" rows="${rows}">${e(Array.isArray(r[k])?L(r[k]):r[k])}</textarea></div>`;
 const t=(k,lab)=>`<div><label>${lab}</label><input type="text" data-k="${k}" value="${e(r[k])}"></div>`;
 return `<div class="rule ${off?'off':''}" data-kind="${kind}"><div class="row c4">${t('id','ID')}
 ${kind==='req'?t('name','이름'):`<div><label>분류</label><select data-k="category">${opts(CAT,CATK,r.category)}</select></div>`}
 <div><label>중요도</label><select data-k="severity">${opts(SEV,SEVK,r.severity||'medium')}</select></div>
 <div><label>적용</label><select data-k="enabled"><option value="true" ${off?'':'selected'}>적용</option><option value="false" ${off?'selected':''}>비활성(검수 제외)</option></select></div></div>
 ${kind==='req'?`<div class="row c2">${f('any_of','검출 패턴 — 하나라도 있으면 충족 (정규식, 한 줄에 하나)',3)}${f('all_of','모두 있어야 충족 (선택)',3)}</div>
   <div class="row c3">${f('weak_any_of','약한 패턴 — 번호 형식만 있으면 ‘불확실’ (선택)',2)}${f('fuzzy','유사 문구 탐색어 (OCR 오인식 대비, 선택)',2)}${f('applies_to','적용 상품군 (renewable, savings … 비우면 전체)',2)}</div>`
  :`<div class="row c2">${f('pattern','검출 패턴 (정규식 한 개, | 로 연결)',3)}${f('exceptions','예외 패턴 — 근처에 있으면 제외 (한 줄에 하나)',3)}</div>
   <div class="row c2">${t('downgrade_if','근거 표기 패턴 — 같은 화면에 있으면 중요도 낮음 (선택)')}${t('note','담당자에게 보일 설명')}</div>`}
 ${t('basis','근거 규정 (조항명)')}<div style="text-align:right;margin-top:6px"><button class="del" onclick="this.closest('.rule').remove()">삭제</button></div></div>`}
function draw(){['req','ban'].forEach(k=>$('#'+k).innerHTML=D[k].map(r=>card(k,r)).join(''));
 $('#v_ratio').value=D.vis.min_disclaimer_height_ratio??'';$('#v_pt').value=D.vis.min_disclaimer_pt??'';$('#v_on').value=String(D.vis.enabled!==false)}
function addR(k){D[k]=collect(k);D[k].push(k==='req'?{id:'REQ-'+String(D[k].length+1).padStart(3,'0'),severity:'medium'}:{id:'BAN-'+String(D[k].length+1).padStart(3,'0'),severity:'medium',category:'exaggeration'});draw()}
function collect(k){return $$('#'+k+' .rule').map(c=>{const r={};c.querySelectorAll('[data-k]').forEach(i=>{let v=i.value;if(i.dataset.k==='enabled')v=v==='true';r[i.dataset.k]=v});return r})}
$('#save').onclick=async()=>report(await post('/api/criteria/rules/structured',{required_phrases:collect('req'),prohibited_expressions:collect('ban'),
 visual_check:{min_disclaimer_height_ratio:$('#v_ratio').value,min_disclaimer_pt:$('#v_pt').value,enabled:$('#v_on').value==='true'},note:$('#note').value,user:$('#who').value}));
draw();
</script>
<div class="card"><details><summary>고급: rules.yaml 전체를 직접 편집 (주석 유지)</summary>
<textarea id="raw" style="min-height:50vh">""" + _esc(raw) + """</textarea>
<p><button class="sec" onclick="(async()=>report(await post('/api/criteria/rules/text',{text:$('#raw').value,note:$('#note').value,user:$('#who').value})))()">YAML 그대로 저장</button></p></details></div>"""


def _checklist_editor(cl: dict, raw: str = "") -> str:
    rows = []
    for i in cl.get("items", []) or []:
        off = i.get("enabled", True) is False
        rows.append(f"<tr><td>{_esc(i['num'])}</td><td>{_esc(i.get('group'))}</td><td>{_esc(i.get('title'))}"
                    f"<div class='small mut'>{_esc(i.get('basis', ''))}</div></td><td><span class='pill'>{_esc(i.get('type'))}</span></td>"
                    f"<td><input type='checkbox' class='en' data-n='{_esc(i['num'])}' {'' if off else 'checked'}></td>"
                    f"<td><button class='sec' onclick=\"edit('{_esc(i['num'])}')\">패턴 편집</button></td></tr>"
                    f"<tr id='ed{_esc(i['num'])}' style='display:none'><td colspan=6><textarea data-n='{_esc(i['num'])}' class='it' style='min-height:200px'></textarea></td></tr>")
    return ("<div class='card'><h2>광고심의점검표 항목</h2><p class='small mut'>체크를 해제하면 해당 항목은 검수에서 제외(‘해당 없음’)됩니다. "
            "‘패턴 편집’에서 항목의 판정 패턴·적용 조건(YAML)을 고칩니다. 패턴은 예시이므로 규정 원문에 맞게 검수해 사용하세요.</p>"
            "<table><tr><th>No.</th><th>구분</th><th>점검 항목 / 근거 규정</th><th>판정 방식</th><th>적용</th><th></th></tr>" + "".join(rows) + "</table></div>"
            + _SAVE_BAR + """<script>
async function edit(n){const r=$('#ed'+n);if(r.style.display==='none'){const t=r.querySelector('textarea');if(!t.value)t.value=(await (await fetch('/api/criteria/checklist/item/'+n)).json()).text;t.dataset.loaded=1;r.style.display=''}else r.style.display='none'}
$('#save').onclick=async()=>{const enabled={};$$('.en').forEach(c=>enabled[c.dataset.n]=c.checked);
 const items={};$$('textarea.it').forEach(t=>{if(t.dataset.loaded)items[t.dataset.n]=t.value});
 report(await post('/api/criteria/checklist/apply',{enabled,items,note:$('#note').value,user:$('#who').value}))}
</script>
<div class="card"><details><summary>고급: checklist.yaml 전체를 직접 편집 (주석 유지)</summary><textarea id="raw" style="min-height:50vh">""" + _esc(raw) + """</textarea>
<p><button class="sec" onclick="(async()=>report(await post('/api/criteria/checklist/text',{text:$('#raw').value,note:$('#note').value,user:$('#who').value})))()">YAML 그대로 저장</button></p></details></div>""")


def _history_view(config_dir) -> str:
    rows = []
    for r in C.list_history(config_dir=config_dir):
        rows.append(f"<tr><td>{_esc(r['time'].replace('T', ' '))}</td><td>{_esc(r['file'])}</td><td>{_esc(r.get('user'))}</td><td>{_esc(r.get('note'))}</td>"
                    f"<td><a class='btn sec' href='/criteria/diff?name={_esc(r['backup'])}'>변경 전과 비교</a> "
                    f"<button class='sec' onclick=\"restore('{_esc(r['backup'])}')\">이 시점 이전으로 복원</button></td></tr>")
    return ("<div class='card'><h2>변경 이력</h2><table><tr><th>시각</th><th>파일</th><th>변경자</th><th>메모</th><th></th></tr>"
            + ("".join(rows) or "<tr><td colspan=5 class='mut'>변경 이력이 없습니다.</td></tr>") + "</table></div>" + _SAVE_BAR +
            "<script>async function restore(n){if(!confirm(n+' 내용으로 되돌릴까요? (현재 내용도 백업됩니다)'))return;"
            "report(await post('/api/criteria/restore',{name:n,note:$('#note').value,user:$('#who').value}))}$('#save').style.display='none'</script>")


def serve(host: str = "127.0.0.1", port: int = 8080, engine: str = "paddle", ocr_opts: Optional[str] = None,
          password: str = "", admin_password: str = "") -> int:
    opts = json.loads(ocr_opts) if ocr_opts else {}
    st = State(engine, opts, password=password, admin_password=admin_password)
    app = create_app(st)
    print("로그인: " + ("사용 (관리자/검수자 구분)" if st.admin_password and st.password else "사용" if st.auth else "없음"))
    print(f"검수 화면: http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}   (종료: Ctrl+C)")
    if host not in ("127.0.0.1", "localhost") and not st.auth:
        print("[주의] 비밀번호가 설정되지 않았습니다. --password 를 지정하거나 내부망에서만 여십시오.")
    n = st.purge_old()
    if st.retention_days:
        print(f"결과 보관기간 {st.retention_days}일 (삭제 {n}건)")
    try:
        from waitress import serve as wserve          # 운영용 WSGI 서버(순수 파이썬). 없으면 개발용 서버로 대체
        wserve(app, host=host, port=port, threads=4, max_request_body_size=MAX_UPLOAD, ident="adreview")
    except ImportError:
        print("[주의] waitress 가 없어 Flask 개발용 서버로 실행합니다. 운영에서는 waitress 설치를 권장합니다.")
        app.run(host=host, port=port, threaded=True)
    return 0
