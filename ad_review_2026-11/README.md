# 생명보험 광고 검수 (2026-11)

AI 광고 검수 결과와 담당자 검수 결과를 비교한 작업 파일 모음입니다.

- `input/standards/` 검수 기준: 점검표(txt), 규정·시행세칙(docx), 사내 지침 G07(pdf), 2022 법령집(pdf)
- `input/ads/` 검수 대상 광고 A~Z 26건(pptx, xlsx, 이미지). 파일명의 한글이 업로드 과정에서 밑줄로 바뀌었으므로 앞의 알파벳으로 구분. 이미지(`*-image.jpg`) 5개는 D, E, G, V, Y
- `input/reviewer/` 담당자 원본 검수 엑셀(`…261111.xlsx`)과 담당자 회신 메일 캡처(AI 활용 관련 준법 의견)
- `results/` 결과 엑셀. 최종본은 `광고검수_담당자vsClaude_비교_최종2.xlsx`(광고물 목록·집계 시트 포함, 이전 최종본은 `…_최종.xlsx`), 나머지는 단계별 중간 버전
- `광고물_개수.md` 광고물 개수 정리(소재 130개, 변형 포함 171개)
- `scripts/` 결과 엑셀을 만든 파이썬 스크립트(`build_review.py`, 차수별 `update_*.py`, 완화 기준 반영 `update_relax.py`, 광고물 목록 추가 `add_inventory.py`)
