"""입력 파일(이미지 / PPTX / PDF)에서 AdPage 목록을 만든다.

PPTX 처리 전략 (광고물은 이미지 위에 글자를 얹거나 도형·그룹 안에 글자를 넣는 일이 많다)
  1) 네이티브 텍스트  : 텍스트 상자·표·그룹 도형 안의 글자 (OCR 불필요, 정확)
  2) 삽입 이미지 OCR  : 슬라이드에 들어 있는 그림을 원본 해상도로 OCR (작은 각주 문구 대비)
  3) 슬라이드 렌더링 OCR : LibreOffice 로 슬라이드 전체를 이미지로 만들어 OCR (눈에 보이는 그대로)
  세 경로의 결과를 한 슬라이드 안에서 합친다 (중복은 점검 단계에서 제거).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import AdPage, TextBlock
from .ocr import OCREngine

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}


# ----------------------------------------------------------------------------
# 이미지
# ----------------------------------------------------------------------------
def extract_image(path: str, engine: OCREngine) -> list:
    page = AdPage(file=os.path.basename(path), label="image", images={"main": path})
    blocks = engine.recognize(path)
    for b in blocks:
        b.image = "main"
    page.blocks = blocks
    return [page]


# ----------------------------------------------------------------------------
# PDF  (광고 PDF 입력용: 텍스트 레이어 + 페이지 렌더링 OCR)
# ----------------------------------------------------------------------------
def render_pdf_pages(pdf_path: str, out_dir: str, dpi: int = 200) -> list:
    import pymupdf

    paths = []
    doc = pymupdf.open(pdf_path)
    zoom = dpi / 72
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        p = os.path.join(out_dir, f"{Path(pdf_path).stem}_p{i:03d}.png")
        pix.save(p)
        paths.append(p)
    doc.close()
    return paths


def extract_pdf(path: str, engine: OCREngine, workdir: str) -> list:
    import pymupdf

    pages = []
    imgs = render_pdf_pages(path, workdir)
    doc = pymupdf.open(path)
    for i, (img, pg) in enumerate(zip(imgs, doc), start=1):
        page = AdPage(file=os.path.basename(path), label=f"page {i}", images={"render": img})
        native = pg.get_text("text").strip()
        if native:
            for line in native.splitlines():
                if line.strip():
                    page.blocks.append(TextBlock(text=line.strip(), source="native"))
        for b in engine.recognize(img):
            b.image = "render"
            page.blocks.append(b)
        pages.append(page)
    doc.close()
    return pages


# ----------------------------------------------------------------------------
# PPTX
# ----------------------------------------------------------------------------
def _iter_shapes(shapes):
    """그룹 도형을 재귀적으로 풀어서 순회."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(sh.shapes)
        else:
            yield sh


def _paragraph_blocks(tf) -> list:
    out = []
    for para in tf.paragraphs:
        text = "".join(r.text for r in para.runs).strip() or para.text.strip()
        if not text:
            continue
        sizes = [r.font.size.pt for r in para.runs if r.font is not None and r.font.size is not None]
        out.append(TextBlock(text=text, source="native", font_pt=min(sizes) if sizes else None))
    return out


def native_slide_blocks(slide) -> tuple:
    """(텍스트 블록 목록, [(이미지 blob, 확장자), ...])"""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    blocks, pictures = [], []
    for sh in _iter_shapes(slide.shapes):
        if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
            try:
                pictures.append((sh.image.blob, sh.image.ext))
            except Exception:
                pass
        if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
            blocks.extend(_paragraph_blocks(sh.text_frame))
        if getattr(sh, "has_table", False) and sh.has_table:
            for row in sh.table.rows:
                for cell in row.cells:
                    blocks.extend(_paragraph_blocks(cell.text_frame))
    return blocks, pictures


def render_pptx_to_pngs(pptx_path: str, out_dir: str, dpi: int = 200, timeout: int = 240) -> list:
    """LibreOffice → PDF → PNG. 실패하면 빈 목록과 사유를 반환."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return [], "LibreOffice(soffice)를 찾을 수 없어 슬라이드 렌더링을 건너뜀"
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    try:
        cmd = [soffice, f"-env:UserInstallation=file://{profile}", "--headless",
               "--convert-to", "pdf", "--outdir", out_dir, pptx_path]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        pdf = os.path.join(out_dir, Path(pptx_path).stem + ".pdf")
        if proc.returncode != 0 or not os.path.exists(pdf):
            return [], f"LibreOffice 변환 실패: {proc.stderr.decode(errors='ignore')[:200]}"
        return render_pdf_pages(pdf, out_dir, dpi=dpi), None
    except subprocess.TimeoutExpired:
        return [], "LibreOffice 변환 시간 초과"
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def extract_pptx(path: str, engine: OCREngine, workdir: str, render_dpi: int = 200) -> list:
    from pptx import Presentation

    prs = Presentation(path)
    stem = Path(path).stem
    rendered, warn = render_pptx_to_pngs(path, workdir, dpi=render_dpi)
    pages = []
    for idx, slide in enumerate(prs.slides, start=1):
        page = AdPage(file=os.path.basename(path), label=f"slide {idx}")
        if warn:
            page.warnings.append(warn)

        native, pictures = native_slide_blocks(slide)
        page.blocks.extend(native)

        # 삽입 이미지 원본 OCR
        for k, (blob, ext) in enumerate(pictures, start=1):
            key = f"img{k}"
            p = os.path.join(workdir, f"{stem}_s{idx:03d}_{key}.{ext or 'png'}")
            with open(p, "wb") as f:
                f.write(blob)
            page.images[key] = p
            try:
                for b in engine.recognize(p):
                    b.image = key
                    page.blocks.append(b)
            except Exception as e:  # 이미지 형식 미지원(emf, wmf 등)
                page.warnings.append(f"삽입 이미지 {k} OCR 실패({ext}): {e}")

        # 슬라이드 렌더링 OCR
        if idx - 1 < len(rendered):
            r = rendered[idx - 1]
            page.images["render"] = r
            for b in engine.recognize(r):
                b.image = "render"
                page.blocks.append(b)
        pages.append(page)
    return pages


# ----------------------------------------------------------------------------
# 진입점
# ----------------------------------------------------------------------------
def extract_any(path: str, engine: OCREngine, workdir: str) -> list:
    ext = Path(path).suffix.lower()
    os.makedirs(workdir, exist_ok=True)
    if ext in IMAGE_EXTS:
        return extract_image(path, engine)
    if ext == ".pptx":
        return extract_pptx(path, engine, workdir)
    if ext == ".pdf":
        return extract_pdf(path, engine, workdir)
    if ext == ".ppt":
        raise ValueError(".ppt(구형 형식)는 지원하지 않습니다. PowerPoint/LibreOffice 에서 .pptx 로 저장 후 사용하세요.")
    raise ValueError(f"지원하지 않는 형식: {ext}")
