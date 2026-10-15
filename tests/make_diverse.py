"""서로 다른 글꼴·배경·레이아웃의 광고 이미지 15종 + 화질 저하 2단계(mild/heavy) = 45장을 만든다.

각 광고는 정답 문구(items)와 위반 점검용 정답 줄(check_lines)을 함께 manifest.json 에 기록한다.
※ 합성 이미지이므로 실제 광고물과 다르다. 다만 글꼴(명조·둥근·손글씨·붓글씨·헤드라인·가는 글씨),
  배경(사진풍·패턴·네온·밝은 그라데이션·종이), 레이아웃(표·카드·2단·회전·세로쓰기·빽빽한 각주·영문 혼용)을 최대한 섞었다.
실행:  python3 tests/make_diverse.py
"""
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "diverse"
N = "/usr/share/fonts/truetype/nanum/"
NOTO = "/usr/share/fonts/opentype/noto/"
F = {
    "ng": N + "NanumGothic.ttf", "ngb": N + "NanumGothicBold.ttf",
    "nm": N + "NanumMyeongjo.ttf", "nmb": N + "NanumMyeongjoBold.ttf",
    "nsr": N + "NanumSquareRoundR.ttf", "nsrb": N + "NanumSquareRoundB.ttf",
    "pen": N + "NanumPen.ttf", "brush": N + "NanumBrush.ttf",
    "bmh": "/usr/share/fonts/truetype/baekmuk/hline.ttf", "bmb": "/usr/share/fonts/truetype/baekmuk/batang.ttf",
    "bmd": "/usr/share/fonts/truetype/baekmuk/dotum.ttf",
    "unb": "/usr/share/fonts/truetype/unfonts-core/UnBatang.ttf",
    "black": NOTO + "NotoSansCJK-Black.ttc", "thin": NOTO + "NotoSansCJK-Thin.ttc",
    "noto": NOTO + "NotoSansCJK-Regular.ttc", "notob": NOTO + "NotoSansCJK-Bold.ttc",
    "serifb": NOTO + "NotoSerifCJK-Bold.ttc",
}
USED = []   # (font path, text) — 글리프 누락 검사용


# ---------------------------------------------------------------- 그리기 도구
def font(key, size):
    return ImageFont.truetype(F[key], size)


def txt(d, xy, s, key, size, fill=(0, 0, 0), anchor="la", stroke=0, sfill=(0, 0, 0), maxw=None, shadow=None):
    if maxw:
        while size > 10 and font(key, size).getlength(s) > maxw:
            size -= 2
    f = font(key, size)
    USED.append((F[key], s))
    if shadow:
        d.text((xy[0] + shadow[0], xy[1] + shadow[1]), s, font=f, fill=shadow[2], anchor=anchor,
               stroke_width=stroke, stroke_fill=shadow[2])
    d.text(xy, s, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sfill)


def rot_text(im, center, s, key, size, fill, deg, stroke=0, sfill=(0, 0, 0)):
    f = font(key, size)
    USED.append((F[key], s))
    w, h = int(f.getlength(s)) + 60, size * 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((30, h // 2), s, font=f, fill=fill, anchor="lm", stroke_width=stroke, stroke_fill=sfill)
    layer = layer.rotate(deg, expand=True, resample=Image.BICUBIC)
    im.paste(layer, (int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)), layer)


def glow_text(im, xy, s, key, size, color, anchor="ma", blur=9):
    f = font(key, size)
    USED.append((F[key], s))
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, s, font=f, fill=color + (255,), anchor=anchor)
    g = layer.filter(ImageFilter.GaussianBlur(blur))
    base = im.convert("RGBA")
    base = Image.alpha_composite(Image.alpha_composite(base, g), g)
    ImageDraw.Draw(base).text(xy, s, font=f, fill=(255, 255, 255, 255), anchor=anchor)   # 심지는 밝게
    ImageDraw.Draw(base).text(xy, s, font=f, fill=color + (200,), anchor=anchor, stroke_width=1, stroke_fill=color + (255,))
    return base.convert("RGB")


