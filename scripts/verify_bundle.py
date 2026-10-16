"""반입한 묶음의 무결성 확인: SHA256SUMS.txt 와 실제 파일의 해시를 대조한다.
  python app/scripts/verify_bundle.py [묶음폴더]     (기본: app 폴더의 상위 폴더)
※ SHA256SUMS.txt 자체는 반입 전 별도 경로(예: 문서·메일)로 받은 값과 대조해야 의미가 있다.
"""
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent.parent
sums = root / "SHA256SUMS.txt"
if not sums.exists():
    sys.exit(f"{sums} 가 없습니다.")
bad = missing = ok = 0
for line in sums.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    digest, name = line.split("  ", 1)
    f = root / name
    if not f.exists():
        print("없음  ", name)
        missing += 1
        continue
    h = hashlib.sha256()
    with f.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != digest:
        print("불일치", name)
        bad += 1
    else:
        ok += 1
print(f"일치 {ok} / 불일치 {bad} / 없음 {missing}")
sys.exit(1 if bad or missing else 0)
