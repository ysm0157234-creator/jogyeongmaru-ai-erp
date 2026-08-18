"""DuckDuckGo 이미지 검색 크롤링.

Google 이미지 검색은 2024년 이후 결과를 JavaScript로만 렌더링해서, 헤드리스 브라우저
없이는 HTML에서 사진 URL을 얻을 수 없다(응답은 status=200이지만 <img> 태그와
이미지 URL이 0개다). 그래서 Google 자리를 DuckDuckGo가 대신한다.

DuckDuckGo는 검색 페이지에서 vqd 토큰을 받은 뒤 JSON 엔드포인트를 호출하는 2단계
방식이고, 원본 해상도(width/height)를 함께 주기 때문에 아이콘·배너를 걸러낼 수 있다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_VQD_RE = re.compile(r'vqd=["\']?([\w-]+)["\']?')


@dataclass
class CrawledImage:
    title: str
    image_url: str
    thumbnail_url: str
    context_url: str
    display_link: str
    width: int | None = None
    height: int | None = None
    source: str = "duckduckgo-images"


def _fetch(url: str, headers: dict, timeout: int) -> bytes | None:
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            return response.read(3_000_000)
    except HTTPError as exc:
        print(f"[duckduckgo_image_service] HTTPError code={exc.code} url={url[:80]}", flush=True)
    except (URLError, TimeoutError, OSError) as exc:
        print(f"[duckduckgo_image_service] request failed error={exc} url={url[:80]}", flush=True)
    return None


def search_duckduckgo_images(query: str, *, limit: int = 20, timeout: int = 15) -> list[CrawledImage]:
    """DuckDuckGo 이미지 검색 결과를 관련도 순서 그대로 수집한다.

    실패해도 예외를 던지지 않고 빈 리스트를 반환해서 상위 파이프라인이 다음 소스로 넘어가게 한다.
    """
    encoded = quote_plus(query)

    page = _fetch(f"https://duckduckgo.com/?q={encoded}&iax=images&ia=images", _HEADERS, timeout)
    if not page:
        return []

    match = _VQD_RE.search(page.decode("utf-8", errors="replace"))
    if not match:
        print(f"[duckduckgo_image_service] query={query!r} VQD_TOKEN_NOT_FOUND", flush=True)
        return []

    headers = dict(_HEADERS)
    headers["Referer"] = "https://duckduckgo.com/"
    payload = _fetch(
        f"https://duckduckgo.com/i.js?l=us-en&o=json&q={encoded}&vqd={match.group(1)}&f=,,,&p=1",
        headers,
        timeout,
    )
    if not payload:
        return []

    try:
        data = json.loads(payload)
    except ValueError as exc:
        print(f"[duckduckgo_image_service] JSON parse failed query={query!r} error={exc}", flush=True)
        return []

    output: list[CrawledImage] = []
    seen: set[str] = set()

    for record in data.get("results", []):
        image_url = str(record.get("image") or "").strip()
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        output.append(
            CrawledImage(
                title=str(record.get("title") or query).strip() or query,
                image_url=image_url,
                thumbnail_url=str(record.get("thumbnail") or image_url).strip(),
                context_url=str(record.get("url") or "").strip(),
                display_link=str(record.get("source") or "DuckDuckGo 이미지 검색"),
                width=_safe_int(record.get("width")),
                height=_safe_int(record.get("height")),
                source="duckduckgo-images",
            )
        )
        if len(output) >= limit:
            break

    print(
        f"[duckduckgo_image_service] query={query!r} raw={len(data.get('results', []))} candidates={len(output)}",
        flush=True,
    )
    return output


def _safe_int(value) -> int | None:
    try:
        number = int(float(str(value)))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None