def grad(W, H, c0, c1, diag=False):
    y = np.linspace(0, 1, H)[:, None, None]
    x = np.linspace(0, 1, W)[None, :, None]
    t = (x + y) / 2 if diag else y + 0 * x
    a = np.array(c0)[None, None, :] * (1 - t) + np.array(c1)[None, None, :] * t
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def add_noise(im, sigma, seed=0):
    r = np.random.default_rng(seed)
    a = np.array(im).astype(np.float32) + r.normal(0, sigma, (im.height, im.width, 1))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def photo_bg(W, H, seed):
    r = np.random.default_rng(seed)
    im = grad(W, H, (60, 110, 190), (240, 170, 110))
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(30):
        cx, cy, rad = int(r.integers(0, W)), int(r.integers(0, H)), int(r.integers(40, 200))
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                  fill=tuple(int(v) for v in r.integers(40, 255, 3)) + (int(r.integers(50, 120)),))
    xx = 0
    while xx < W:   # 도시 스카이라인
        w, h = int(r.integers(50, 130)), int(r.integers(100, 380))
        d.rectangle([xx, H - h, xx + w, H], fill=(20, 25, 40, 255))
        for wy in range(H - h + 14, H - 8, 28):
            for wx in range(xx + 8, xx + w - 12, 20):
                if r.random() < 0.4:
                    d.rectangle([wx, wy, wx + 8, wy + 12], fill=(255, 220, 120, 255))
        xx += w + int(r.integers(0, 10))
    return add_noise(im.filter(ImageFilter.GaussianBlur(1.4)), 5, seed)


def paper_bg(W, H, base, seed, grain=7):
    r = np.random.default_rng(seed)
    n = Image.fromarray(np.clip(128 + r.normal(0, 40, (H, W)), 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    n = (np.array(n).astype(np.float32) - 128) / 40 * grain
    a = np.array(Image.new("RGB", (W, H), base)).astype(np.float32) + n[:, :, None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- 광고 템플릿
def t01_serif():
    W, H = 1400, 900
    im = paper_bg(W, H, (247, 241, 226), 1)
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([30, 30, W - 30, H - 30], outline=(90, 60, 30), width=4)
    d.rectangle([44, 44, W - 44, H - 44], outline=(90, 60, 30), width=1)
    L = ["차곡차곡저축보험", "원금 보장, 확정 3.5% 이자를 드립니다", "누구나 가입할 수 있는 저축보험",
         "가입연령 0~75세 · 5년납 가능", "※ 공시이율은 변동될 수 있습니다.", "준법감시인 심의필 제2026-0777호"]
    txt(d, (700, 90), L[0], "nmb", 70, (60, 30, 20), "ma")
    txt(d, (700, 230), L[1], "nmb", 52, (120, 20, 20), "ma", maxw=1200)
    txt(d, (700, 340), L[2], "nm", 42, (40, 40, 40), "ma")
    txt(d, (700, 430), L[3], "nm", 42, (40, 40, 40), "ma")
    txt(d, (700, 760), L[4], "nm", 18, (110, 100, 90), "ma")
    txt(d, (700, 815), L[5], "nm", 24, (60, 50, 40), "ma")
    return im, dict(items=L, product="DEMO-SAVING-01")


def t02_round_pop():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), (255, 244, 230))
    d = ImageDraw.Draw(im, "RGBA")
    r = np.random.default_rng(2)
    for _ in range(26):
        cx, cy, rad = int(r.integers(0, W)), int(r.integers(0, H)), int(r.integers(30, 120))
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=tuple(int(v) for v in r.integers(150, 255, 3)) + (110,))
    d.rounded_rectangle([120, 160, 1280, 270], 40, fill=(255, 210, 70, 255))
    L = ["든든암보험 지금 가입 이벤트!", "오늘만 선착순 100명 마감 임박", "암 진단비 5,000만원 · 소액암 진단비 1,000만원",
         "20년납 20년만기 · 가입연령 20~65세", "다른 보험사보다 저렴한 보험료",
         "※ 약관 및 상품설명서를 확인하세요. 갱신 시 보험료가 인상될 수 있습니다.", "심의필 제2026-0801호"]
    txt(d, (700, 60), L[0], "nsrb", 62, (230, 60, 90), "ma")
    txt(d, (700, 190), L[1], "nsrb", 50, (60, 40, 20), "ma")
    txt(d, (700, 330), L[2], "nsrb", 40, (40, 40, 90), "ma", maxw=1280)
    txt(d, (700, 410), L[3], "nsrb", 40, (40, 40, 90), "ma")
    txt(d, (700, 510), L[4], "nsrb", 46, (20, 120, 90), "ma")
    txt(d, (700, 740), L[5], "nsr", 22, (110, 110, 110), "ma", maxw=1300)
    txt(d, (700, 790), L[6], "nsr", 24, (110, 110, 110), "ma")
    return im, dict(items=L, product="DEMO-CANCER-01")


