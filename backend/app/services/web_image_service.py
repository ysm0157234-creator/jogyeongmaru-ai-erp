from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass
class PageImageResult:
    title: str
    image_url: str
    preview_url: str
    context_url: str
    display_link: str
    alt_text: str = ""
    width: int | None = None
    height: int | None = None
    source_type: str = "web-page"


class _PageImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(k).lower(): str(v or "") for k, v in attrs}
        lower = tag.lower()
        if lower == "title":
            self.in_title = True
        elif lower == "meta":
            self.meta.append(values)
        elif lower == "img":
            self.images.append(values)
        elif lower == "script" and "ld+json" in values.get("type", "").lower():
            self._in_json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "title":
            self.in_title = False
        elif lower == "script" and self._in_json_ld:
            self._in_json_ld = False
            value = "".join(self._json_parts).strip()
            if value:
                self.json_ld.append(value)
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self._in_json_ld:
            self._json_parts.append(data)


_BLOCKED_EXTENSIONS = (".svg", ".gif")
_BLOCKED_WORDS = (
    "logo", "icon", "sprite", "avatar", "favicon", "banner", "tracking",
    "pixel", "placeholder", "loading", "advert", "cookie", "social",
)


def _safe_int(value: Any) -> int | None:
    try:
        number = int(float(str(value).strip()))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _candidate_ok(url: str, alt: str, width: int | None, height: int | None) -> bool:
    lowered = f"{url} {alt}".lower()
    if not url.startswith(("http://", "https://")):
        return False
    if any(urlparse(url).path.lower().endswith(ext) for ext in _BLOCKED_EXTENSIONS):
        return False
    if any(word in lowered for word in _BLOCKED_WORDS):
        return False
    if width and height and (width < 220 or height < 180):
        return False
    return True


def _image_values(value: Any) -> list[str]:
    output: list[str] = []
    if isinstance(value, str):
        output.append(value)
    elif isinstance(value, list):
        for item in value:
            output.extend(_image_values(item))
    elif isinstance(value, dict):
        for key in ("url", "contentUrl", "thumbnailUrl", "image"):
            if key in value:
                output.extend(_image_values(value[key]))
    return output


def _walk_json_ld(value: Any) -> list[str]:
    output: list[str] = []
    if isinstance(value, dict):
        if "image" in value:
            output.extend(_image_values(value["image"]))
        for child in value.values():
            if isinstance(child, (dict, list)):
                output.extend(_walk_json_ld(child))
    elif isinstance(value, list):
        for child in value:
            output.extend(_walk_json_ld(child))
    return output


def extract_page_images(page_url: str, *, timeout: int = 18, max_images: int = 20) -> list[PageImageResult]:
    request = Request(
        page_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Jogyeongmaru-AI-ERP/17.0; +https://example.invalid)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en,ko;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if "html" not in content_type:
                return []
            raw = response.read(2_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
    except Exception:
        return []

    try:
        html = raw.decode(charset, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")

    parser = _PageImageParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    page_title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
    host = urlparse(page_url).netloc
    candidates: list[PageImageResult] = []

    # Open Graph / Twitter 대표 이미지
    for meta in parser.meta:
        key = (meta.get("property") or meta.get("name") or "").lower()
        if key not in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
            continue
        image_url = urljoin(page_url, meta.get("content", "").strip())
        if _candidate_ok(image_url, page_title, None, None):
            candidates.append(PageImageResult(
                title=page_title or host,
                image_url=image_url,
                preview_url=image_url,
                context_url=page_url,
                display_link=host,
                alt_text=page_title,
                source_type="meta-image",
            ))

    # JSON-LD image
    for block in parser.json_ld:
        try:
            payload = json.loads(block)
        except Exception:
            continue
        for value in _walk_json_ld(payload):
            image_url = urljoin(page_url, value.strip())
            if _candidate_ok(image_url, page_title, None, None):
                candidates.append(PageImageResult(
                    title=page_title or host,
                    image_url=image_url,
                    preview_url=image_url,
                    context_url=page_url,
                    display_link=host,
                    alt_text=page_title,
                    source_type="json-ld-image",
                ))

    # 일반 img / lazy-loading 속성
    for img in parser.images:
        src = ""
        for key in ("data-src", "data-lazy-src", "data-original", "data-image", "src"):
            if img.get(key):
                src = img[key].strip()
                break
        if not src or src.startswith("data:"):
            continue
        image_url = urljoin(page_url, src)
        alt = re.sub(r"\s+", " ", img.get("alt", "")).strip()
        width = _safe_int(img.get("width") or img.get("data-width"))
        height = _safe_int(img.get("height") or img.get("data-height"))
        if not _candidate_ok(image_url, alt, width, height):
            continue
        candidates.append(PageImageResult(
            title=alt or page_title or host,
            image_url=image_url,
            preview_url=image_url,
            context_url=page_url,
            display_link=host,
            alt_text=alt,
            width=width,
            height=height,
            source_type="html-image",
        ))

    seen: set[str] = set()
    output: list[PageImageResult] = []
    for item in candidates:
        normalized = item.image_url.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(item)
        if len(output) >= max_images:
            break
    return output
