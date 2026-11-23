"""담당자 vs Claude 검수 결과의 일치율·Cohen's Kappa·항목별 오류를 집계한다 (표준 라이브러리만)."""
import sys, math
sys.path.insert(0, "scripts")
from xlsx_dump import load

XLSX = "results/광고검수_담당자vsClaude_비교_최종.xlsx"
d = load(XLSX)

# ---------------- 1) 최종결과(적격/시정요구) 수준 ----------------
op = d["광고검수의견"]
# 헤더 행 0, 이후 데이터. 열: 1 광고명, 2 담당자(준법), 5 Claude, 6 비교, 16 완화후 Claude, 17 완화후 비교
rows = [r for r in op[1:] if len(r) > 6 and r[1].strip() and r[2].strip()]
def norm(x):
    x = (x or "").strip()
    return x

pairs = []
for r in rows:
    ad = r[1].split(".")[0].strip()
    human = norm(r[2])
    claude = norm(r[5])
    post = norm(r[16]) if len(r) > 16 and r[16].strip() else claude
    pairs.append((ad, human, claude, post))

print(f"총 광고 건수: {len(pairs)}")
labels = ["적격", "시정요구"]

def confusion(human_i, model_i):
    # 2x2: rows=human(적격/시정), cols=model
    m = {(a, b): 0 for a in labels for b in labels}
    other = 0
    for p in pairs:
        h, c = p[human_i], p[model_i]
        if h in labels and c in labels:
            m[(h, c)] += 1
        else:
            other += 1
    return m, other

def kappa(m):
    n = sum(m.values())
    po = sum(m[(l, l)] for l in labels) / n
    # marginals
    pe = 0
    for l in labels:
        row = sum(m[(l, b)] for b in labels) / n
        col = sum(m[(a, l)] for a in labels) / n
        pe += row * col
    k = (po - pe) / (1 - pe) if (1 - pe) else float("nan")
    return po, pe, k, n

for tag, mi in [("기존 Claude", 2), ("완화기준 반영 후", 3)]:
    m, other = confusion(1, mi)
    po, pe, k, n = kappa(m)
    agree = sum(m[(l, l)] for l in labels)
    print(f"\n=== {tag} (최종결과 수준, n={n}) ===")
    print(f"  담당자 적격·Claude 적격: {m[('적격','적격')]}")
    print(f"  담당자 적격·Claude 시정: {m[('적격','시정요구')]}  (AI가 더 엄격 = FP)")
    print(f"  담당자 시정·Claude 적격: {m[('시정요구','적격')]}  (AI가 더 관대 = FN)")
    print(f"  담당자 시정·Claude 시정: {m[('시정요구','시정요구')]}")
    print(f"  일치 {agree}/{n} = {agree/n:.1%}  / 관측일치 po={po:.3f}, 우연일치 pe={pe:.3f}, Cohen κ={k:.3f}")
    # 담당자/Claude 각각의 적격·시정 분포
    h_ok = sum(1 for p in pairs if p[1]=="적격"); h_fix = sum(1 for p in pairs if p[1]=="시정요구")
    c_ok = sum(1 for p in pairs if p[mi]=="적격"); c_fix = sum(1 for p in pairs if p[mi]=="시정요구")
    print(f"  담당자 적격 {h_ok} / 시정 {h_fix}   Claude 적격 {c_ok} / 시정 {c_fix}")

# ---------------- 2) 항목 수준 (46 x 26) ----------------
it = d["항목별점검표"]
hdr = it[0]
body = [r for r in it[1:] if len(r) >= 6 and r[0].strip() and r[2].strip()]
print(f"\n\n=== 항목 수준 ===\n판정 포인트(행) 수: {len(body)}")
from collections import Counter
dist = Counter(norm(r[5]) for r in body)
print("Claude 판정 분포:", dict(dist))
post_dist = Counter((norm(r[9]) if len(r) > 9 and r[9].strip() else "") for r in body)
# 완화 후 판정이 바뀐 항목
changed = [r for r in body if len(r) > 9 and r[9].strip() and norm(r[9]) != norm(r[5])]
print(f"완화기준 반영으로 판정이 바뀐 항목 수: {len(changed)}")
cc = Counter((norm(r[5]), norm(r[9])) for r in changed)
for (a,b),n in sorted(cc.items(), key=lambda x:-x[1]):
    print(f"  {a} → {b}: {n}")

# 구분별(경고/필수안내/준수/금지) × 미흡 비율
import re
def section(no):
    return {"1":"경고문구","2":"필수안내","3":"준수사항","4":"금지행위"}.get(no.split("-")[0],"기타")
sec = {}
for r in body:
    s = section(r[2]); j = norm(r[5])
    sec.setdefault(s, Counter())[j]+=1
print("\n구분별 Claude 판정 분포 (× 부적합 / △ 미흡 / ○ 적합 / - 해당없음):")
for s in ["경고문구","필수안내","준수사항","금지행위"]:
    c = sec.get(s, Counter())
    tot = sum(c.values())
    print(f"  {s:6s} 총{tot:3d}  ×{c.get('×',0):3d}  △{c.get('△',0):3d}  ○{c.get('○',0):3d}  -{c.get('-',0):3d}")

# 항목(No.)별 × 또는 △가 가장 많은 항목
badcnt = Counter()
for r in body:
    if norm(r[5]) in ("×","△"):
        badcnt[(r[2], r[4])] += 1
print("\n지적(×·△)이 많은 상위 항목:")
for (no,name),n in badcnt.most_common(12):
    print(f"  {no:5s} {name[:28]:30s} {n}건")