def t03_handwriting():
    W, H = 1400, 900
    im = paper_bg(W, H, (205, 170, 125), 3, grain=12)
    d = ImageDraw.Draw(im, "RGBA")
    L = ["든든암보험", "암 걱정 없는 세상, 최고의 보장", "진단비 7,000만원 보장",
         "※ 보장개시 후 90일 면책, 1년 이내 진단 시 50% 감액", "준법감시인 심의필 제2026-0310호"]
    txt(d, (80, 40), L[0], "brush", 140, (60, 30, 10))
    txt(d, (80, 250), L[1], "pen", 90, (120, 20, 20))
    txt(d, (80, 390), L[2], "pen", 90, (30, 30, 30))
    txt(d, (80, 700), L[3], "ng", 26, (50, 30, 20))
    txt(d, (80, 770), L[4], "ng", 26, (50, 30, 20))
    return im, dict(items=L, product="DEMO-CANCER-01")


def t04_photo():
    W, H = 1400, 900
    im = photo_bg(W, H, 4)
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([60, 330, 1120, 470], fill=(0, 0, 0, 140))
    L = ["든든암보험", "100% 보장! 무조건 지급", "암 진단비 최대 1억원", "가입연령 20~65세 | 보험기간 20년",
         "※ 갱신형 상품이며 갱신 시 보험료가 인상될 수 있습니다."]
    txt(d, (80, 50), L[0], "notob", 80, (255, 255, 255), stroke=4, sfill=(10, 20, 50))
    txt(d, (80, 180), L[1], "notob", 86, (255, 255, 255), stroke=5, sfill=(10, 20, 50))
    txt(d, (90, 350), L[2], "notob", 66, (255, 230, 90))
    txt(d, (80, 520), L[3], "noto", 46, (255, 255, 255), stroke=3, sfill=(10, 20, 50))
    txt(d, (80, 780), L[4], "noto", 22, (255, 255, 255), stroke=2, sfill=(10, 20, 50))
    return im, dict(items=L, product="DEMO-CANCER-01")


def t05_dense():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im, "RGBA")
    head = ["든든암보험", "암 진단 시 3,000만원 지급", "가입연령 20~65세 · 20년납 20년만기"]
    small = ["※ 이 보험은 갱신형 상품으로 갱신 시 보험료가 인상될 수 있습니다.",
             "※ 보험계약 체결 전 상품설명서 및 약관을 반드시 확인하시기 바랍니다.",
             "※ 암 보장개시일은 계약일부터 90일이 지난 날의 다음 날입니다.",
             "※ 보장개시일부터 1년 이내 암 진단 시 보험금의 50%를 지급합니다.",
             "※ 소액암(갑상선암, 기타피부암 등)은 일반암 진단비의 20%를 지급합니다.",
             "※ 기존 보험계약을 해지하고 새로운 보험계약을 체결하는 경우 보험인수가 거절되거나 보험료가 인상될 수 있습니다.",
             "※ 가입 연령 및 납입 기간에 따라 보험료는 달라질 수 있습니다.",
             "준법감시인 심의필 제2026-0123호 (2026.10.01)"]
    txt(d, (80, 50), head[0], "nsrb", 72, (20, 60, 130))
    txt(d, (80, 150), head[1], "nsrb", 56, (30, 30, 30))
    txt(d, (80, 240), head[2], "nsr", 36, (60, 60, 60))
    for i, s in enumerate(small):
        txt(d, (80, 360 + i * 40), s, "ng", 19, (70, 70, 70), maxw=1250)
    return im, dict(items=head + small, product="DEMO-CANCER-01")


