# SUNNY 9조 Streamlit 챗봇 UI

배경 이미지와 써니 캐릭터를 적용한 품질 데이터 챗봇 UI 데모입니다.

## 가장 빠른 실행 방법 (Windows)

1. ZIP 파일의 압축을 풉니다.
2. 폴더 안의 `실행하기.bat`를 더블 클릭합니다.
3. 처음 실행할 때 필요한 패키지가 자동으로 설치됩니다.
4. 브라우저가 열리면 화면을 확인합니다.

## 터미널에서 직접 실행

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 현재 구현된 기능

- 운동장 배경 이미지
- 써니 캐릭터 프로필
- ChatGPT 형태의 채팅 화면
- 새 채팅 및 최근 질문 표시
- 처리 단계 상태 메시지
- 결과 데이터 표
- 자동 그래프
- SQL 및 검증 정보 펼쳐보기
- 추천 질문 버튼
- 데모 응답

## 실제 API 연결 위치

`app.py` 안의 아래 함수를 팀 백엔드 API 호출 코드로 교체하면 됩니다.

```python
def create_demo_result(question: str):
    ...
```

실제 API 응답은 다음 정보를 반환하도록 맞추면 화면 연결이 쉽습니다.

```json
{
  "answer": "분석 답변",
  "data": [
    {"제품군": "UFS", "불량건수": 18}
  ],
  "table": "quality_data",
  "recognized_columns": ["제품군", "lvd_cnt"],
  "sql": "SELECT ...",
  "validation": "passed",
  "chart": {
    "type": "bar",
    "x": "제품군",
    "y": "불량건수"
  }
}
```

## 이미지 파일

- `assets/sunny_bg.png`: 전체 배경
- `assets/sunny_avatar.png`: 챗봇 프로필 이미지
