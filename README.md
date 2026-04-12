# 청구항 분석 프로그램

`app.py`와 `app_gui.py`는 의견제출통지서와 명세서 PDF를 바탕으로 청구항 분석 결과를 생성합니다.

- 의견제출통지서 PDF에서 거절이유와 청구항 상태를 추출합니다.
- 명세서 PDF에서 청구항 본문과 위치를 추출합니다.
- 청구항별 분석 내용을 반영한 PDF를 생성합니다.
- HTML 보고서와 JSON 데이터도 함께 생성합니다.

## 실행 방법

```powershell
python app.py
```

또는

```powershell
python app_gui.py
```

## 생성 파일

- `output/청구항_분석_결과.pdf`
- `output/result.html`
- `output/claim_mapping.json`

## 참고

- 빨간 표시: 거절이유가 있는 청구항
- 초록 표시: 특허 가능한 청구항