def t06_table():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im, "RGBA")
    title = "든든암보험 보장내용 (업계 최고 수준)"
    txt(d, (80, 40), title, "nsrb", 54, (20, 40, 90))
    xs = [80, 520, 880, 1320]
    head = ["보장내용", "가입금액", "지급조건"]
    rows = [["일반암 진단비", "5,000만원", "최초 1회 한함"], ["소액암 진단비", "1,000만원", "최초 1회 한함"],
            ["가입연령", "20~65세", "보험기간 20년"], ["면책기간", "90일", "감액 1년"]]
    d.rectangle([xs[0], 150, xs[-1], 230], fill=(30, 60, 120))
    for j, h in enumerate(head):
        txt(d, ((xs[j] + xs[j + 1]) // 2, 190), h, "ngb", 38, (255, 255, 255), "mm")
    for i, row in enumerate(rows):
        y0 = 230 + i * 90
        d.rectangle([xs[0], y0, xs[-1], y0 + 90], fill=(240, 244, 252) if i % 2 == 0 else (255, 255, 255))
        for j, c in enumerate(row):
            txt(d, ((xs[j] + xs[j + 1]) // 2, y0 + 45), c, "ng", 38, (30, 30, 30), "mm")
    for x in xs:
        d.line([x, 150, x, 590], fill=(120, 130, 160), width=2)
    for y in [150, 230, 320, 410, 500, 590]:
        d.line([xs[0], y, xs[-1], y], fill=(120, 130, 160), width=2)
    f1, f2 = "※ 갱신 시 보험료가 인상될 수 있으며 약관을 확인하시기 바랍니다.", "준법감시인 심의필 제2026-0222호"
    txt(d, (80, 660), f1, "ng", 24, (80, 80, 80))
    txt(d, (80, 710), f2, "ng", 24, (80, 80, 80))
    cells = [c for r in rows for c in r]
    return im, dict(items=[title] + head + cells + [f1, f2], product="DEMO-CANCER-01",
                    check_lines=[title] + head + [" ".join(r) for r in rows] + [f1, f2])


def t07_rotated():
    W, H = 1400, 900
    im = grad(W, H, (255, 120, 60), (255, 205, 70), diag=True)
    d = ImageDraw.Draw(im, "RGBA")
    rot_text(im, (540, 250), "든든암보험 출시 기념 파격 혜택", "black", 62, (255, 255, 255, 255), 6, stroke=3, sfill=(120, 40, 0))   # 배지(x>=1060)와 겹치지 않게
    d.ellipse([1060, 60, 1300, 300], fill=(200, 20, 40, 255), outline=(255, 255, 255, 255), width=6)
    txt(d, (1180, 135), "최초", "notob", 54, (255, 255, 255), "mm")
    txt(d, (1180, 215), "1위", "black", 80, (255, 255, 255), "mm")
    L = ["든든암보험 출시 기념 파격 혜택", "최초", "1위", "역대급 혜택, 지금 바로 가입", "가입연령 20~65세 · 암 진단비 5,000만원",
         "※ 갱신형 상품 / 약관을 확인하세요"]
    txt(d, (80, 430), L[3], "ngb", 58, (255, 255, 255), stroke=2, sfill=(120, 40, 0))
    txt(d, (80, 540), L[4], "ngb", 46, (60, 20, 0))
    txt(d, (80, 800), L[5], "ng", 22, (90, 40, 0))
    return im, dict(items=L, product="DEMO-CANCER-01")


def t08_neon():
    W, H = 1400, 900
    im = grad(W, H, (8, 10, 30), (30, 10, 60))
    d = ImageDraw.Draw(im, "RGBA")
    for x in range(0, W, 70):
        d.line([x, 0, x, H], fill=(80, 80, 160, 40), width=1)
    for y in range(0, H, 70):
        d.line([0, y, W, y], fill=(80, 80, 160, 40), width=1)
    L = ["차곡차곡저축보험", "연 4.0% 확정 이자", "5년납 · 가입연령 0~70세",
         "※ 공시이율은 변동될 수 있으며 최저보증이율은 1.0%입니다.", "준법감시인 심의필 제2026-0444호"]
    im = glow_text(im, (700, 80), L[0], "black", 84, (0, 230, 255))
    im = glow_text(im, (700, 230), L[1], "black", 92, (255, 60, 200))
    im = glow_text(im, (700, 390), L[2], "notob", 52, (255, 235, 60), blur=6)
    d = ImageDraw.Draw(im, "RGBA")
    txt(d, (700, 780), L[3], "noto", 24, (170, 170, 205), "ma")
    txt(d, (700, 830), L[4], "noto", 24, (170, 170, 205), "ma")
    return im, dict(items=L, product="DEMO-SAVING-01")


def t09_twocol():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), (240, 242, 245))
    d = ImageDraw.Draw(im, "RGBA")
    d.rounded_rectangle([60, 60, 760, 740], 30, fill=(255, 255, 255))
    d.rounded_rectangle([800, 60, 1340, 740], 30, fill=(20, 60, 130))
    L = ["보장 안내", "• 일반암 진단비 5,000만원", "• 소액암 진단비 1,000만원", "• 가입연령 20~65세", "• 20년납 20년만기",
         "든든암보험", "암 걱정", "최대 보장", "※ 갱신 시 보험료 인상 가능 / 심의필 제2026-0666호"]
    txt(d, (100, 100), L[0], "ngb", 48, (20, 60, 130))
    for i in range(1, 5):
        txt(d, (100, 210 + (i - 1) * 110), L[i], "ng", 42, (40, 40, 40))
    txt(d, (1070, 200), L[5], "nsrb", 60, (255, 255, 255), "mm")
    txt(d, (1070, 380), L[6], "black", 96, (255, 220, 60), "mm")
    txt(d, (1070, 540), L[7], "black", 96, (255, 255, 255), "mm")
    txt(d, (60, 800), L[8], "ng", 24, (90, 90, 90))
    return im, dict(items=L, product="DEMO-CANCER-01")


def t10_english():
    W, H = 1400, 900
    im = grad(W, H, (255, 255, 255), (200, 225, 250))
    d = ImageDraw.Draw(im, "RGBA")
    L = ["CANCER CARE+ 든든암보험", "대한민국 No.1 암보험", "Best Choice 2026", "보장 확대! 암 진단비 5,000만원",
         "상담 문의 1588-0000 (24시간)", "※ 약관을 확인하시기 바랍니다. 심의필 제2026-0999호"]
    txt(d, (80, 60), L[0], "black", 72, (0, 90, 170))
    txt(d, (80, 190), L[1], "notob", 78, (220, 30, 60))
    txt(d, (80, 320), L[2], "noto", 62, (40, 40, 40))
    txt(d, (80, 430), L[3], "notob", 58, (30, 30, 30))
    txt(d, (80, 550), L[4], "noto", 50, (30, 30, 30))
    txt(d, (80, 800), L[5], "noto", 24, (80, 80, 80))
    return im, dict(items=L, product="DEMO-CANCER-01")


def t11_vertical():
    W, H = 1400, 900
    im = paper_bg(W, H, (250, 245, 235), 11, grain=4)
    d = ImageDraw.Draw(im, "RGBA")
    for i, ch in enumerate("든든암보험"):
        txt(d, (1220, 60 + i * 140), ch, "nmb", 110, (40, 20, 20), "ma")
    for i, ch in enumerate("최고의보장"):
        txt(d, (1040, 60 + i * 140), ch, "nm", 90, (150, 20, 20), "ma")
    L = ["든든암보험", "최고의보장", "암 진단 시 5,000만원", "가입연령 20~65세", "※ 약관을 확인하세요", "심의필 제2026-0333호"]
    txt(d, (80, 200), L[2], "nsrb", 62, (30, 30, 30))
    txt(d, (80, 330), L[3], "nsrb", 50, (30, 30, 30))
    txt(d, (80, 800), L[4], "ng", 26, (90, 90, 90))
    txt(d, (80, 845), L[5], "ng", 26, (90, 90, 90))
    return im, dict(items=L, product="DEMO-CANCER-01", check_lines=["든든암보험 최고의 보장"] + L[2:])


def t12_thin():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im, "RGBA")
    L = ["차곡차곡저축보험", "전액 환급 가능한 저축보험", "5년납 · 가입연령 0~70세",
         "※ 해지환급금은 납입보험료보다 적거나 없을 수 있습니다.", "예금자보호법에 따라 보호됩니다.", "준법감시인 심의필 제2026-0111호"]
    txt(d, (700, 100), L[0], "thin", 80, (120, 120, 120), "ma")
    txt(d, (700, 250), L[1], "thin", 66, (140, 140, 140), "ma")
    txt(d, (700, 380), L[2], "thin", 52, (150, 150, 150), "ma")
    txt(d, (700, 690), L[3], "thin", 26, (150, 150, 150), "ma")
    txt(d, (700, 740), L[4], "thin", 26, (150, 150, 150), "ma")
    txt(d, (700, 790), L[5], "thin", 26, (150, 150, 150), "ma")
    return im, dict(items=L, product="DEMO-SAVING-01")


def t13_retro():
    W, H = 1400, 900
    im = grad(W, H, (255, 232, 80), (255, 170, 40))
    d = ImageDraw.Draw(im, "RGBA")
    L = ["든든암보험", "지금 바로 가입하세요", "최고의 보장", "암 진단비 3,000만원 · 가입연령 20~65세",
         "※ 약관을 확인하세요. 심의필 제2026-0888호"]
    sh = (6, 6, (180, 70, 0))
    txt(d, (700, 60), L[0], "bmh", 130, (255, 255, 255), "ma", shadow=sh)
    txt(d, (700, 250), L[1], "bmh", 84, (255, 255, 255), "ma", shadow=sh)
    txt(d, (700, 380), L[2], "bmh", 96, (255, 255, 255), "ma", shadow=sh)
    txt(d, (700, 560), L[3], "bmb", 46, (110, 60, 0), "ma")
    txt(d, (700, 800), L[4], "bmd", 24, (110, 60, 0), "ma")
    return im, dict(items=L, product="DEMO-CANCER-01")


def t14_scan():
    W, H = 1000, 1400
    im = paper_bg(W, H, (243, 238, 224), 14, grain=9)
    d = ImageDraw.Draw(im, "RGBA")
    L = ["든든암보험 안내문", "든든암보험은 암 진단 시 진단비를 지급하는 갱신형 보험입니다.",
         "일반암 진단비 5,000만원, 소액암 진단비 1,000만원을 지급합니다.",
         "가입연령은 20세부터 65세까지이며 보험기간은 20년입니다.",
         "타사 대비 보험료가 저렴하며 모든 보장 혜택을 누리실 수 있습니다.",
         "보장개시일부터 90일간은 면책이며, 1년 이내 진단 시 50%가 감액됩니다.",
         "갱신 시 보험료가 인상될 수 있으니 약관을 반드시 확인하시기 바랍니다.",
         "문의: 고객센터 1588-0000 (평일 09:00~18:00)", "준법감시인 심의필 제2026-0555호"]
    txt(d, (500, 90), L[0], "serifb", 60, (30, 30, 30), "ma")
    for i, s in enumerate(L[1:]):
        txt(d, (70, 260 + i * 110), s, "unb", 27, (35, 35, 35), maxw=870)
    vign = np.array(im).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    v = 1 - 0.18 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    sheet = Image.fromarray(np.clip(vign * v[:, :, None], 0, 255).astype(np.uint8))
    sheet = sheet.rotate(1.3, expand=True, resample=Image.BICUBIC, fillcolor=(120, 120, 120))
    return add_noise(sheet, 6, 14), dict(items=L, product="DEMO-CANCER-01")


def t15_cards():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), (235, 240, 248))
    d = ImageDraw.Draw(im, "RGBA")
    cards = [("일반암 진단비", "5,000만원", (30, 110, 200)), ("소액암 진단비", "1,000만원", (230, 90, 60)), ("면책기간", "90일", (40, 160, 110))]
    L = ["든든암보험 핵심 보장"]
    check = ["든든암보험 핵심 보장"]
    txt(d, (700, 50), L[0], "nsrb", 58, (20, 40, 90), "ma")
    for i, (lab, val, col) in enumerate(cards):
        x0 = 80 + i * 430
        d.rounded_rectangle([x0, 180, x0 + 380, 480], 28, fill=col + (255,))
        txt(d, (x0 + 190, 270), lab, "nsrb", 38, (255, 255, 255), "mm")
        txt(d, (x0 + 190, 380), val, "black", 66, (255, 255, 255), "mm")
        L += [lab, val]
        check.append(f"{lab} {val}")
    tail = ["20년납 20년만기 · 가입연령 20~65세", "업계 최초 · 최고 보장", "※ 갱신 시 보험료가 인상될 수 있습니다. 약관 확인 / 심의필 제2026-0120호"]
    txt(d, (700, 570), tail[0], "nsrb", 42, (40, 40, 40), "ma")
    txt(d, (700, 680), tail[1], "nsrb", 48, (200, 30, 50), "ma")
    txt(d, (700, 820), tail[2], "ng", 22, (90, 90, 90), "ma", maxw=1300)
    return im, dict(items=L + tail, product="DEMO-CANCER-01", check_lines=check + tail)


