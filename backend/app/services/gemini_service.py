from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

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
    """
    Google Gen AI SDK 기반 Gemini 서비스.

    동작 방식:
    1. Render의 GEMINI_MODEL 값이 현재 계정에서 사용 가능하면 우선 사용
    2. 사용 불가하거나 비어 있으면 models.list() 결과를 확인
    3. 안정적인 Flash 모델부터 순서대로 자동 시도
    """

    PREFERRED_MODELS = (
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
    )

    EXCLUDED_MODEL_WORDS = (
        "embedding",
        "imagen",
        "image",
        "veo",
        "live",
        "tts",
        "robotics",
        "antigravity",
    )

    def __init__(self) -> None:
        settings = get_settings()

        api_key = str(settings.gemini_api_key or "").strip()
        if not api_key:
            raise GeminiNotConfiguredError(
                "Render 환경변수 GEMINI_API_KEY가 누락되었습니다."
            )

        self.client = genai.Client(api_key=api_key)
        self.configured_model = self._clean_model_name(
            str(settings.gemini_model or "")
        )

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

        # SDK 버전에 따라 지원 메서드 정보가 비어 있을 수 있다.
        # 이 경우 이름 기준으로 후보에 포함하고 실제 호출에서 확인한다.
        if not actions:
            return True

        normalized = {
            str(action)
            .lower()
            .replace("_", "")
            .replace("-", "")
            for action in actions
        }

        return any("generatecontent" in action for action in normalized)

    def list_available_models(
        self,
        *,
        refresh: bool = False,
    ) -> list[str]:
        if (
            self._available_models is not None
            and not refresh
        ):
            return list(self._available_models)

        found: list[str] = []

        try:
            for model in self.client.models.list():
                model_name = self._clean_model_name(
                    getattr(model, "name", "")
                )

                if not model_name:
                    continue

                lowered = model_name.lower()

                if "gemini" not in lowered:
                    continue

                if any(
                    blocked in lowered
                    for blocked in self.EXCLUDED_MODEL_WORDS
                ):
                    continue

                if not self._supports_generate_content(model):
                    continue

                found.append(model_name)

        except Exception as exc:
            # 모델 목록 조회가 실패해도 지정 모델과 안정 모델을 직접 시도한다.
            fallback = [
                self.configured_model,
                *self.PREFERRED_MODELS,
            ]
            found = [
                model
                for model in fallback
                if model
            ]

            if not found:
                raise GeminiError(
                    f"Gemini 사용 가능 모델 조회 실패: {exc}"
                ) from exc

        self._available_models = list(dict.fromkeys(found))
        return list(self._available_models)

    @staticmethod
    def _model_priority(name: str) -> tuple[int, int, int, str]:
        lowered = name.lower()

        if name == "gemini-3.6-flash":
            stable_rank = 0
        elif name == "gemini-3.5-flash":
            stable_rank = 1
        elif name == "gemini-3.5-flash-lite":
            stable_rank = 2
        elif name == "gemini-3.1-flash-lite":
            stable_rank = 3
        elif name == "gemini-flash-latest":
            stable_rank = 4
        else:
            stable_rank = 20

        preview_penalty = 1 if "preview" in lowered else 0
        lite_penalty = 1 if "lite" in lowered else 0

        return (
            stable_rank,
            preview_penalty,
            lite_penalty,
            name,
        )

    def _model_candidates(self) -> list[str]:
        available = self.list_available_models()
        available_set = set(available)

        candidates: list[str] = []

        if self.configured_model:
            candidates.append(self.configured_model)

        for preferred in self.PREFERRED_MODELS:
            if preferred in available_set:
                candidates.append(preferred)

        flash_models = sorted(
            (
                model
                for model in available
                if "flash" in model.lower()
            ),
            key=self._model_priority,
        )

        other_models = sorted(
            (
                model
                for model in available
                if "flash" not in model.lower()
            ),
            key=self._model_priority,
        )

        candidates.extend(flash_models)
        candidates.extend(other_models)

        # models.list()가 불완전하게 동작하는 경우를 대비해
        # 안정 모델명을 마지막 후보로도 직접 넣는다.
        candidates.extend(self.PREFERRED_MODELS)

        return list(
            dict.fromkeys(
                model
                for model in candidates
                if model
            )
        )

    @staticmethod
    def _response_text(response: Any) -> str:
        direct_text = str(
            getattr(response, "text", "") or ""
        ).strip()

        if direct_text:
            return direct_text

        pieces: list[str] = []

        for candidate in (
            getattr(response, "candidates", None)
            or []
        ):
            content = getattr(candidate, "content", None)

            for part in (
                getattr(content, "parts", None)
                or []
            ):
                text = getattr(part, "text", None)

                if text:
                    pieces.append(str(text))

        result = "".join(pieces).strip()

        if not result:
            raise GeminiError(
                "Gemini 응답에 텍스트가 없습니다."
            )

        return result

    @staticmethod
    def _is_non_retryable_error(message: str) -> bool:
        lowered = message.lower()

        markers = (
            "api key not valid",
            "invalid api key",
            "permission denied",
            "billing",
            "quota exceeded",
            "resource_exhausted",
            "unauthenticated",
        )

        return any(marker in lowered for marker in markers)

    def _generate(
        self,
        prompt: str,
        *,
        config_factory: Callable[[], types.GenerateContentConfig],
        operation_name: str,
    ) -> GeminiCallResult:
        candidates = self._model_candidates()

        if not candidates:
            raise GeminiError(
                "현재 API 키에서 사용할 Gemini 모델을 찾지 못했습니다."
            )

        errors: list[str] = []

        for model_name in candidates:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config_factory(),
                )

                text = self._response_text(response)
                self.last_used_model = model_name

                return GeminiCallResult(
                    text=text,
                    model=model_name,
                    response=response,
                )

            except Exception as exc:
                message = str(exc)

                errors.append(
                    f"{model_name}: "
                    f"{type(exc).__name__}: "
                    f"{message[:450]}"
                )

                if self._is_non_retryable_error(message):
                    break

        raise GeminiError(
            f"Gemini {operation_name}에 실패했습니다. "
            f"시도 결과: {' | '.join(errors[:10])}"
        )

    @staticmethod
    def _grounding_sources(
        response: Any,
    ) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        seen: set[str] = set()

        for candidate in (
            getattr(response, "candidates", None)
            or []
        ):
            metadata = getattr(
                candidate,
                "grounding_metadata",
                None,
            )

            chunks = getattr(
                metadata,
                "grounding_chunks",
                None,
            ) or []

            for chunk in chunks:
                web = getattr(chunk, "web", None)

                uri = str(
                    getattr(web, "uri", "") or ""
                ).strip()

                if not uri or uri in seen:
                    continue

                seen.add(uri)

                title = str(
                    getattr(web, "title", "") or uri
                ).strip()

                sources.append(
                    {
                        "title": title,
                        "url": uri,
                        "type": (
                            "Gemini Google Search Grounding"
                        ),
                        "status": "검색 근거",
                    }
                )

        return sources

    def grounded_research(
        self,
        prompt: str,
    ) -> tuple[str, list[dict[str, str]]]:
        result = self._generate(
            prompt,
            operation_name="Google 검색 조사",
            config_factory=lambda: (
                types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            google_search=types.GoogleSearch()
                        )
                    ],
                )
            ),
        )

        return (
            result.text,
            self._grounding_sources(result.response),
        )

    def structure_json(
        self,
        prompt: str,
    ) -> dict[str, Any]:
        result = self._generate(
            prompt,
            operation_name="JSON 구조화",
            config_factory=lambda: (
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            ),
        )

        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            result.text,
            flags=re.I,
        )
        text = re.sub(
            r"\s*```$",
            "",
            text,
        ).strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(
                f"Gemini JSON 해석 실패 "
                f"(모델: {result.model}): "
                f"{text[:1400]}"
            ) from exc

        if not isinstance(payload, dict):
            raise GeminiError(
                "Gemini JSON 결과가 객체 형식이 아닙니다."
            )

        return payload
