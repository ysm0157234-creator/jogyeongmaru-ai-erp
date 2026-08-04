from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import get_settings


class GoogleSearchNotConfiguredError(RuntimeError):
    pass


class GoogleSearchError(RuntimeError):
    pass


@dataclass
class WebSearchResult:
    title: str
    link: str
    snippet: str
    display_link: str


@dataclass
class ImageSearchResult:
    title: str
    image_url: str
    thumbnail_url: str
    context_url: str
    display_link: str
    width: int | None = None
    height: int | None = None


class GoogleSearchService:
    BASE_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.google_search_api_key.strip()
        self.engine_id = settings.google_search_engine_id.strip()
        missing: list[str] = []
        if not self.api_key:
            missing.append("GOOGLE_SEARCH_API_KEY")
        if not self.engine_id:
            missing.append("GOOGLE_SEARCH_ENGINE_ID")
        if missing:
            raise GoogleSearchNotConfiguredError(
                "Render 환경변수가 누락되었습니다: " + ", ".join(missing)
            )

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        query = {
            "key": self.api_key,
            "cx": self.engine_id,
            "safe": "active",
            **params,
        }
        request = Request(
            f"{self.BASE_URL}?{urlencode(query)}",
            headers={
                "User-Agent": "Jogyeongmaru-AI-ERP/8.0",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GoogleSearchError(
                f"Google 검색 API 오류({exc.code}): {body[:700]}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise GoogleSearchError(f"Google 검색 API 연결 실패: {exc}") from exc
        except Exception as exc:
            raise GoogleSearchError(f"Google 검색 응답 처리 실패: {exc}") from exc
        if payload.get("error"):
            raise GoogleSearchError(f"Google 검색 API 오류: {payload['error']}")
        return payload

    def search_web(self, query: str, *, num: int = 10) -> list[WebSearchResult]:
        payload = self._request({"q": query, "num": max(1, min(num, 10))})
        output: list[WebSearchResult] = []
        for item in payload.get("items", []):
            link = str(item.get("link", "")).strip()
            if not link:
                continue
            output.append(
                WebSearchResult(
                    title=str(item.get("title", "")).strip(),
                    link=link,
                    snippet=str(item.get("snippet", "")).strip(),
                    display_link=str(item.get("displayLink", "")).strip(),
                )
            )
        return output

    def search_images(self, query: str, *, num: int = 10) -> list[ImageSearchResult]:
        payload = self._request(
            {
                "q": query,
                "searchType": "image",
                "imgType": "photo",
                "imgSize": "large",
                "num": max(1, min(num, 10)),
            }
        )
        output: list[ImageSearchResult] = []
        for item in payload.get("items", []):
            image = item.get("image") or {}
            original = str(item.get("link", "")).strip()
            thumbnail = str(image.get("thumbnailLink", "")).strip()
            if not original and not thumbnail:
                continue
            output.append(
                ImageSearchResult(
                    title=str(item.get("title", "")).strip(),
                    image_url=original,
                    thumbnail_url=thumbnail,
                    context_url=str(image.get("contextLink", "")).strip(),
                    display_link=str(item.get("displayLink", "")).strip(),
                    width=image.get("width"),
                    height=image.get("height"),
                )
            )
        return output
