from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class CommonsImage:
    title: str
    original_url: str
    thumbnail_url: str
    description_url: str
    artist: str
    license_name: str


def search_commons_images(query: str, *, limit: int = 6) -> list[CommonsImage]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6,
        "gsrlimit": max(1, min(limit, 20)),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1000,
        "format": "json",
        "formatversion": 2,
        "origin": "*",
    }
    request = Request(
        "https://commons.wikimedia.org/w/api.php?" + urlencode(params),
        headers={
            "User-Agent": "Jogyeongmaru-AI-ERP/8.0 (plant report research)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    output: list[CommonsImage] = []
    for page in payload.get("query", {}).get("pages", []):
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        metadata = info.get("extmetadata") or {}
        original = str(info.get("url", "")).strip()
        thumb = str(info.get("thumburl", "")).strip()
        if not original and not thumb:
            continue
        output.append(
            CommonsImage(
                title=str(page.get("title", "")).replace("File:", "").strip(),
                original_url=original or thumb,
                thumbnail_url=thumb or original,
                description_url=str(info.get("descriptionurl", "")).strip(),
                artist=str((metadata.get("Artist") or {}).get("value", "")).strip(),
                license_name=str((metadata.get("LicenseShortName") or {}).get("value", "")).strip(),
            )
        )
    return output
