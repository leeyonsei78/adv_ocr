"""OCR 엔진 래퍼.

- PaddleOCREngine : 기본값. 비교 시험(합성 광고 45장)에서 정확도·속도 모두 우세. 모델 파일(약 19MB)을 사전에 반입해야 한다.
- TesseractEngine : 대안. 폐쇄망 설치가 쉽다 (tesseract 바이너리 + kor.traineddata 필요).

모든 엔진은 `recognize(image_path) -> list[TextBlock]` 를 제공한다.
bbox 는 "원본 이미지" 픽셀 좌표 기준이다 (내부 확대 처리 후 되돌려서 반환).
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import re
from typing import Optional

import cv2
import numpy as np

from .models import TextBlock

_HAS_CONTENT = re.compile(r"[0-9A-Za-z가-힣]")


@contextlib.contextmanager
def _tesseract_env():
    """Tesseract 하위 프로세스에만 OMP_THREAD_LIMIT=1 을 적용한다.

    Tesseract 의 OpenMP 다중 스레드는 코어가 적은 PC 에서 오히려 3배가량 느려지는 경우가 많다.
    하지만 이 값을 현재 프로세스 전체에 걸어 두면 같은 프로세스의 PaddleOCR 인식 결과가 깨진다
    (한 프로세스에서 두 엔진을 함께 쓸 때 실제로 발생). 그래서 호출하는 동안만 설정하고 복원한다.
    사용자가 OMP_THREAD_LIMIT 을 직접 지정해 둔 경우에는 그 값을 따른다.
    """
    if "OMP_THREAD_LIMIT" in os.environ:
        yield
        return
    os.environ["OMP_THREAD_LIMIT"] = "1"
    try:
        yield
    finally:
        os.environ.pop("OMP_THREAD_LIMIT", None)


def load_bgr(path: str):
    """이미지를 BGR ndarray 로 읽는다. 투명 PNG 는 흰 배경에 합성한다. (한글 경로 안전)"""
    from PIL import Image

    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def _iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if inter == 0:
        return 0.0
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua else 0.0


def merge_blocks(groups: list, iou_thr: float = 0.4) -> list:
    """여러 전처리 변형의 결과를 합친다. 겹치는 박스는 (신뢰도 x 글자수)가 큰 쪽을 남긴다."""
    merged: list = []
    for blocks in groups:
        for b in blocks:
            hit = None
            for i, m in enumerate(merged):
                if b.bbox and m.bbox and _iou(b.bbox, m.bbox) >= iou_thr:
                    hit = i
                    break
            if hit is None:
                merged.append(b)
            else:
                m = merged[hit]
                if b.conf * len(b.text) > m.conf * len(m.text):
                    merged[hit] = b
    return merged


def sort_reading_order(blocks: list, line_tol: float = 0.6) -> list:
    """위→아래, 같은 줄이면 왼→오른쪽 순으로 정렬."""
    def key(b):
        x0, y0, x1, y1 = b.bbox
        return (y0, x0)

    out = sorted([b for b in blocks if b.bbox], key=key)
    # 같은 줄(세로 중심이 비슷한) 블록은 x 순으로 재정렬
    lines: list = []
    for b in out:
        cy = (b.bbox[1] + b.bbox[3]) / 2
        h = max(1, b.bbox[3] - b.bbox[1])
        for ln in lines:
            if abs(ln["cy"] - cy) <= h * line_tol:
                ln["items"].append(b)
                break
        else:
            lines.append({"cy": cy, "items": [b]})
    res = []
    for ln in lines:
        res.extend(sorted(ln["items"], key=lambda b: b.bbox[0]))
    return res


class OCREngine:
    name = "base"

    def recognize(self, image_path: str) -> list:
        raise NotImplementedError


class TesseractEngine(OCREngine):
    """Tesseract 다중 변형 OCR.

    광고물은 '큰 제목 + 아주 작은 각주'가 한 장에 섞여 있어 한 가지 설정으로는 둘 다 읽기 어렵다.
    그래서 설정이 다른 여러 번의 인식 결과(variant)를 모두 보존하고, 점검 단계에서 변형별로 검사한 뒤
    결과를 합친다.
      page   : 페이지 전체, psm 6 (블록 단위)       - 본문·제목에 강함 (+ 반전 이미지 보완)
      sparse : 페이지 전체, psm 11 (흩어진 글자)     - 배치가 자유로운 디자인 문구 보완
      bands  : 가로 띠로 잘라 확대 후 psm 6          - 작은 각주·단서 문구 복원
    """
    name = "tesseract"

    def __init__(self, lang: str = "kor+eng", min_conf: float = 30.0, min_width: int = 1800,
                 try_inverted: bool = True, variants=("page", "sparse", "bands"),
                 band_min_conf: float = 55.0):
        import pytesseract  # noqa: F401  (import 오류를 초기에 드러내기 위해)
        self.lang = lang
        self.min_conf = min_conf
        self.min_width = min_width
        self.try_inverted = try_inverted
        self.variants = tuple(variants)
        self.band_min_conf = band_min_conf

    def _run(self, gray, scale: float, psm: int, min_conf: float, y_offset: float = 0.0) -> list:
        """gray 는 이미 scale 배 확대된 상태. 반환 bbox 는 (원본 좌표계 + y_offset)."""
        import pytesseract
        from pytesseract import Output

        with _tesseract_env():
            data = pytesseract.image_to_data(
                gray, lang=self.lang, config=f"--psm {psm}", output_type=Output.DICT
            )
        lines: dict = {}
        for i in range(len(data["text"])):
            txt = (data["text"][i] or "").strip()
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1
            if not txt or conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            lines.setdefault(key, []).append((x, y, x + w, y + h, txt, conf))

        blocks = []
        for words in lines.values():
            words.sort(key=lambda t: t[0])
            text = " ".join(t[4] for t in words)
            if not _HAS_CONTENT.search(text):
                continue
            conf = sum(t[5] for t in words) / len(words)
            if conf < min_conf:
                continue
            x0 = min(t[0] for t in words)
            y0 = min(t[1] for t in words)
            x1 = max(t[2] for t in words)
            y1 = max(t[3] for t in words)
            hs = sorted(t[3] - t[1] for t in words)
            med_h = hs[len(hs) // 2]
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=(x0 / scale, y0 / scale + y_offset, x1 / scale, y1 / scale + y_offset),
                    conf=conf,
                    source="ocr",
                    height_px=med_h / scale,
                )
            )
        return blocks

    def _bands(self, gray_orig) -> list:
        H, W = gray_orig.shape[:2]
        bh = int(min(max(H * 0.16, 110), 420))
        step = max(1, int(bh * 0.65))
        scale = min(4.0, max(1.0, 420.0 / bh))
        out = []
        y = 0
        while y < H:
            y1 = min(H, y + bh)
            if y1 - y < 25 and y > 0:
                break
            strip = gray_orig[y:y1, :]
            big = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            out.extend(self._run(big, scale, 6, self.band_min_conf, y_offset=y))
            if y1 >= H:
                break
            y += step
        return merge_blocks([out], iou_thr=0.4)

    def recognize(self, image_path: str) -> list:
        img = load_bgr(image_path)
        H, W = img.shape[:2]
        gray0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        scale = max(1.0, self.min_width / W)
        gray = cv2.resize(gray0, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale > 1 else gray0

        result: list = []
        if "page" in self.variants:
            groups = [self._run(gray, scale, 6, self.min_conf)]
            if self.try_inverted:   # 어두운 배경 + 밝은 글자 보완
                groups.append(self._run(cv2.bitwise_not(gray), scale, 6, self.min_conf))
            blocks = sort_reading_order(merge_blocks(groups))
            for b in blocks:
                b.variant = "page"
            result += blocks
        if "sparse" in self.variants:
            blocks = sort_reading_order(self._run(gray, scale, 11, self.min_conf))
            for b in blocks:
                b.variant = "sparse"
            result += blocks
        if "bands" in self.variants:
            blocks = sort_reading_order(self._bands(gray0))
            for b in blocks:
                b.variant = "bands"
            result += blocks
        return result


class PaddleOCREngine(OCREngine):
    """PaddleOCR(PP-OCRv5) 2단계 엔진: 텍스트 탐지(det) → 줄 단위 인식(rec).

    paddleocr 의 통합 파이프라인(PaddleOCR 클래스) 대신 paddlex 의 모델을 직접 호출한다.
    이유: 이 PoC 개발 환경(paddlepaddle 3.3 CPU)에서
      - 탐지 모델은 oneDNN 이 켜져 있으면 오류가 나고,
      - 한국어 인식 모델은 oneDNN 이 꺼져 있으면 한글이 전부 공백으로 나오는
    문제가 있어, 모델별로 실행 모드를 다르게 줘야 했다 (파이프라인은 둘을 한 번에 설정).
    다른 버전/환경에서는 달라질 수 있으니 `ocr` 명령으로 먼저 확인할 것.

    폐쇄망: 모델 폴더를 사전 반입하고 opts 로 경로를 지정한다.
      {"det_model_dir": "D:/models/PP-OCRv5_mobile_det", "rec_model_dir": "D:/models/korean_PP-OCRv5_mobile_rec"}
    (모델 이름 변경: det_model_name / rec_model_name. 정확도가 더 필요하면 det 를 PP-OCRv5_server_det 로 — 메모리 6GB+ 사용)
    """
    name = "paddle"

    def __init__(self, lang: str = "korean", min_conf: float = 0.3, opts: Optional[dict] = None):
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")  # 폐쇄망에서 접속 확인 지연 방지
        opts = dict(opts or {})
        self.min_conf = min_conf
        self.pad = int(opts.pop("pad", 4))
        self.det_max_side = int(opts.pop("det_max_side", 2000))
        self.rec_batch = int(opts.pop("rec_batch", 8))
        # 작은 글씨(푸터·각주·심의필) 보강: 가로가 small_text_below 픽셀 미만이면 2배 확대본을 한 번 더 인식해 합친다.
        # 웹 화면 캡처(약 1500px)처럼 해상도가 낮은 이미지에서 심의필 번호 등이 누락되던 문제 대응. 0 이면 끔.
        self.small_text_below = int(opts.pop("small_text_below", 2400))
        self.small_text_scale = float(opts.pop("small_text_scale", 2.0))
        det_name = opts.pop("det_model_name", "PP-OCRv5_mobile_det")
        rec_name = opts.pop("rec_model_name", {"korean": "korean_PP-OCRv5_mobile_rec"}.get(lang, "PP-OCRv5_server_rec"))
        det_dir, rec_dir = opts.pop("det_model_dir", None), opts.pop("rec_model_dir", None)
        det_mode = opts.pop("det_run_mode", "paddle")      # oneDNN 끔
        rec_mode = opts.pop("rec_run_mode", None)          # 기본값(oneDNN 사용 가능 시 사용)

        from paddlex import create_model  # 지연 import (미설치 시 ImportError → CLI 가 안내)

        def build(name_, dir_, mode):
            kw = {"engine": "paddle_static", "engine_config": {"run_mode": mode}} if mode else {}
            return create_model(name_, model_dir=dir_, **kw)

        self._det = build(det_name, det_dir, det_mode)
        self._rec = build(rec_name, rec_dir, rec_mode)

    @staticmethod
    def _res(o):
        return o if isinstance(o, dict) else o.json["res"]

    def _crop_poly(self, img, pts):
        """탐지된 사각형(기울어진 글줄 포함)을 똑바로 펴서 잘라낸다. 기울어진 광고에서 축 정렬 crop 은
        옆 줄 글자가 섞이고 글자가 잘려 인식률이 크게 떨어졌다."""
        pts = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
        if len(pts) != 4:
            pts = cv2.boxPoints(cv2.minAreaRect(pts)).astype(np.float32)
        s_, d_ = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
        tl, br = pts[np.argmin(s_)], pts[np.argmax(s_)]
        tr, bl = pts[np.argmin(d_)], pts[np.argmax(d_)]
        w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
        h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
        if w < 2 or h < 2:
            return None
        pad = self.pad
        src = np.array([tl, tr, br, bl], dtype=np.float32)
        dst = np.array([[pad, pad], [w + pad, pad], [w + pad, h + pad], [pad, h + pad]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(src, dst)
        crop = cv2.warpPerspective(img, M, (w + 2 * pad, h + 2 * pad), flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REPLICATE)
        if crop.shape[0] >= 1.5 * crop.shape[1]:      # 세로로 긴 글줄은 눕힌다
            crop = np.rot90(crop)
        return crop

    def _recognize_img(self, img, scale: float = 1.0) -> list:
        det = self._res(next(iter(self._det.predict(img, limit_side_len=self.det_max_side, limit_type="max"))))
        boxes, crops = [], []
        for poly in det.get("dt_polys", []):
            pts = np.array(poly, dtype=float).reshape(-1, 2)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            crop = self._crop_poly(img, pts)
            if crop is None or crop.shape[0] < 4 or crop.shape[1] < 4:
                continue
            boxes.append((float(x0) / scale, float(y0) / scale, float(x1) / scale, float(y1) / scale))
            crops.append(crop)
        blocks = []
        if crops:
            for b, o in zip(boxes, self._rec.predict(crops, batch_size=self.rec_batch)):
                r = self._res(o)
                text, score = (r.get("rec_text") or "").strip(), float(r.get("rec_score", 0))
                if not text or score < self.min_conf or not _HAS_CONTENT.search(text):
                    continue
                blocks.append(TextBlock(text=text, bbox=b, conf=score * 100, source="ocr",
                                        height_px=b[3] - b[1], variant="paddle" if scale == 1.0 else "paddle-x2"))
        return blocks

    def recognize(self, image_path: str) -> list:
        img = load_bgr(image_path)
        H, W = img.shape[:2]
        groups = [self._recognize_img(img)]
        if self.small_text_below and W < self.small_text_below and self.small_text_scale > 1:
            big = cv2.resize(img, None, fx=self.small_text_scale, fy=self.small_text_scale, interpolation=cv2.INTER_CUBIC)
            groups.append(self._recognize_img(big, self.small_text_scale))
        return sort_reading_order(merge_blocks(groups) if len(groups) > 1 else groups[0])


def default_ocr_opts(root=None) -> dict:
    """폐쇄망용 기본 OCR 옵션. 우선순위: config/ocr.json > 저장소의 models/ 폴더 > (없으면 빈 값 = 라이브러리 기본 모델)."""
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    opts: dict = {}
    det, rec = base / "models" / "PP-OCRv5_mobile_det", base / "models" / "korean_PP-OCRv5_mobile_rec"
    if (det / "inference.yml").exists() and (rec / "inference.yml").exists():
        opts = {"det_model_dir": str(det), "rec_model_dir": str(rec)}
    cfg = base / "config" / "ocr.json"
    if cfg.exists():
        import json
        user = json.loads(cfg.read_text(encoding="utf-8"))
        for k, v in (user.get("paddle") or {}).items():
            if isinstance(v, str) and k.endswith("_dir") and not os.path.isabs(v):
                v = str(base / v)
            opts[k] = v
    return opts


def build_engine(name: str = "paddle", opts: Optional[dict] = None) -> OCREngine:
    opts = dict(opts or {})
    if name == "paddle":
        opts = {**default_ocr_opts(), **opts}
    if name == "tesseract":
        return TesseractEngine(**opts)
    if name == "paddle":
        return PaddleOCREngine(opts=opts)
    raise ValueError(f"알 수 없는 OCR 엔진: {name}")
