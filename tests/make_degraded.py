"""기준 광고(ad_cancer_bad.png)를 여러 방식으로 열화시킨 테스트 이미지를 만든다.
열화는 재현 가능하도록 난수 시드를 고정한다."""
import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "samples" / "ad_cancer_bad.png"
OUT = ROOT / "samples" / "degraded"
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
rng = np.random.default_rng(42)


def jpeg(im, q):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def resize(im, f):
    return im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)


def noise(im, sigma):
    a = np.array(im).astype(np.float32)
    a += rng.normal(0, sigma, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def rotate(im, deg):
    return im.rotate(deg, resample=Image.BICUBIC, expand=True, fillcolor=(235, 235, 235))


def low_contrast(im, alpha):
    a = np.array(im).astype(np.float32)
    a = 128 + (a - 128) * alpha
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def busy_banner():
    """사진 같은 복잡한 배경 위에 글자를 얹은 광고 (원본과 같은 문구)."""
    W, H = 1400, 900
    x = np.linspace(0, 1, W)[None, :, None]
    y = np.linspace(0, 1, H)[:, None, None]
    base = np.concatenate([60 + 150 * x + 0 * y, 90 + 100 * y + 0 * x, 200 - 140 * x + 0 * y], axis=2)
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(70):
        cx, cy, r = rng.integers(0, W), rng.integers(0, H), rng.integers(30, 160)
        col = tuple(int(v) for v in rng.integers(30, 255, 3)) + (int(rng.integers(40, 110)),)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    im = im.filter(ImageFilter.GaussianBlur(3))
    d = ImageDraw.Draw(im)

    def t(xy, s, size, bold=False, fill=(255, 255, 255)):
        f = ImageFont.truetype(FONT_B if bold else FONT, size)
        d.text(xy, s, font=f, fill=fill, stroke_width=2 if size > 30 else 1, stroke_fill=(20, 20, 40))

    t((60, 50), "든든암보험", 54, True, (255, 220, 80))
    t((60, 130), "대한민국 최고의 암보험! 무조건 100% 보장", 62, True)
    t((60, 235), "타사보다 저렴한 보험료, 지금 바로 가입하세요", 40)
    t((60, 380), "암 진단비 최대 7,000만원", 56, True, (255, 255, 255))
    t((60, 470), "소액암 진단비 1,000만원 · 가입연령 20~70세", 40)
    t((60, 540), "20년납 20년만기 · 보장개시 후 90일 면책", 40)
    t((60, 780), "※ 자세한 보장내용은 약관을 확인하시기 바랍니다.", 15)
    t((60, 805), "※ 갱신형 상품으로 갱신 시 보험료가 인상될 수 있습니다.", 15)
    return im


def make():
    OUT.mkdir(parents=True, exist_ok=True)
    src = Image.open(SRC).convert("RGB")
    cases = {
        "01_jpeg_q15": jpeg(src, 15),
        "02_lowres_0.6x": resize(src, 0.6),
        "03_lowres_0.4x": resize(src, 0.4),
        "04_blur_s2": src.filter(ImageFilter.GaussianBlur(2)),
        "05_noise_s30": noise(src, 30),
        "06_skew_5deg": rotate(src, 5),
        "07_low_contrast": low_contrast(src, 0.4),
        "08_busy_background": busy_banner(),
        "09_combo_phone": jpeg(resize(src, 0.5).filter(ImageFilter.GaussianBlur(1.0)), 30),
        "10_combo_worst": jpeg(noise(rotate(resize(src, 0.5).filter(ImageFilter.GaussianBlur(1.3)), 3), 18), 22),
    }
    for name, im in cases.items():
        ext = "jpg" if ("jpeg" in name or "combo" in name) else "png"
        p = OUT / f"{name}.{ext}"
        if ext == "jpg":
            im.save(p, "JPEG", quality=int(name.split('q')[-1]) if "jpeg" in name else 30)
        else:
            im.save(p)
    return sorted(p.name for p in OUT.iterdir())


if __name__ == "__main__":
    print(make())
