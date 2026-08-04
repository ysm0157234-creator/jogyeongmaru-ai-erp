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
    v11 원칙
    - Google Search Grounding을 호출하지 않는다.
    - Custom Search 결과를 한 번의 Gemini 요청으로만 구조화한다.
    - 모델 목록에서 generateContent 지원 모델만 선택한다.
    - 429가 발생하면 상위 서비스가 검색결과 기반 초안으로 대체할 수 있게
      GeminiQuotaError를 발생시킨다.
    """

    BUILD_VERSION = "v11.0-search-first"

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
    def _normalize_model_name(value: str) -> str:
        name = str(value or "").strip()
        if not name:
            return ""

        # SDK에는 일반적으로 gemini-... 형식을 전달한다.
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
        normalized = {str(action).lower() for action in actions}
        return (
            "generatecontent" in normalized
            or "generate_content" in normalized
        )

    def _available_model_ids(self) -> list[str]:
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
                    model_id = self._normalize_model_name(
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
                        "image",
                    )
                ):
                    continue

                found.append(model_id)
        except Exception:
            pass

        return list(dict.fromkeys(found))

    @staticmethod
    def _rank(model_id: str) -> tuple[int, int, int, str]:
        lowered = model_id.lower()
        return (
            0 if "flash" in lowered else 1,
            0 if "lite" in lowered else 1,
            1 if "preview" in lowered else 0,
            lowered,
        )

    def _model_candidates(self) -> list[str]:
        candidates: list[str] = []

        configured = self._normalize_model_name(
            self.configured_model
        )
        if configured:
            candidates.append(configured)

        candidates.extend(
            sorted(
                self._available_model_ids(),
                key=self._rank,
            )
        )

        # 목록 조회가 실패했을 때만 별칭 후보를 사용한다.
        if not candidates:
            candidates.extend(
                [
                    "gemini-flash-latest",
                    "gemini-3-flash-preview",
                ]
            )

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
            raise GeminiError(
                "Gemini 응답에 텍스트가 없습니다."
            )
        return text

    def structure_json(
        self,
        prompt: str,
    ) -> GeminiCallResult:
        errors_seen: list[str] = []

        for model_id in self._model_candidates():
            try:
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        max_output_tokens=1800,
                    ),
                )

                text = self._response_text(response)
                text = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    text,
                    flags=re.I,
                )
                text = re.sub(r"\s*```$", "", text).strip()

                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise GeminiError(
                        f"Gemini JSON 해석 실패: {text[:900]}"
                    ) from exc

                if not isinstance(data, dict):
                    raise GeminiError(
                        "Gemini JSON 결과가 객체 형식이 아닙니다."
                    )

                self.last_used_model = model_id
                return GeminiCallResult(
                    data=data,
                    model=model_id,
                )

            except errors.APIError as exc:
                message = str(exc)
                errors_seen.append(
                    f"{model_id}: {exc.code} {message[:280]}"
                )

                if exc.code == 429:
                    raise GeminiQuotaError(
                        "Gemini 무료 할당량이 초과되어 "
                        "Google 검색결과 기반 초안으로 전환합니다."
                    ) from exc

                # 모델 미지원/폐기면 다음 모델 시도
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
                    f"{model_id}: {type(exc).__name__}: "
                    f"{str(exc)[:280]}"
                )
                continue

        raise GeminiError(
            "사용 가능한 Gemini 모델 호출에 실패했습니다. "
            + " | ".join(errors_seen[:8])
        )