TEMPLATES = [
    ("T01_명조_종이", ["serif", "paper"], t01_serif), ("T02_둥근체_파스텔", ["rounded", "pattern"], t02_round_pop),
    ("T03_손글씨_붓글씨", ["handwriting", "paper"], t03_handwriting), ("T04_사진배경_외곽선", ["photo", "outline"], t04_photo),
    ("T05_빽빽한_작은글씨", ["small-print"], t05_dense), ("T06_표", ["table"], t06_table),
    ("T07_회전_배지", ["rotated", "bright-bg"], t07_rotated), ("T08_네온_어두운배경", ["neon", "dark-bg"], t08_neon),
    ("T09_2단_레이아웃", ["two-column", "dark-bg"], t09_twocol), ("T10_영문혼용", ["mixed-language"], t10_english),
    ("T11_세로쓰기", ["vertical", "paper"], t11_vertical), ("T12_가는글씨_저대비", ["thin", "low-contrast"], t12_thin),
    ("T13_복고_밝은배경", ["retro", "bright-bg", "low-contrast"], t13_retro), ("T14_스캔_전단", ["scan", "serif", "paper"], t14_scan),
    ("T15_카드", ["cards", "dark-bg"], t15_cards),
]


# ---------------------------------------------------------------- 화질 저하
LEVELS = {"mild": dict(scale=0.75, blur=0.5, noise=3, rot=0.8, q=55),
          "heavy": dict(scale=0.5, blur=1.0, noise=8, rot=2.0, q=28)}


