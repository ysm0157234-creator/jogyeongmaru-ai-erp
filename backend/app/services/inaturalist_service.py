"""iNaturalist 사진 수집.

일반 이미지 검색(Bing/DuckDuckGo)은 '검색어와 비슷해 보이는' 사진을 주기 때문에
학명이 정확해도 스톡사진·씨앗 판매글·전혀 다른 식물이 섞여 들어온다.

iNaturalist는 사진이 **분류군 ID(taxon id)에 직접 묶여 있고** 커뮤니티 검증을 거치므로,
학명만 맞으면 종(species)이 틀린 사진이 나올 수 없다. 라이선스도 명시되어 있어
보고서 첨부 시 이용 조건을 그대로 표기할 수 있다.

한계: iNaturalist는 품종(cultivar)을 구분하지 않는다. 종 단위까지만 보장된다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_API = "https://api.inaturalist.org/v1"

_HEADERS = {
    "User-Agent": "jogyeongmaru-ai-erp/1.0 (plant import report generator)",
    "Accept": "application/json",
}

# 라이선스 코드 → 보고서에 표기할 한국어 문구
_LICENSE_LABELS = {
    "cc0": "CC0 (퍼블릭 도메인)",
    "cc-by": "CC BY (출처 표시)",
    "cc-by-sa": "CC BY-SA (출처 표시·동일조건)",
    "cc-by-nc": "CC BY-NC (출처 표시·비영리)",
    "cc-by-nc-sa": "CC BY-NC-SA (출처 표시·비영리·동일조건)",
    "cc-by-nd": "CC BY-ND (출처 표시·변경금지)",
    "cc-by-nc-nd": "CC BY-NC-ND (출처 표시·비영리·변경금지)",
}


@dataclass
class CrawledImage:
    title: str
    image_url: str
    thumbnail_url: str
    context_url: str
    display_link: str
    width: int | None = None
    height: int | None = None
    source: str = "inaturalist"


def _get(url: str, timeout: int) -> dict | None:
    try:
        with urlopen(Request(url, headers=_HEADERS), timeout=timeout) as response:
            return json.loads(response.read(3_000_000))
    except HTTPError as exc:
        print(f"[inaturalist_service] HTTPError url={url} code={exc.code}", flush=True)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"[inaturalist_service] request failed url={url} error={exc}", flush=True)
    return None


def _license_label(code: str | None) -> str:
    if not code:
        return "iNaturalist 게시자 저작권 유지 — 원본 페이지에서 이용 조건을 확인하세요."
    return _LICENSE_LABELS.get(str(code).lower(), str(code).upper())


def find_taxon(scientific_name: str, *, timeout: int = 15) -> dict | None:
    """학명으로 분류군을 찾는다. 종 단위 매칭을 우선한다."""
    query = quote_plus(scientific_name.strip())
    if not query:
        return None

    for suffix in ("&rank=species", ""):
        data = _get(f"{_API}/taxa?q={query}&per_page=5{suffix}", timeout)
        for taxon in (data or {}).get("results", []):
            if str(taxon.get("name", "")).lower() == scientific_name.strip().lower():
                return taxon
        if (data or {}).get("results"):
            return data["results"][0]

    return None


def search_inaturalist_photos(
    scientific_name: str,
    *,
    limit: int = 12,
    timeout: int = 15,
) -> list[CrawledImage]:
    """학명에 해당하는 분류군의 검증된 사진을 모은다.

    1순위: taxon_photos — iNaturalist가 그 분류군의 대표로 큐레이션한 사진
    2순위: 연구등급(research grade) 관찰 사진 — 커뮤니티가 종 동정에 합의한 관찰
    """
    taxon = find_taxon(scientific_name, timeout=timeout)
    if not taxon:
        print(f"[inaturalist_service] taxon not found name={scientific_name!r}", flush=True)
        return []

    taxon_id = taxon.get("id")
    matched = taxon.get("name") or scientific_name
    output: list[CrawledImage] = []
    seen: set[str] = set()

    def add(photo: dict, context_url: str, attribution: str) -> None:
        raw_url = str(photo.get("url") or "")
        if not raw_url:
            return
        image_url = raw_url.replace("/square.", "/large.")
        if image_url in seen:
            return
        seen.add(image_url)
        dimensions = photo.get("original_dimensions") or {}
        output.append(
            CrawledImage(
                title=f"{matched} — {attribution}" if attribution else matched,
                image_url=image_url,
                thumbnail_url=raw_url.replace("/square.", "/medium."),
                context_url=context_url,
                display_link=f"iNaturalist ({_license_label(photo.get('license_code'))})",
                width=dimensions.get("width"),
                height=dimensions.get("height"),
                source="inaturalist",
            )
        )

    detail = _get(f"{_API}/taxa/{taxon_id}", timeout)
    for entry in ((detail or {}).get("results") or [{}])[0].get("taxon_photos", []):
        photo = entry.get("photo") or {}
        add(
            photo,
            str(photo.get("native_page_url") or f"https://www.inaturalist.org/taxa/{taxon_id}"),
            str(photo.get("attribution") or "").split(",")[0],
        )
        if len(output) >= limit:
            break

    if len(output) < limit:
        observations = _get(
            f"{_API}/observations?taxon_id={taxon_id}&photos=true"
            f"&quality_grade=research&per_page={limit}&order_by=votes",
            timeout,
        )
        for observation in (observations or {}).get("results", []):
            for photo in observation.get("photos", [])[:1]:
                add(
                    photo,
                    f"https://www.inaturalist.org/observations/{observation.get('id')}",
                    str((observation.get("user") or {}).get("login") or ""),
                )
            if len(output) >= limit:
                break

    print(
        f"[inaturalist_service] name={scientific_name!r} matched={matched!r} "
        f"taxon_id={taxon_id} observations={taxon.get('observations_count')} photos={len(output)}",
        flush=True,
    )
    return output[:limit]
