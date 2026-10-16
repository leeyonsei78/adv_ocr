# 포함된 OCR 모델 (폐쇄망 반입용)

| 폴더 | 용도 | 출처 |
|---|---|---|
| `PP-OCRv5_mobile_det` | 글줄 위치 탐지 | PaddleOCR PP-OCRv5 (PaddlePaddle) |
| `korean_PP-OCRv5_mobile_rec` | 한국어 글자 인식 | PaddleOCR PP-OCRv5 (PaddlePaddle) |

PaddleOCR 및 모델은 Apache License 2.0 입니다. 인터넷 없이 `python -m adreview web` 을 실행하면
이 폴더의 모델을 자동으로 사용합니다(`config/ocr.json` 으로 다른 경로 지정 가능).
정확도가 더 필요하면 서버용 탐지 모델(PP-OCRv5_server_det, 약 85MB, 메모리 6GB+)을 같은 방식으로 반입해 경로만 바꾸면 됩니다.
