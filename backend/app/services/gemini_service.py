from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from google import genai
from google.genai import types

from app.core.config import get_settings


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiError(RuntimeError):
    pass


@dataclass
class GeminiCallResult:
    text: str
    model: str
    response: Any


class GeminiService:
    """Google Gen AI SDK 기반 Gemini 호출 서비스.

    Render의 GEMINI_MODEL이 비어 있거나 현재 계정에서 사용할 수 없으면
    models.list() 결과에서 generateContent 가능한 Flash 계열 모델을 우선 선택한다.
    """

    PREFERRED_MODELS = (
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    )

    def __init__(self) -> None:
        settings = get_settings()
        api_key = settings.gemini_api_key.strip()
        if not api_key:
            raise GeminiNotConfiguredError(
                "Render 환경변수 GEMINI_API_KEY가 누락되었습니다."
            )

        self.client = genai.Client(api_key=api_key)
        self.configured_model = settings.gemini_model.strip()
        self._available_models: list[str] | None = None
        self.last_used_model: str | None = None

    @staticmethod
    def _clean_model_name(value: str) -> str:
        name = str(value or "").strip()
        if name.startswith("models/"):
            name = name.split("/", 1)[1]
        return name

    @staticmethod
    def _supports_generate_content(model: Any) -> bool:
        actions = (
            getattr(model, "supported_actions", None)
            or getattr(model, "supported_generation_methods", None)
            or []
        )
        if not actions:
            return True
        lowered = {str(action).lower() for action in actions}
        return any("generatecontent" in action.replace("_", "") for action in lowered)

    def list_available_models(self, *, refresh: bool = False) -> list[str]:
        if self._available_models is not None and not refresh:
            return list(self._available_models)

        found: list[str] = []
        try:
            for model in self.client.models.list():
                raw_name = getattr(model, "name", "")
                name = self._clean_model_name(raw_name)
                if not name or not self._supports_generate_content(model):
                    continue
                lowered = name.lower()
                if "gemini" not in lowered:
                    continue
                if any(skip in lowered for skip in ("embedding", "imagen", "veo", "live", "tts")):
                    continue
                found.append(name)
        except Exception as exc:
            # 목록 조회 실패가 실제 생성 호출까지 막아서는 안 된다.
            if self.configured_model:
                found.append(self._clean_model_name(self.configured_model))
            if not found:
                raise GeminiError(f"Gemini 사용 가능 모델 조회 실패: {exc}") from exc

        self._available_models = list(dict.fromkeys(found))
        return list(self._available_models)

    def _model_candidates(self) -> list[str]:
        available = self.list_available_models()
        available_set = set(available)
        candidates: list[str] = []

        configured = self._clean_model_name(self.configured_model)
        if configured:
            candidates.append(configured)

        for preferred in self.PREFERRED_MODELS:
            if preferred in available_set:
                candidates.append(preferred)

        # Flash 계열 우선, 그 다음 나머지 generateContent 모델
        candidates.extend(
            sorted(
                (name for name in available if "flash" in name.lower()),
                key=lambda name: (
                    "preview" not in name.lower(),
                    "lite" in name.lower(),
                    name,
                ),
            )
        )
        candidates.extend(available)
        return list(dict.fromkeys(name for name in candidates if name))

    @staticmethod
    def _response_text(response: Any) -> str:
        text = str(getattr(response, "text", "") or "").strip()
        if text:
            return text

        candidates = getattr(response, "candidates", None) or []
        pieces: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                value = getattr(part, "text", None)
                if value:
                    pieces.append(str(value))
        text = "".join(pieces).strip()
        if not text:
            raise GeminiError("Gemini 응답에 텍스트가 없습니다.")
        return text

    def _generate(
        self,
        prompt: str,
        *,
        config_factory,
        operation_name: str,
    ) -> GeminiCallResult:
        errors: list[str] = []
        candidates = self._model_candidates()
        if not candidates:
            raise GeminiError("현재 API 키에서 generateContent 가능한 Gemini 모델을 찾지 못했습니다.")

        for model_name in candidates:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config_factory(),
                )
                text = self._response_text(response)
                self.last_used_model = model_name
                return GeminiCallResult(text=text, model=model_name, response=response)
            except Exception as exc:
                message = str(exc)
                errors.append(f"{model_name}: {type(exc).__name__}: {message[:350]}")
                lowered = message.lower()
                # 인증/과금/쿼터 오류는 모델을 바꿔도 대부분 동일하므로 조기 종료
                if any(marker in lowered for marker in (
                    "api key not valid",
                    "permission denied",
                    "billing",
                    "quota exceeded",
                    "resource_exhausted",
                )):
                    break

        raise GeminiError(
            f"Gemini {operation_name}에 실패했습니다. 시도한 모델: "
            + " | ".join(errors[:8])
        )

    @staticmethod
    def _grounding_sources(response: Any) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        seen: set[str] = set()
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            chunks = getattr(metadata, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                uri = str(getattr(web, "uri", "") or "").strip()
                if not uri or uri in seen:
                    continue
                seen.add(uri)
                title = str(getattr(web, "title", "") or uri).strip()
                sources.append(
                    {
                        "title": title,
                        "url": uri,
                        "type": "Gemini Google Search Grounding",
                        "status": "검색 근거",
                    }
                )
        return sources

    def grounded_research(self, prompt: str) -> tuple[str, list[dict[str, str]]]:
        result = self._generate(
            prompt,
            operation_name="Google 검색 조사",
            config_factory=lambda: types.GenerateContentConfig(
                temperature=0.1,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return result.text, self._grounding_sources(result.response)

    def structure_json(self, prompt: str) -> dict[str, Any]:
        result = self._generate(
            prompt,
            operation_name="JSON 구조화",
            config_factory=lambda: types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        text = re.sub(r"^```(?:json)?\s*", "", result.text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(
                f"Gemini JSON 해석 실패({result.model}): {text[:1200]}"
            ) from exc
        if not isinstance(payload, dict):
            raise GeminiError("Gemini JSON 결과가 객체 형식이 아닙니다.")
        return payload
