"""폐쇄망 반입 묶음 만들기 — **인터넷이 되는 PC** 에서 실행한다.

  python scripts/make_offline_bundle.py --out adreview_offline --platform win_amd64 --python-version 3.11

만들어지는 것(--out 폴더):
  wheels/        필요한 파이썬 패키지(wheel) 전부 (폐쇄망 PC 의 OS·파이썬 버전에 맞게 받는다)
  app/           프로그램 본체 + 설정(config) + OCR 모델(models) + 샘플 + 실행 스크립트
  INSTALL.txt    폐쇄망에서의 설치 순서

--platform / --python-version 은 *폐쇄망 PC* 기준이다. (예: Windows 64bit → win_amd64, 파이썬 3.11 → 3.11)
이 PC 와 같으면 두 옵션을 생략한다.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", "__pycache__", "output", "_work", ".pytest_cache", "history", "wheels"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="adreview_offline")
    ap.add_argument("--platform", help="폐쇄망 PC 플랫폼. 예) win_amd64, manylinux2014_x86_64")
    ap.add_argument("--python-version", help="폐쇄망 PC 파이썬 버전. 예) 3.11")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    (out / "wheels").mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "pip", "download", "-r", str(ROOT / "requirements-offline.txt"), "-d", str(out / "wheels")]
    if a.platform:
        cmd += ["--platform", a.platform, "--only-binary=:all:"]
        if a.python_version:
            cmd += ["--python-version", a.python_version]
    print(">>", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode:
        print("[오류] 패키지 다운로드 실패. --platform 지정 시 wheel 이 없는 패키지가 있으면 해당 PC 에서 직접 받아야 합니다.")
        return r.returncode

    app = out / "app"
    if app.exists():
        shutil.rmtree(app)
    shutil.copytree(ROOT, app, ignore=lambda d, names: [n for n in names if n in SKIP or n.endswith(".pyc")])
    for d in ("output", "config/history"):
        (app / d).mkdir(parents=True, exist_ok=True)
    (out / "INSTALL.txt").write_text(
        "1) 이 폴더 전체를 폐쇄망 PC 로 옮긴다.\n"
        "2) app 폴더에서: scripts\\install_offline.bat (Windows) 또는 sh scripts/install_offline.sh (Linux)\n"
        "3) 실행: scripts\\run_web.bat / sh scripts/run_web.sh  → 브라우저에서 http://127.0.0.1:8080\n"
        "자세한 내용은 app/docs/폐쇄망_설치.md\n", encoding="utf-8")
    print(f"\n완료: {out}\n  wheel {len(list((out / 'wheels').glob('*')))}개 / 앱 폴더 {app}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
