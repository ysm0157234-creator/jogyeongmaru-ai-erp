from __future__ import annotations

import json
import re
from typing import Any

from google import genai
from google.genai import types

from app.core.config import get_settings


class GeminiNotConfiguredError(RuntimeError):
    pass


class GeminiError(RuntimeError):
    pass


class GeminiService:

    def __init__(self):
        settings = get_settings()

        if not settings.gemini_api_key:
            raise GeminiNotConfiguredError(
                "Render 환경변수 GEMINI_API_KEY가 없습니다."
            )

        self.client = genai.Client(
            api_key=settings.gemini_api_key
        )

        self.model = (
            settings.gemini_model
            or "gemini-3-flash-preview"
        )

    def grounded_research(self, prompt: str):

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                ),
            )

            text = response.text

            sources = []

            if (
                hasattr(response, "grounding_metadata")
                and response.grounding_metadata
            ):
                for chunk in response.grounding_metadata.grounding_chunks:
                    if getattr(chunk, "web", None):
                        sources.append(
                            {
                                "title": chunk.web.title,
                                "url": chunk.web.uri,
                                "type": "Google Search",
                                "status": "검색 근거",
                            }
                        )

            return text, sources

        except Exception as e:
            raise GeminiError(str(e))

    def structure_json(self, prompt: str):

        try:

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            txt = response.text

            txt = re.sub(r"^```json", "", txt).strip()
            txt = re.sub(r"```$", "", txt).strip()

            return json.loads(txt)

        except Exception as e:
            raise GeminiError(str(e))
