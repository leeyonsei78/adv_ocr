"""블라인드 평가용 신규 광고 이미지 생성. 문구·수치·위반 여부·폰트·배경·레이아웃을 시드 난수로 새로 조합한다.
정답(manifest.json)은 이미지 판독이 끝난 뒤에만 열람한다(판독자가 정답을 모르게 하기 위함).
  python3 tests/make_blind.py [seed]    → samples/blind/B01.jpg ... + manifest.json (stdout 에는 정답을 출력하지 않음)"""
import json, random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "blind"
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20261016
rnd = random.Random(SEED)
FD = "/usr/share/fonts/truetype"
import glob, subprocess
FONTS = [f for f in subprocess.run(["fc-list", ":lang=ko", "file"], capture_output=True, text=True).stdout.replace(": ", "\n").split("\n")
         if f.endswith((".ttf", ".ttc")) and "Pen" not in f and "Brush" not in f and "Coding" not in f and "YetHangul" not in f and "Eco" not in f]
FONTS = sorted(set(FONTS))
PALETTES = [("#ffffff", "#17306b", "#d6336c"), ("#fff7e6", "#3b2a14", "#b4540a"), ("#0f1b3d", "#f5f7ff", "#ffd54a"), ("#eef7f1", "#12392a", "#0a8f5a"),
            ("#f3eefb", "#2b1a52", "#7a3cff"), ("#222222", "#f2f2f2", "#ff8a3d"), ("#fdecec", "#4a1010", "#d12c2c"), ("#e8f1fb", "#0d2a4d", "#1766c2")]

CANCER = dict(pid="DEMO-CANCER-01", name="든든암보험")
SAVING = dict(pid="DEMO-SAVING-01", name="차곡차곡저축보험")
SLOG_OK = ["암에 대한 든든한 준비", "가족을 위한 첫걸음", "걱정을 덜어 드립니다", "내일을 위한 안심 설계", "생활 속 작은 안심"]
SLOG_BAD = ["최고의 암 보장 설계", "무조건 받는 진단비", "모든 암 전액 보장", "타사보다 확실한 보장", "지금 바로 가입 놓치지 마세요", "파격 할인 이벤트", "1위 인기 암보험", "업계 최저 보험료", "완벽한 암 준비", "선착순 100명 마감 임박"]
SSLOG_OK = ["차곡차곡 모으는 즐거움", "목돈 마련의 시작", "꾸준히 쌓이는 안정감"]
SSLOG_BAD = ["원금 보장 확정 이자", "누구나 받는 확정 3% 이자", "손실 없는 저축", "다른 상품보다 높은 이율", "역대급 금리 혜택"]

def make_ad():
    prod = rnd.choice([CANCER, SAVING])
    L = []   # (role, text)
    bad = rnd.random() < 0.6
    if prod is CANCER:
        L.append(("head", prod["name"]))
        L.append(("sub", rnd.choice(SLOG_BAD if bad else SLOG_OK)))
        dx = rnd.choice([3000, 5000, 5000, 7000, 10000]); lo = rnd.choice([15, 20, 20]); hi = rnd.choice([60, 65, 65, 70])
        yrs = rnd.choice([10, 20, 20, 15])
        L.append(("body", f"암 진단비 {dx:,}만원 지급"))
        L.append(("body", f"가입연령 {lo}~{hi}세 · {yrs}년납"))
        if rnd.random() < .5:
            L.append(("body", f"소액암 진단비 {rnd.choice([600, 1000, 2000]):,}만원"))
        foot = []
        if rnd.random() < .75: foot.append("※ 갱신형 상품으로 갱신 시 보험료가 인상될 수 있습니다.")
        if rnd.random() < .7: foot.append("※ 가입 전 약관 및 상품설명서를 확인하시기 바랍니다.")
        if rnd.random() < .6: foot.append("※ 가입 후 90일 이내 면책, 1년 이내 진단 시 50% 감액 지급")
    else:
        L.append(("head", prod["name"]))
        L.append(("sub", rnd.choice(SSLOG_BAD if bad else SSLOG_OK)))
        L.append(("body", f"가입연령 {rnd.choice([0, 15, 20])}~{rnd.choice([65, 70, 75, 80])}세 · {rnd.choice([5, 7, 10, 12])}년납"))
        L.append(("body", f"공시이율 연 {rnd.choice([2.5, 3.0, 3.5, 4.0])}% (변동)"))
        foot = []
        if rnd.random() < .75: foot.append("※ 예금자보호법에 따라 보호됩니다.")
        if rnd.random() < .75: foot.append("※ 해지환급금은 납입보험료보다 적거나 없을 수 있습니다.")
        if rnd.random() < .6: foot.append("※ 가입 전 약관 및 상품설명서를 확인하시기 바랍니다.")
    for f in foot: L.append(("foot", f))
    if rnd.random() < .8: L.append(("foot", f"준법감시인 심의필 제2026-{rnd.randint(100, 999):04d}호"))
    return prod, L

