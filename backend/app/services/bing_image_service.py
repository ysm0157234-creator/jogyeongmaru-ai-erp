from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
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
    source: str = "bing-images"


_SEARCH_URL = "https://www.bing.com/images/search?q={query}&form=HDRSC2&safeSearch=off"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


class _BingImageParser(HTMLParser):
    """Bing은 결과 각각을 <a class="iusc" m='{"murl":...,"turl":...}'> 형태로 내려준다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {str(k).lower(): str(v or "") for k, v in attrs}
        classes = values.get("class", "")
        payload = values.get("m", "")
        if "iusc" not in classes or not payload:
            return
        try:
            data = json.loads(html.unescape(payload))
        except Exception:
            return
        if isinstance(data, dict):
            self.records.append(data)


def search_bing_images(query: str, *, limit: int = 20, timeout: int = 15) -> list[CrawledImage]:
    """Bing 이미지 검색 결과를 크롤링한다. 실패해도 예외를 던지지 않고 빈 리스트를 반환한다."""
    url = _SEARCH_URL.format(query=quote_plus(query))
    request = Request(url, headers=_HEADERS)

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(3_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        print(f"[bing_image_service] HTTPError query={query!r} code={exc.code} reason={exc.reason}", flush=True)
        return []
    except (URLError, TimeoutError, OSError) as exc:
        print(f"[bing_image_service] connection failed query={query!r} error={exc}", flush=True)
        return []

    try:
        page_html = raw.decode(charset, errors="replace")
    except LookupError:
        page_html = raw.decode("utf-8", errors="replace")

    parser = _BingImageParser()
    try:
        parser.feed(page_html)
    except Exception as exc:
        print(f"[bing_image_service] HTML parse failed query={query!r} error={exc}", flush=True)
        return []

    output: list[CrawledImage] = []
    seen: set[str] = set()
    for record in parser.records:
        image_url = str(record.get("murl") or "").strip()
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        output.append(
            CrawledImage(
                title=str(record.get("t") or query).strip() or query,
                image_url=image_url,
                thumbnail_url=str(record.get("turl") or image_url).strip(),
                context_url=str(record.get("purl") or url).strip(),
                display_link=str(record.get("md5") and "Bing 이미지 검색" or "Bing 이미지 검색"),
                width=_safe_int(record.get("ow")),
                height=_safe_int(record.get("oh")),
                source="bing-images",
            )
        )
        if len(output) >= limit:
            break

    print(
        f"[bing_image_service] query={query!r} html_bytes={len(raw)} iusc_records={len(parser.records)} candidates={len(output)}",
        flush=True,
    )
    if not output:
        lowered_html = page_html.lower()
        if "captcha" in lowered_html or "unusual traffic" in lowered_html:
            print(f"[bing_image_service] query={query!r} BLOCKED_BY_CAPTCHA", flush=True)
        elif len(page_html) < 5000:
            print(f"[bing_image_service] query={query!r} SUSPICIOUSLY_SHORT_HTML snippet={page_html[:300]!r}", flush=True)
    return output


def _safe_int(value) -> int | None:
    try:
        number = int(float(str(value)))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None
