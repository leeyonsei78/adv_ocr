"""공통 데이터 모델."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

BBox = tuple  # (x0, y0, x1, y1) 이미지 픽셀 좌표


def squash(text: str) -> str:
    """공백류를 모두 제거한 문자열 (OCR 공백 오류 보정용)."""
    return re.sub(r"\s+", "", text or "")


@dataclass
class TextBlock:
    text: str
    bbox: Optional[BBox] = None          # OCR 결과일 때만 존재
    conf: float = 100.0                  # 0~100 (native 텍스트는 100)
    source: str = "ocr"                  # ocr | native
    image: Optional[str] = None          # AdPage.images 의 키 (bbox 가 속한 이미지)
    height_px: Optional[float] = None    # OCR 글자(줄) 높이
    font_pt: Optional[float] = None      # native 텍스트의 글자 크기(pt), 알 수 없으면 None
    variant: Optional[str] = None        # OCR 처리 변형 (page / sparse / bands ...)

    def to_dict(self):
        return asdict(self)


@dataclass
class AdPage:
    """검토 단위 1건 = 단독 이미지 1장 / PPT 슬라이드 1장 / PDF 1페이지."""
    file: str
    label: str                                    # 예: "slide 3", "image"
    images: dict = field(default_factory=dict)    # key -> 이미지 파일 경로
    blocks: list = field(default_factory=list)    # list[TextBlock]
    warnings: list = field(default_factory=list)

    @property
    def page_id(self) -> str:
        return f"{self.file} / {self.label}"

    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass
class Finding:
    rule_id: str
    category: str            # required / prohibited / numeric / visual / ocr_quality
    severity: str            # high / medium / low / info
    title: str
    detail: str
    page: str                # AdPage.page_id
    matched_text: str = ""
    image: Optional[str] = None
    bbox: Optional[BBox] = None
    basis: str = ""          # 근거 규정 (룰 파일에 적힌 값)
    related: list = field(default_factory=list)   # 참고 조항 [{title, text, score, source}]
    status: str = "review"   # review(검토필요) / ok / info
    query: str = ""          # 관련 조항 검색용 질의 (비어 있으면 제목 등으로 대체)

    def to_dict(self):
        return asdict(self)


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
