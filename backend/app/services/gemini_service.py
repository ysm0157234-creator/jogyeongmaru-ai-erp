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


@dataclass
class GeminiCallResult:
    text: str
    model: str
    response: Any


class GeminiService:
    """Google Gen AI SDK 기반 Gemini 호출 서비스.

    핵심 원칙:
    - models.list()가 반환한 정식 model.name을 가능한 한 그대로 사용한다.
    - 임의로 publishers/google/models/... 같은 잘못된 형식으로 바꾸지 않는다.
    - 설정값이 잘못되어도 목록에 있는 generateContent 모델로 자동 대체한다.
    """

    BUILD_VERSION = "v10.1-valid-model-name"

    # 목록 조회가 실패했을 때만 사용하는 안전한 별칭 후보.
    FALLBACK_MODEL_IDS = (
        "gemini-flash-latest",
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3-flash",
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
    def _normalize_configured_model(value: str) -> str:
        """사용자가 넣은 환경변수를 Gemini API 허용 형식으로 제한한다."""
        name = str(value or "").strip()
        if not name:
            return ""

        # Gemini API에서 허용되는 두 형식만 인정한다.
        # 1) gemini-...
        # 2) models/gemini-...
        if re.fullmatch(r"gemini-[A-Za-z0-9._-]+", name):
            return name
        if re.fullmatch(r"models/gemini-[A-Za-z0-9._-]+", name):
            return name

        # Vertex 형식이나 URL 전체를 넣은 경우 마지막 모델 ID만 안전하게 추출한다.
        match = re.search(r"(?:^|/)models/(gemini-[A-Za-z0-9._-]+)$", name)
        if match:
            return match.group(1)

        match = re.search(r"(gemini-[A-Za-z0-9._-]+)$", name)
        return match.group(1) if match else ""

    @staticmethod
    def _supports_generate_content(model: Any) -> bool:
        actions = getattr(model, "supported_actions", None) or []
        if not actions:
            return True
        return any(str(action) == "generateContent" for action in actions)

    @staticmethod
    def _model_name_from_resource(model: Any) -> str:
        """models.list()가 준 정식 이름을 그대로 반환한다."""
        raw_name = str(getattr(model, "name", "") or "").strip()
        if re.fullmatch(r"models/gemini-[A-Za-z0-9._-]+", raw_name):
            return raw_name
        if re.fullmatch(r"gemini-[A-Za-z0-9._-]+", raw_name):
            return raw_name

        # 일부 SDK 버전은 base_model_id를 별도로 제공한다.
        base_id = str(getattr(model, "base_model_id", "") or "").strip()
        if re.fullmatch(r"gemini-[A-Za-z0-9._-]+", base_id):
            return base_id

        return ""

    def list_available_models(self, *, refresh: bool = False) -> list[str]:
        if self._available_models is not None and not refresh:
            return list(self._available_models)

        found: list[str] = []
        try:
            for model in self.client.models.list():
                if not self._supports_generate_content(model):
                    continue

                name = self._model_name_from_resource(model)
                if not name:
                    continue

                lowered = name.lower()
                if any(
                    skip in lowered
                    for skip in (
                        "embedding",
                        "imagen",
                        "veo",
                        "live",
                        "tts",
                        "image-generation",
                    )
                ):
                    continue

                found.append(name)
        except Exception as exc:
            configured = self._normalize_configured_model(self.configured_model)
            if configured:
                found.append(configured)
            else:
                # 목록 조회가 실패한 경우에만 최신 별칭을 시도한다.
                found.extend(self.FALLBACK_MODEL_IDS)

        self._available_models = list(dict.fromkeys(found))
        return list(self._available_models)

    @staticmethod
    def _ranking(name: str) -> tuple[int, int, int, str]:
        lowered = name.lower()
        # 텍스트 생성용 Flash 최신 계열 우선
        return (
            0 if "flash" in lowered else 1,
            0 if "latest" in lowered else 1,
            0 if "preview" in lowered else 1,
            lowered,
        )

    def _model_candidates(self) -> list[str]:
        available = self.list_available_models()
        candidates: list[str] = []

        configured = self._normalize_configured_model(self.configured_model)
        if configured:
            candidates.append(configured)

        candidates.extend(sorted(available, key=self._ranking))

        # 빈 문자열과 잘못된 형식은 마지막으로 다시 제거한다.
        valid: list[str] = []
        for name in candidates:
            if re.fullmatch(r"(?:models/)?gemini-[A-Za-z0-9._-]+", name):
                valid.append(name)

        return list(dict.fromkeys(valid))

    @staticmethod
    def _response_text(response: Any) -> str:
        text = str(getattr(response, "text", "") or "").strip()
        if text:
            return text

        pieces: list[str] = []
        for candidate in getattr(response, "candidates", None) or []:
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
        model_candidates = self._model_candidates()
        if not model_candidates:
            raise GeminiError(
                "현재 API 키에서 generateContent 가능한 Gemini 모델을 찾지 못했습니다."
            )

        errors_seen: list[str] = []

        for model_name in model_candidates:
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
            except errors.APIError as exc:
                errors_seen.append(
                    f"{model_name}: API {exc.code}: {str(exc)[:300]}"
                )
                # 모델명/미지원 기능 오류는 다음 모델을 계속 시도한다.
                if exc.code in (400, 404):
                    continue
                # 인증/권한/쿼터는 모델을 바꿔도 해결되지 않는다.
                if exc.code in (401, 403, 429):
                    break
            except Exception as exc:
                errors_seen.append(
                    f"{model_name}: {type(exc).__name__}: {str(exc)[:300]}"
                )
                continue

        raise GeminiError(
            f"Gemini {operation_name}에 실패했습니다. "
            + " | ".join(errors_seen[:10])
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
                sources.append(
                    {
                        "title": str(getattr(web, "title", "") or uri).strip(),
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
