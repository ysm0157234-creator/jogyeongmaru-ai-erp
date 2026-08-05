# v16.0 single Gemini + Serper fallback

- Serper가 웹/이미지 자료를 수집합니다.
- Gemini는 구조화 및 한국어 문장 생성을 위해 최대 1회만 호출합니다.
- Gemini 429, 미설정, 일시 오류가 발생해도 Serper 검색결과로 자동 초안을 생성합니다.
- 사진 검색과 선택에는 Gemini를 사용하지 않습니다.
- 화면 버전: v16.0-single-gemini-fallback
