from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiError(RuntimeError):
    pass


class GeminiService:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.gemini_api_key.strip()
        self.model = settings.gemini_model.strip() or "gemini-2.5-flash"
        if not self.api_key:
            raise GeminiNotConfiguredError(
                "Render 환경변수 GEMINI_API_KEY가 누락되었습니다."
            )

    def _call(self, payload: dict[str, Any], *, timeout: int = 90) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Jogyeongmaru-AI-ERP/8.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GeminiError(f"Gemini API 오류({exc.code}): {detail[:900]}") from exc
        except (URLError, TimeoutError) as exc:
            raise GeminiError(f"Gemini API 연결 실패: {exc}") from exc
        except Exception as exc:
            raise GeminiError(f"Gemini 응답 처리 실패: {exc}") from exc

    @staticmethod
    def _text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            raise GeminiError(
                f"Gemini가 결과를 반환하지 않았습니다: {payload.get('promptFeedback')}"
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts)
        if not text.strip():
            raise GeminiError("Gemini 응답에 텍스트가 없습니다.")
        return text.strip()

    def grounded_research(self, prompt: str) -> tuple[str, list[dict[str, str]]]:
        payload = self._call(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.1},
            }
        )
        text = self._text(payload)
        sources: list[dict[str, str]] = []
        candidate = (payload.get("candidates") or [{}])[0]
        metadata = candidate.get("groundingMetadata") or {}
        for chunk in metadata.get("groundingChunks", []):
            web = chunk.get("web") or {}
            uri = str(web.get("uri", "")).strip()
            if not uri:
                continue
            sources.append(
                {
                    "title": str(web.get("title", "")).strip() or uri,
                    "url": uri,
                    "type": "Gemini Google Search Grounding",
                    "status": "검색 근거",
                }
            )
        return text, sources

    def structure_json(self, prompt: str) -> dict[str, Any]:
        payload = self._call(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
        )
        text = self._text(payload)
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(f"Gemini JSON 해석 실패: {text[:1000]}") from exc