def fit(draw, text, path, size, maxw):
    f = ImageFont.truetype(path, size)
    while draw.textlength(text, font=f) > maxw and size > 8:
        size -= 1; f = ImageFont.truetype(path, size)
    return f

def render(L, W, H):
    bg, fg, ac = rnd.choice(PALETTES)
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    style = rnd.choice(["solid", "grad", "stripe", "card", "band"])
    if style == "grad":
        c2 = rnd.choice(PALETTES)[0]
        for y in range(H):
            t = y / H; a = tuple(int(int(bg[i:i+2], 16) * (1 - t) + int(c2[i:i+2], 16) * t) for i in (1, 3, 5)); d.line([(0, y), (W, y)], fill=a)
    elif style == "stripe":
        for x in range(-H, W, 40): d.polygon([(x, 0), (x + 18, 0), (x + 18 + H, H), (x + H, H)], fill=tuple(min(255, int(bg[i:i+2], 16) + 10) for i in (1, 3, 5)))
    elif style == "card":
        d.rounded_rectangle([W * .05, H * .06, W * .95, H * .94], 26, outline=ac, width=6)
    elif style == "band":
        d.rectangle([0, int(H * .28), W, int(H * .5)], fill=ac)
    hp, sp, bp, fp = (rnd.choice(FONTS) for _ in range(4))
    bp = sp if rnd.random() < .5 else bp; fp = bp if rnd.random() < .5 else fp
    align = rnd.choice(["c", "l"]); m = int(W * .09); maxw = W - 2 * m
    size = {"head": int(W * .095), "sub": int(W * .062), "body": int(W * .05), "foot": int(W * .021)}
    path = {"head": hp, "sub": sp, "body": bp, "foot": fp}
    heights = [size[r] * 1.55 for r, _ in L]; gap = H - 2 * int(H * .08) - sum(heights)
    y = int(H * .08) + max(0, gap * .25)
    vis = []
    for (r, t), h in zip(L, heights):
        top, bot = y, y + size[r] * 1.25
        ok = bot <= H
        if style == "band" and top < int(H * .5) < bot: ok = False
        if style == "band" and top < int(H * .28) < bot: ok = False
        if style == "band" and int(H * .28) <= top <= int(H * .5) and bot > int(H * .5): ok = False
        vis.append(ok)
        f = fit(d, t, path[r], size[r], maxw)
        w = d.textlength(t, font=f); x = (W - w) / 2 if align == "c" else m
        col = ac if r == "sub" else fg
        if style == "band" and int(H * .28) <= y <= int(H * .5): col = bg if r != "foot" else col
        if r == "foot": y = max(y, H - int(H * .08) - sum(size["foot"] * 1.55 for rr, _ in L if rr == "foot")) if False else y
        d.text((x, y), t, font=f, fill=col); y += h
        if r == "body" and (L[L.index((r, t)) + 1][0] == "foot"): y += H * .06
    return im, vis

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    widths = [600, 450, 340, 260] * 6; rnd.shuffle(widths)
    man = []
    for i, w in enumerate(widths, 1):
        prod, L = make_ad()
        BW = 1200; BH = rnd.choice([420, 640, 800, 1200]) if False else rnd.choice([560, 700, 900, 1200])
        im, vis = render(L, BW, BH)
        if rnd.random() < .4: im = im.filter(ImageFilter.GaussianBlur(.6))
        h = round(BH * w / BW)
        name = f"B{i:02d}.jpg"
        im.resize((w, h), Image.LANCZOS).save(OUT / name, quality=rnd.choice([60, 70, 80]))
        lines = [t for (_, t), v in zip(L, vis) if v]      # 캔버스 밖으로 잘리거나 띠에 가려진 줄은 정답에서 제외
        n_hidden = len(L) - len(lines)
        man.append({"file": name, "template": name[:3], "tags": [], "level": f"w{w}", "size": [w, h], "items": lines,
                    "product": prod["pid"], "check_lines": lines, "n_hidden": n_hidden})
    (OUT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(man)}장 생성 (정답은 출력하지 않음)")
main()
