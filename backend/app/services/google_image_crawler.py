from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


@dataclass
class CrawledImage:
    title: str
    image_url: str
    thumbnail_url: str
    context_url: str
    display_link: str
    width: int | None = None
    height: int | None = None
    source: str = "google-images"


_SEARCH_URL = "https://www.google.com/search?q={query}&tbm=isch&hl=en&gl=us&safe=off"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # 클라우드 서버 IP에서 요청하면 Google이 실제 검색결과 대신
    # 쿠키 동의(consent) 페이지를 돌려주는 경우가 흔하다. 이를 우회하기 위한 쿠키.
    "Cookie": "CONSENT=YES+shp.gws-20231010-0-RC1.en+FX+000; SOCS=CAI",
}

# 원본 이미지 후보로 쓰지 않을 도메인(아이콘/로고/구글 자체 UI 리소스 등).
_SKIP_DOMAINS = (
    "gstatic.com",
    "google.com",
    "googleusercontent.com/a/",
    "ssl.gstatic.com",
    "schema.org",
)

# 확장자를 알 수 있는 이미지 URL 매칭. 쿼리스트링이 붙어도 인식하도록 유연하게 처리.
_IMG_URL_RE = re.compile(
    r'"(https?://[^"\\]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\\]*)?)"',
    re.IGNORECASE,
)

# Google이 페이지 안에 심어두는 [url, width, height] 형태의 트리플. 실제 해상도 원본 이미지를 찾는 데 사용.
_TRIPLE_RE = re.compile(
    r'"(https?://(?!encrypted-tbn0)[^"\\]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\\]*)?)"\s*,\s*(\d+)\s*,\s*(\d+)\s*\]',
    re.IGNORECASE,
)

_THUMB_RE = re.compile(
    r'"(https?://encrypted-tbn0[^"\\]+?)"',
    re.IGNORECASE,
)


def _skip(url: str) -> bool:
    lowered = url.lower()
    return any(domain in lowered for domain in _SKIP_DOMAINS)


def search_google_images(query: str, *, limit: int = 20, timeout: int = 15) -> list[CrawledImage]:
    """Google 이미지 검색 결과 페이지를 크롤링해서 후보 이미지 URL을 수집한다.

    API 키를 쓰지 않는 순수 HTML 크롤링이므로, 구조 변경/차단으로 실패할 수 있다.
    이 함수는 실패 시 예외를 던지지 않고 빈 리스트를 반환해서 상위 파이프라인이
    다음 소스(Bing, 웹페이지 크롤링)로 자연스럽게 넘어가도록 한다.
    """
    url = _SEARCH_URL.format(query=quote_plus(query))
    request = Request(url, headers=_HEADERS)

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(3_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            status = getattr(response, "status", None)
    except HTTPError as exc:
        print(f"[google_image_crawler] HTTPError query={query!r} code={exc.code} reason={exc.reason}", flush=True)
        return []
    except (URLError, TimeoutError, OSError) as exc:
        print(f"[google_image_crawler] connection failed query={query!r} error={exc}", flush=True)
        return []

    try:
        html = raw.decode(charset, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")

    output: list[CrawledImage] = []
    seen: set[str] = set()

    # 1순위: [url, width, height] 트리플 — 실제 해상도를 아는 원본급 이미지.
    for match in _TRIPLE_RE.finditer(html):
        raw_url, width_s, height_s = match.group(1), match.group(2), match.group(3)
        image_url = raw_url.replace("\\u003d", "=").replace("\\u0026", "&")
        if _skip(image_url) or image_url in seen:
            continue
        try:
            width, height = int(width_s), int(height_s)
        except ValueError:
            width = height = None
        if width and height and (width < 200 or height < 150):
            continue
        seen.add(image_url)
        output.append(
            CrawledImage(
                title=query,
                image_url=image_url,
                thumbnail_url=image_url,
                context_url=url,
                display_link="Google 이미지 검색",
                width=width,
                height=height,
                source="google-images",
            )
        )
        if len(output) >= limit:
            break

    # 2순위: 트리플 파싱이 실패하면 일반 이미지 URL 패턴으로 보강.
    if len(output) < limit:
        for match in _IMG_URL_RE.finditer(html):
            image_url = match.group(1).replace("\\u003d", "=").replace("\\u0026", "&")
            if _skip(image_url) or image_url in seen:
                continue
            seen.add(image_url)
            output.append(
                CrawledImage(
                    title=query,
                    image_url=image_url,
                    thumbnail_url=image_url,
                    context_url=url,
                    display_link="Google 이미지 검색",
                    source="google-images",
                )
            )
            if len(output) >= limit:
                break

    # 3순위: 그래도 없으면 저해상도 썸네일이라도 최후 후보로 확보.
    if not output:
        for match in _THUMB_RE.finditer(html):
            image_url = match.group(1)
            if image_url in seen:
                continue
            seen.add(image_url)
            output.append(
                CrawledImage(
                    title=query,
                    image_url=image_url,
                    thumbnail_url=image_url,
                    context_url=url,
                    display_link="Google 이미지 검색(썸네일)",
                    source="google-images-thumb",
                )
            )
            if len(output) >= limit:
                break

    print(
        f"[google_image_crawler] query={query!r} status={status} html_bytes={len(raw)} candidates={len(output)}",
        flush=True,
    )
    if not output:
        lowered_html = html.lower()
        if "consent.google.com" in lowered_html or "before you continue" in lowered_html:
            print(f"[google_image_crawler] query={query!r} BLOCKED_BY_CONSENT_PAGE", flush=True)
        elif "captcha" in lowered_html or "unusual traffic" in lowered_html:
            print(f"[google_image_crawler] query={query!r} BLOCKED_BY_CAPTCHA", flush=True)
        elif len(html) < 5000:
            print(f"[google_image_crawler] query={query!r} SUSPICIOUSLY_SHORT_HTML snippet={html[:300]!r}", flush=True)
    return output
