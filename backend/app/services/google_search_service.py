from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings


class GoogleSearchNotConfiguredError(RuntimeError):
    """
    기존 코드와의 호환을 위해 클래스명은 유지하지만,
    실제 검색 공급자는 v12부터 Serper API이다.
    """


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
    source: str = "google-images"


class GoogleSearchService:
    """
    v17 검색 서비스.

    Serper를 통해 구글 웹검색과 구글 이미지 검색을 쓴다.
    구글 이미지 검색 페이지는 결과를 자바스크립트로만 그려서 직접 크롤링할 수 없다.
    """

    SEARCH_URL = "https://google.serper.dev/search"
    IMAGE_URL = "https://google.serper.dev/images"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.serper_api_key.strip()

        if not self.api_key:
            raise GoogleSearchNotConfiguredError(
                "Render 환경변수 SERPER_API_KEY가 누락되었습니다."
            )

    def _request(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = {
            "gl": "kr",
            "hl": "ko",
            **payload,
        }

        request = Request(
            url,
            data=json.dumps(
                body,
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Jogyeongmaru-AI-ERP/17.1",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=40,
            ) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )

        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )

            if exc.code == 401:
                message = (
                    "Serper API 키가 올바르지 않습니다. "
                    "Render의 SERPER_API_KEY를 확인하세요."
                )
            elif exc.code == 403:
                message = (
                    "Serper API 접근이 거부되었습니다. "
                    "계정 상태와 API 키 권한을 확인하세요."
                )
            elif exc.code == 429:
                message = (
                    "Serper 검색 크레딧 또는 요청 한도를 초과했습니다."
                )
            else:
                message = (
                    f"Serper API 오류({exc.code}): "
                    f"{detail[:800]}"
                )

            raise GoogleSearchError(message) from exc

        except (URLError, TimeoutError) as exc:
            raise GoogleSearchError(
                f"Serper API 연결 실패: {exc}"
            ) from exc

        except json.JSONDecodeError as exc:
            raise GoogleSearchError(
                "Serper API 응답을 JSON으로 해석하지 못했습니다."
            ) from exc

        except Exception as exc:
            raise GoogleSearchError(
                f"Serper 검색 응답 처리 실패: {exc}"
            ) from exc

        if not isinstance(result, dict):
            raise GoogleSearchError(
                "Serper API 응답 형식이 올바르지 않습니다."
            )

        return result

    def search_web(
        self,
        query: str,
        *,
        num: int = 10,
    ) -> list[WebSearchResult]:
        result = self._request(
            self.SEARCH_URL,
            {
                "q": query,
                "num": max(
                    1,
                    min(num, 20),
                ),
            },
        )

        output: list[WebSearchResult] = []

        # 일반 검색 결과
        for item in result.get("organic", []) or []:
            link = str(
                item.get("link", "")
            ).strip()

            if not link:
                continue

            output.append(
                WebSearchResult(
                    title=str(
                        item.get("title", "")
                    ).strip(),
                    link=link,
                    snippet=str(
                        item.get("snippet", "")
                    ).strip(),
                    display_link=str(
                        item.get("domain")
                        or item.get("source")
                        or ""
                    ).strip(),
                )
            )

        # Knowledge Graph도 검색 근거로 사용할 수 있도록 추가
        knowledge = result.get("knowledgeGraph") or {}
        knowledge_link = str(
            knowledge.get("website")
            or knowledge.get("descriptionLink")
            or ""
        ).strip()

        if knowledge_link:
            output.insert(
                0,
                WebSearchResult(
                    title=str(
                        knowledge.get("title", "")
                    ).strip(),
                    link=knowledge_link,
                    snippet=str(
                        knowledge.get("description", "")
                    ).strip(),
                    display_link=str(
                        knowledge.get("descriptionSource", "")
                    ).strip(),
                ),
            )

        return output[: max(1, min(num, 20))]

    def search_images(
        self,
        query: str,
        *,
        num: int = 20,
    ) -> list[ImageSearchResult]:
        """구글 이미지 검색 결과를 가져온다.

        구글 이미지 검색 페이지는 결과를 자바스크립트로만 그려서 크롤링이 불가능하다.
        Serper의 images 엔드포인트가 그 결과를 그대로 돌려주므로 이것을 쓴다.
        """
        text = str(query or "").strip()
        if not text:
            return []

        # 사진은 나라·언어를 가리지 않는 편이 후보가 넓다.
        data = self._request(self.IMAGE_URL, {"q": text, "num": num, "gl": "us", "hl": "en"})

        output: list[ImageSearchResult] = []
        for item in (data.get("images") or [])[:num]:
            image_url = str(item.get("imageUrl") or "").strip()
            if not image_url:
                continue
            output.append(
                ImageSearchResult(
                    title=str(item.get("title") or text).strip(),
                    image_url=image_url,
                    thumbnail_url=str(item.get("thumbnailUrl") or image_url).strip(),
                    context_url=str(item.get("link") or "").strip(),
                    display_link=str(item.get("source") or "구글 이미지 검색").strip(),
                    width=_safe_int(item.get("imageWidth")),
                    height=_safe_int(item.get("imageHeight")),
                )
            )

        print(f"[google_search_service] 구글 이미지 {text!r} → {len(output)}건", flush=True)
        return output


def _safe_int(value: Any) -> int | None:
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None