def degrade(im, level, seed):
    p, r = LEVELS[level], np.random.default_rng(seed)
    im = im.convert("RGB").resize((int(im.width * p["scale"]), int(im.height * p["scale"])), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(p["blur"]))
    sign = 1 if r.random() < 0.5 else -1
    im = im.rotate(sign * p["rot"], expand=True, resample=Image.BICUBIC, fillcolor=im.getpixel((0, 0)))
    im = add_noise(im, p["noise"], seed)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=p["q"])
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def check_glyphs():
    from fontTools.ttLib import TTFont
    cmaps, bad = {}, set()
    for path, s in USED:
        if path not in cmaps:
            cmaps[path] = TTFont(path, fontNumber=0).getBestCmap()
        for ch in s:
            if ch != " " and ord(ch) not in cmaps[path]:
                bad.add((Path(path).name, ch))
    return sorted(bad)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (name, tags, fn) in enumerate(TEMPLATES):
        im, gt = fn()
        im = im.convert("RGB")
        gt.setdefault("check_lines", gt["items"])
        for level in ("clean", "mild", "heavy"):
            img = im if level == "clean" else degrade(im, level, 100 + i)
            fname = f"{name}__{level}." + ("png" if level == "clean" else "jpg")
            if level == "clean":
                img.save(OUT / fname)
            else:
                img.save(OUT / fname, "JPEG", quality=LEVELS[level]["q"])
            manifest.append(dict(file=fname, template=name, tags=tags, level=level, size=list(img.size), **gt))
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = check_glyphs()
    print(f"{len(manifest)}장 생성 → {OUT}")
    print("글리프 누락:", bad if bad else "없음")


if __name__ == "__main__":
    main()
