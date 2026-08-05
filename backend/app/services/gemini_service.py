from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors, types

from app.core.config import get_settings


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiError(RuntimeError):
    pass


class GeminiQuotaError(GeminiError):
    pass


@dataclass
class GeminiCallResult:
    data: dict[str, Any]
    model: str


class GeminiService:
    BUILD_VERSION = "v17.0-web-image-single-gemini"

    FORBIDDEN_PHRASES = (
        "확인 필요",
        "공식자료 확인",
        "공식 자료 확인",
        "증빙자료 확인",
        "증빙 자료 확인",
        "최종 기재",
        "추후 기재",
        "자료 확인 후",
        "대표 꽃색",
        "대표 개화기",
        "성숙 초장 범위",
        "검색자료에 나타난 대표 꽃색",
        "검색자료에 나타난 대표 개화기",
        "자료에 기재된 성숙 크기",
    )

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.gemini_api_key.strip()
        self.configured_model = settings.gemini_model.strip()

        if not self.api_key:
            raise GeminiNotConfiguredError(
                "Render 환경변수 GEMINI_API_KEY가 누락되었습니다."
            )

        self.client = genai.Client(api_key=self.api_key)
        self.last_used_model: str | None = None

    @staticmethod
    def _normalize_model_id(value: str) -> str:
        name = str(value or "").strip()
        if name.startswith("models/"):
            name = name[len("models/"):]
        return name if re.fullmatch(r"gemini-[A-Za-z0-9._-]+", name) else ""

    @staticmethod
    def _supports_generate_content(model: Any) -> bool:
        actions = getattr(model, "supported_actions", None) or []
        if not actions:
            return True
        normalized = {str(action).lower().replace("_", "") for action in actions}
        return "generatecontent" in normalized

    @staticmethod
    def _model_priority(model_id: str) -> tuple[int, int, int, str]:
        lowered = model_id.lower()
        return (
            0 if "flash" in lowered else 1,
            0 if "lite" not in lowered else 1,
            1 if "preview" in lowered else 0,
            lowered,
        )

    def _available_models(self) -> list[str]:
        found: list[str] = []
        try:
            for model in self.client.models.list():
                if not self._supports_generate_content(model):
                    continue
                for candidate in (
                    getattr(model, "base_model_id", None),
                    getattr(model, "name", None),
                ):
                    model_id = self._normalize_model_id(str(candidate or ""))
                    if model_id:
                        break
                else:
                    continue

                lowered = model_id.lower()
                if any(blocked in lowered for blocked in (
                    "embedding", "imagen", "veo", "tts", "live", "image-generation"
                )):
                    continue
                found.append(model_id)
        except Exception:
            return []

        return sorted(list(dict.fromkeys(found)), key=self._model_priority)

    def _model_candidates(self) -> list[str]:
        candidates: list[str] = []
        configured = self._normalize_model_id(self.configured_model)
        if configured:
            candidates.append(configured)
        candidates.extend(self._available_models())
        if not candidates:
            candidates.extend(("gemini-flash-latest", "gemini-3-flash-preview"))
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _response_text(response: Any) -> str:
        text = str(getattr(response, "text", "") or "").strip()
        if text:
            return text

        parts: list[str] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                value = getattr(part, "text", None)
                if value:
                    parts.append(str(value))

        text = "".join(parts).strip()
        if not text:
            raise GeminiError("Gemini 응답에 텍스트가 없습니다.")
        return text

    @staticmethod
    def _clean_json_text(text: str) -> str:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
        return re.sub(r"\s*```$", "", cleaned).strip()

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @staticmethod
    def _sentence_count(value: str) -> int:
        return len([s for s in re.split(r"(?<=[.!?다])\s+", value.strip()) if s.strip()])

    @staticmethod
    def _looks_like_full_scientific_name(value: str) -> bool:
        return bool(re.match(
            r"^[A-Z][a-z-]+\s+(?:×\s*)?[a-z][a-z-]+"
            r"(?:\s+['\"][^'\"]+['\"])?"
            r"(?:\s+[A-Z][A-Za-z.\- ]+)?$",
            value.strip(),
        ))

    @staticmethod
    def _looks_like_flower_color(value: str) -> bool:
        text = value.strip()
        if len(text) < 2:
            return False
        if text in ("대표", "색상", "꽃색", "미상", "없음", "해당 없음"):
            return False
        return any(term in text for term in (
            "흰", "백", "크림", "노랑", "황", "주황", "적", "빨강",
            "분홍", "자주", "보라", "청", "파랑", "녹", "은회", "갈", "아이보리"
        ))

    @staticmethod
    def _looks_like_flowering_period(value: str) -> bool:
        text = value.strip()
        if re.search(r"\d{1,2}\s*월", text):
            return True
        return text in ("초봄", "봄", "늦봄", "초여름", "여름", "늦여름", "가을", "겨울")

    @staticmethod
    def _looks_like_height(value: str) -> bool:
        return bool(re.search(
            r"\d+(?:\.\d+)?(?:\s*[~\-–]\s*\d+(?:\.\d+)?)?\s*(?:cm|㎝)",
            value.strip(), flags=re.I,
        ))

    def _validate_profile(self, data: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        for field in (
            "matched_name", "scientific_name", "characteristics_draft", "breeding_process_draft"
        ):
            if not self._normalize_text(data.get(field)):
                problems.append(f"{field} 값이 비어 있습니다.")

        classification = data.get("classification")
        if not isinstance(classification, dict):
            problems.append("classification이 객체 형식이 아닙니다.")
            classification = {}

        scientific_name = self._normalize_text(data.get("scientific_name"))
        if scientific_name and not self._looks_like_full_scientific_name(scientific_name):
            problems.append("scientific_name이 속명+종명 형태의 풀 학명이 아닙니다.")

        if not self._looks_like_flower_color(self._normalize_text(classification.get("flower_color"))):
            problems.append("flower_color에 실제 꽃색이 없습니다.")
        if not self._looks_like_flowering_period(self._normalize_text(classification.get("flowering_period"))):
            problems.append("flowering_period가 월 범위 또는 명확한 계절이 아닙니다.")
        if not self._looks_like_height(self._normalize_text(classification.get("height"))):
            problems.append("height가 cm 단위의 실제 수치가 아닙니다.")

        characteristics = self._normalize_text(data.get("characteristics_draft"))
        if characteristics:
            if self._sentence_count(characteristics) < 4:
                problems.append("characteristics_draft가 너무 짧습니다.")
            if "http://" in characteristics or "https://" in characteristics:
                problems.append("characteristics_draft에 URL이 포함되어 있습니다.")

        breeding = self._normalize_text(data.get("breeding_process_draft"))
        if breeding and self._sentence_count(breeding) < 3:
            problems.append("breeding_process_draft가 너무 짧습니다.")

        combined = json.dumps(data, ensure_ascii=False)
        for phrase in self.FORBIDDEN_PHRASES:
            if phrase in combined:
                problems.append(f"금지 문구가 포함되어 있습니다: {phrase}")
        return problems

    def _generate_json(self, *, model_id: str, prompt: str, max_output_tokens: int = 3200) -> dict[str, Any]:
        response = self.client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                max_output_tokens=max_output_tokens,
            ),
        )
        cleaned = self._clean_json_text(self._response_text(response))
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise GeminiError(f"Gemini JSON 해석 실패: {cleaned[:1400]}") from exc
        if not isinstance(data, dict):
            raise GeminiError("Gemini 응답이 JSON 객체가 아닙니다.")
        return data

    def _repair_prompt(
        self,
        *,
        original_prompt: str,
        current_data: dict[str, Any],
        problems: list[str],
    ) -> str:
        problem_text = "\n".join(f"- {problem}" for problem in problems)
        current_json = json.dumps(current_data, ensure_ascii=False, indent=2)
        return f"""
아래는 식물 신고서용 JSON을 생성하는 원래 요청이다.

[원래 요청]
{original_prompt}

[현재 JSON]
{current_json}

[수정해야 할 문제]
{problem_text}

JSON 전체를 다시 작성하라.
1. scientific_name은 반드시 속명+종명 형식으로 작성하고 가능한 경우 품종명과 명명자를 포함한다.
2. flower_color에는 실제 색상만 쓴다.
3. flowering_period는 가능한 경우 '4~5월'처럼 월 범위로 쓴다.
4. height는 반드시 cm 단위 수치 또는 범위로 쓴다.
5. characteristics_draft는 검색문장을 붙여 넣지 말고 국립종자원 신고서 문체로 5~8문장 새로 작성한다.
6. breeding_process_draft는 4~6문장으로 작성한다.
7. URL과 출처 번호를 본문에 넣지 않는다.
8. '확인 필요', '대표 꽃색', '대표 개화기', '성숙 초장 범위', '증빙자료 확인 후'를 쓰지 않는다.
9. JSON 이외에는 출력하지 않는다.
"""

    def structure_json(self, prompt: str) -> GeminiCallResult:
        errors_seen: list[str] = []
        for model_id in self._model_candidates():
            try:
                data = self._generate_json(model_id=model_id, prompt=prompt)
                problems = self._validate_profile(data)
                if problems:
                    data = self._generate_json(
                        model_id=model_id,
                        prompt=self._repair_prompt(
                            original_prompt=prompt,
                            current_data=data,
                            problems=problems,
                        ),
                    )
                    remaining = self._validate_profile(data)
                    if remaining:
                        raise GeminiError(
                            "Gemini 결과 품질 검증 실패: " + " / ".join(remaining)
                        )

                self.last_used_model = model_id
                return GeminiCallResult(data=data, model=model_id)

            except errors.APIError as exc:
                message = str(exc)
                errors_seen.append(f"{model_id}: {exc.code} {message[:350]}")
                if exc.code == 429:
                    raise GeminiQuotaError("Gemini 무료 할당량을 초과했습니다.") from exc
                if exc.code in (400, 404):
                    continue
                if exc.code in (401, 403):
                    raise GeminiError(f"Gemini 인증 또는 권한 오류: {message}") from exc
            except GeminiError as exc:
                errors_seen.append(f"{model_id}: {str(exc)[:500]}")
                continue
            except Exception as exc:
                errors_seen.append(
                    f"{model_id}: {type(exc).__name__}: {str(exc)[:350]}"
                )
                continue

        raise GeminiError(
            "사용 가능한 Gemini 모델에서 적합한 식물 프로필을 생성하지 못했습니다. "
            + " | ".join(errors_seen[:8])
        )

    def structure_plant_profile(
        self,
        *,
        variety_name: str,
        agency: str,
        source_text: str,
    ) -> GeminiCallResult:
        prompt = f"""
당신은 대한민국 국립종자원 및 산림청의 식물 품종 생산·수입판매 신고자료를 작성하는 전문 조사자이다.

입력 식물 또는 품종명:
{variety_name}

신고 기관:
{agency}

아래 내용은 Serper 검색으로 수집한 해외 식물원, 공식 원예기관, 육종사, 공급사 및 식물 데이터베이스의 자료다.

검색자료:
{source_text}

다음 기준을 지켜 JSON을 작성하라.
1. 입력 식물과 직접 관련된 자료만 사용한다.
2. 영어 검색문장을 그대로 이어 붙이지 않는다.
3. 내용을 자연스럽게 한국어로 번역하고 중복을 제거한다.
4. 국립종자원 제출용 객관적 문체로 다시 작성한다.
5. scientific_name은 속명만 쓰지 않는다.
6. 가능한 경우 속명+종명+품종명+명명자를 모두 포함한다.
7. flower_color에는 실제 꽃색과 색상 변화를 작성한다.
8. flowering_period는 가능한 경우 월 범위로 작성한다.
9. height는 반드시 cm 단위로 작성한다.
10. feet와 m는 cm로 환산한다.
11. 여러 자료의 값이 다르면 신뢰 가능한 전체 범위를 통합한다.
12. '확인 필요', '대표 꽃색', '대표 개화기', '성숙 초장 범위', '증빙자료 확인 후'를 쓰지 않는다.
13. 특성 설명은 5~8문장으로 새로 작성한다.
14. 육성과정은 4~6문장으로 새로 작성한다.
15. JSON 이외에는 출력하지 않는다.

반환 형식:
{{
  "matched_name": "입력과 일치하는 정확한 이름",
  "korean_name": "한국어 통용명",
  "scientific_name": "속명+종명+품종명+명명자를 포함한 풀 학명",
  "genus": "속명",
  "species": "종소명",
  "cultivar": "품종명 또는 빈 문자열",
  "origin": "원산지 또는 육성 지역",
  "propagation_method": "대표 증식방법",
  "classification": {{
    "plant_type": "구체적인 식물 유형",
    "horticultural_group": "원예 분류",
    "flowering_period": "예: 6~7월",
    "flower_color": "예: 크림백색",
    "height": "예: 150~450 cm",
    "use": "주요 이용"
  }},
  "characteristics_draft": "신고용 특성 설명 5~8문장",
  "breeding_process_draft": "선발·육종·증식 과정 4~6문장",
  "research_notes": []
}}
"""
        return self.structure_json(prompt)
