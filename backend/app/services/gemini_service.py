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
    """
    Serper 검색 결과를 신고서용 한국어 JSON으로 구조화한다.

    주요 원칙
    - 검색 결과를 그대로 붙여넣지 않는다.
    - 영어 문장을 한국어 신고서 문체로 다시 작성한다.
    - 학명, 꽃색, 개화기, 초장에 임시 문구를 넣지 않는다.
    - 현재 API 키에서 실제 사용 가능한 모델을 자동 선택한다.
    """

    BUILD_VERSION = "v14.0-official-profile"

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

        if re.fullmatch(r"gemini-[A-Za-z0-9._-]+", name):
            return name

        return ""

    @staticmethod
    def _supports_generate_content(model: Any) -> bool:
        actions = getattr(model, "supported_actions", None) or []

        if not actions:
            return True

        normalized = {
            str(action).lower().replace("_", "")
            for action in actions
        }

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

                candidates = [
                    getattr(model, "base_model_id", None),
                    getattr(model, "name", None),
                ]

                model_id = ""

                for candidate in candidates:
                    model_id = self._normalize_model_id(
                        str(candidate or "")
                    )
                    if model_id:
                        break

                if not model_id:
                    continue

                lowered = model_id.lower()

                if any(
                    blocked in lowered
                    for blocked in (
                        "embedding",
                        "imagen",
                        "veo",
                        "tts",
                        "live",
                        "image-generation",
                    )
                ):
                    continue

                found.append(model_id)

        except Exception:
            return []

        return sorted(
            list(dict.fromkeys(found)),
            key=self._model_priority,
        )

    def _model_candidates(self) -> list[str]:
        candidates: list[str] = []

        configured = self._normalize_model_id(
            self.configured_model
        )

        if configured:
            candidates.append(configured)

        candidates.extend(self._available_models())

        if not candidates:
            candidates.extend(
                [
                    "gemini-3.6-flash",
                    "gemini-3.5-flash",
                    "gemini-flash-latest",
                ]
            )

        return list(dict.fromkeys(candidates))

    @staticmethod
    def _response_text(response: Any) -> str:
        text = str(
            getattr(response, "text", "") or ""
        ).strip()

        if text:
            return text

        parts: list[str] = []

        for candidate in getattr(
            response,
            "candidates",
            None,
        ) or []:
            content = getattr(
                candidate,
                "content",
                None,
            )

            for part in getattr(
                content,
                "parts",
                None,
            ) or []:
                value = getattr(part, "text", None)

                if value:
                    parts.append(str(value))

        text = "".join(parts).strip()

        if not text:
            raise GeminiError(
                "Gemini 응답에 텍스트가 없습니다."
            )

        return text

    @staticmethod
    def _clean_json_text(text: str) -> str:
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            text.strip(),
            flags=re.I,
        )
        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        ).strip()

        return cleaned

    @staticmethod
    def _validate_profile(data: dict[str, Any]) -> None:
        required_text_fields = (
            "matched_name",
            "scientific_name",
            "characteristics_draft",
            "breeding_process_draft",
        )

        for field in required_text_fields:
            if not str(data.get(field, "")).strip():
                raise GeminiError(
                    f"Gemini 결과에 {field} 값이 없습니다."
                )

        classification = data.get("classification")

        if not isinstance(classification, dict):
            raise GeminiError(
                "Gemini 결과의 classification 형식이 올바르지 않습니다."
            )

        required_classification = (
            "flower_color",
            "flowering_period",
            "height",
            "plant_type",
            "use",
        )

        for field in required_classification:
            if not str(
                classification.get(field, "")
            ).strip():
                raise GeminiError(
                    f"Gemini 결과에 classification.{field} 값이 없습니다."
                )

        forbidden_phrases = (
            "확인 필요",
            "공식자료 확인",
            "공식 자료 확인",
            "증빙자료 확인",
            "증빙 자료 확인",
            "최종 기재",
            "추후 기재",
            "자료 확인 후",
        )

        combined = json.dumps(
            data,
            ensure_ascii=False,
        )

        for phrase in forbidden_phrases:
            if phrase in combined:
                raise GeminiError(
                    f"Gemini 결과에 금지 문구가 포함되어 있습니다: {phrase}"
                )

    def structure_plant_profile(
        self,
        *,
        variety_name: str,
        agency: str,
        source_text: str,
    ) -> GeminiCallResult:
        prompt = f"""
당신은 대한민국 국립종자원 및 산림청 식물 품종
생산·수입판매 신고자료를 작성하는 전문 조사자이다.

입력 식물명:
{variety_name}

신고 기관:
{agency}

아래 자료는 Serper 검색을 통해 수집한 해외 원예기관,
식물원, 육종사, 공급사 및 식물 데이터베이스의 검색 결과이다.

검색자료:
{source_text}

반드시 다음 기준을 지켜라.

1. 입력한 식물 또는 품종과 직접 관련된 자료만 사용한다.
2. 검색결과의 영어 문장을 그대로 이어 붙이지 않는다.
3. 검색자료를 자연스러운 한국어로 번역하고 중복 내용을 제거한다.
4. 국립종자원 신고서에 들어갈 수 있는 객관적인 문체로 다시 작성한다.
5. 학명은 속명만 적지 말고 종명, 품종명, 명명자 표기가 확인되면 포함한다.
6. 입력값이 속명처럼 범위가 넓더라도 검색 결과에서 특정 종을 임의로 하나 선택하지 않는다.
7. 꽃색상은 '대표 꽃색' 같은 임시 문구를 쓰지 말고 실제 색상을 쓴다.
8. 개화기는 '봄·여름'처럼 막연하게 적기보다 확인되는 월 범위가 있으면 월로 적는다.
9. 초장은 cm로 통일한다. m는 cm로 변환하고 ft는 cm로 환산한다.
10. 여러 자료의 수치가 다르면 전체적으로 신뢰할 수 있는 범위로 통합한다.
11. '확인 필요', '증빙자료 확인 후 기재', '공식자료 확인 후 입력',
    '최종 기재' 같은 문구를 절대 사용하지 않는다.
12. 검색자료에서 정확한 육종자나 선발연도가 확인되지 않는 경우에도
    확인 필요라는 문구를 쓰지 말고, 해당 식물의 일반적인 선발·증식 과정을
    사실에 어긋나지 않는 범위에서 설명한다.
13. 특성 설명은 5~8문장으로 새롭게 작성한다.
14. 육성과정은 4~6문장으로 새롭게 작성한다.
15. JSON 이외의 설명은 출력하지 않는다.

반환 형식:

{{
  "matched_name": "입력 식물과 일치하는 정확한 이름",
  "korean_name": "한국어 통용명 또는 자연스러운 한글명",
  "scientific_name": "속명+종명+품종명+명명자까지 가능한 풀 학명",
  "genus": "속명",
  "species": "종소명",
  "cultivar": "품종명 또는 빈 문자열",
  "origin": "원산지 또는 육성 지역",
  "propagation_method": "대표 증식방법",
  "classification": {{
    "plant_type": "구체적인 식물 유형",
    "horticultural_group": "원예 분류",
    "flowering_period": "예: 6~7월",
    "flower_color": "예: 크림백색 또는 황금색에서 주황색으로 변화",
    "height": "예: 150~450 cm",
    "use": "구체적인 주요 이용"
  }},
  "characteristics_draft": "국립종자원 신고용 특성 설명 5~8문장",
  "breeding_process_draft": "선발·육종·증식 과정을 설명한 4~6문장",
  "source_summary": [
    {{
      "claim": "반영한 주요 정보",
      "source_numbers": [1, 2]
    }}
  ]
}}
"""

        errors_seen: list[str] = []

        for model_id in self._model_candidates():
            try:
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.15,
                        response_mime_type="application/json",
                        max_output_tokens=3000,
                    ),
                )

                text = self._response_text(response)
                cleaned = self._clean_json_text(text)

                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    raise GeminiError(
                        f"Gemini JSON 해석 실패: {cleaned[:1200]}"
                    ) from exc

                if not isinstance(data, dict):
                    raise GeminiError(
                        "Gemini 응답이 JSON 객체가 아닙니다."
                    )

                self._validate_profile(data)

                self.last_used_model = model_id

                return GeminiCallResult(
                    data=data,
                    model=model_id,
                )

            except errors.APIError as exc:
                message = str(exc)

                errors_seen.append(
                    f"{model_id}: {exc.code} {message[:300]}"
                )

                if exc.code == 429:
                    raise GeminiQuotaError(
                        "Gemini 무료 할당량을 초과했습니다."
                    ) from exc

                if exc.code in (400, 404):
                    continue

                if exc.code in (401, 403):
                    raise GeminiError(
                        f"Gemini 인증 또는 권한 오류: {message}"
                    ) from exc

            except GeminiError:
                raise

            except Exception as exc:
                errors_seen.append(
                    f"{model_id}: "
                    f"{type(exc).__name__}: "
                    f"{str(exc)[:300]}"
                )
                continue

        raise GeminiError(
            "사용 가능한 Gemini 모델 호출에 실패했습니다. "
            + " | ".join(errors_seen[:8])
        )
