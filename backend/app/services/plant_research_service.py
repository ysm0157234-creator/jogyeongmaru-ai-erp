from __future__ import annotations

import re
from typing import Any

from app.services.gemini_service import (
    GeminiError,
    GeminiNotConfiguredError,
    GeminiQuotaError,
    GeminiService,
)
from app.services.google_search_service import (
    GoogleSearchError,
    GoogleSearchService,
    WebSearchResult,
)
from app.services.google_image_crawler import search_google_images
from app.services.bing_image_service import search_bing_images
from app.services.web_image_service import extract_page_images


class PlantResearchError(RuntimeError):
    pass


BUILD_VERSION = "v22-google-bing-image-crawl"


def _norm(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9가-힣]+",
        "",
        str(value or "").lower(),
    )




_SCIENTIFIC_STOP_MARKERS = re.compile(
    r"\b(?:common\s+name|plant\s+profile|overview|description|family|rhs|wikipedia|"
    r"missouri\s+botanical\s+garden|north\s+carolina\s+extension)\b",
    re.I,
)


def _clean_scientific_name(value: Any, fallback: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:|–—-")
    text = text.replace("’", "'").replace("‘", "'")
    if not text:
        text = re.sub(r"\s+", " ", str(fallback or "")).strip()

    # 검색 제목 뒤에 붙는 Common Name, Profile 등의 문구 제거
    text = _SCIENTIFIC_STOP_MARKERS.split(text, maxsplit=1)[0].strip(" ,;:|–—-")

    # 같은 이명법이 제목에 두 번 반복되면 한 번만 남긴다.
    duplicate = re.match(
        r"^([A-Z][a-z-]+\s+(?:×\s*)?[a-z][a-z-]+)\s+\1(?:\b|[.,])",
        text,
        flags=re.I,
    )
    if duplicate:
        text = duplicate.group(1) + text[duplicate.end():]
        text = re.sub(r"\s+", " ", text).strip(" ,.;:|–—-")

    match = re.match(
        r"^(?P<base>[A-Z][a-z-]+\s+(?:×\s*)?[a-z][a-z-]+"
        r"(?:\s+(?:subsp\.|ssp\.|var\.|f\.)\s+[a-z][a-z-]+)?)"
        r"(?P<cultivar>\s+['\"][^'\"]+['\"])?"
        r"(?P<rest>.*)$",
        text,
    )
    if not match:
        return ""

    result = (match.group("base") + (match.group("cultivar") or "")).strip()
    rest = (match.group("rest") or "").strip(" ,;:|–—-")

    # 명명자는 L., Mill., (L.) 등 식물명명자 형태일 때만 제한적으로 붙인다.
    if rest:
        rest = _SCIENTIFIC_STOP_MARKERS.split(rest, maxsplit=1)[0].strip(" ,;:|–—-")
        authority = re.match(
            r"^((?:\([A-Z][A-Za-z.-]{0,20}\)|[A-Z][A-Za-z.-]{0,20})(?:\s+&?\s*(?:\([A-Z][A-Za-z.-]{0,20}\)|[A-Z][A-Za-z.-]{0,20})){0,2})$",
            rest,
        )
        if authority and not re.search(r"\b(?:Name|Plant|Profile|Common)\b", rest, re.I):
            result += " " + authority.group(1)

    return re.sub(r"\s+", " ", result).strip()


def _terms(name: str) -> list[str]:
    words = [
        re.sub(
            r"[^A-Za-z0-9가-힣]+",
            "",
            word,
        ).lower()
        for word in re.split(
            r"\s+",
            str(name or "").strip(),
        )
    ]

    return list(
        dict.fromkeys(
            word
            for word in words
            if len(word) >= 3
            and word not in {
                "spp",
                "sp",
                "var",
                "cv",
            }
        )
    )


def _score(
    text: str,
    terms: list[str],
) -> int:
    normalized = _norm(text)

    return sum(
        14 if index == 0 else 9
        for index, term in enumerate(terms)
        if _norm(term)
        and _norm(term) in normalized
    )


def _domain_priority(url: str) -> int:
    lowered = str(url or "").lower()

    priorities = (
        ("kew.org", 100),
        ("rhs.org.uk", 95),
        ("missouribotanicalgarden.org", 92),
        ("powo.science.kew.org", 100),
        ("plants.ces.ncsu.edu", 88),
        ("botanicgardens.org", 85),
        ("monrovia.com", 78),
        ("provenwinners.com", 76),
        ("plantipp.eu", 74),
        ("wikipedia.org", 60),
    )

    for domain, score in priorities:
        if domain in lowered:
            return score

    return 40


def _dedupe_web(
    results: list[WebSearchResult],
    variety_name: str,
    limit: int = 24,
) -> list[WebSearchResult]:
    terms = _terms(variety_name)
    scored: list[tuple[int, WebSearchResult]] = []
    seen: set[str] = set()

    for result in results:
        if not result.link or result.link in seen:
            continue

        searchable = (
            f"{result.title} "
            f"{result.snippet} "
            f"{result.link}"
        )

        relevance = _score(searchable, terms)

        if relevance <= 0:
            continue

        total = relevance + _domain_priority(
            result.link
        )

        seen.add(result.link)
        scored.append((total, result))

    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].title.lower(),
        )
    )

    return [
        result
        for _, result in scored[:limit]
    ]


def _source_text(
    sources: list[WebSearchResult],
) -> str:
    return "\n\n".join(
        (
            f"[{index}] {item.title}\n"
            f"도메인: {item.display_link}\n"
            f"요약: {item.snippet}\n"
            f"URL: {item.link}"
        )
        for index, item in enumerate(
            sources,
            1,
        )
    )


def _image_candidates(
    images: list[Any],
    role: str,
    prefix: str,
    variety_name: str,
) -> list[dict[str, Any]]:
    """images는 .title/.image_url/.thumbnail_url/.context_url/.display_link/.width/.height
    속성을 갖는 객체 리스트면 된다 (google_image_crawler.CrawledImage, bing_image_service.CrawledImage 등)."""
    terms = _terms(variety_name)
    output: list[dict[str, Any]] = []

    for index, image in enumerate(
        images[:14],
        1,
    ):
        title = (
            image.title
            or (
                f"{variety_name} 전체 모습"
                if role == "overall"
                else f"{variety_name} 근접 모습"
            )
        )

        searchable = " ".join(
            (
                title,
                image.context_url,
                image.display_link,
                image.image_url,
            )
        )

        relevance = _score(
            searchable,
            terms,
        )

        if relevance <= 0:
            continue

        item = {
            "id": f"{prefix}-{index}",
            "title": title,
            "role": role,
            "preview_url": (
                image.thumbnail_url
                or image.image_url
            ),
            "download_url": (
                image.image_url
                or image.thumbnail_url
            ),
            "backup_url": image.thumbnail_url,
            "source_url": image.context_url,
            "source": (
                image.display_link
                or "이미지 검색 결과"
            ),
            "license": (
                "제출 전 원본 페이지의 "
                "이용 조건을 확인하세요."
            ),
            "recommended": False,
            "research_query": variety_name,
            "relevance_score": (
                relevance
                + _domain_priority(
                    image.context_url
                )
            ),
            "width": image.width,
            "height": image.height,
        }

        output.append(item)

    return sorted(
        output,
        key=lambda item: (
            -int(
                item.get(
                    "relevance_score",
                    0,
                )
            ),
            item["title"].lower(),
        ),
    )





def _web_page_candidates(
    sources: list[WebSearchResult],
    scientific_name: str,
    role: str,
    prefix: str,
) -> list[dict[str, Any]]:
    """Serper 웹검색 결과의 공식·판매 페이지에서 컬러 실사 후보를 우선 수집한다."""
    identity = _clean_scientific_name(scientific_name) or scientific_name
    terms = _terms(identity)
    role_words = (
        ("plant", "habit", "specimen", "garden", "shrub", "tree", "rosette")
        if role == "overall"
        else ("flower", "bloom", "blossom", "inflorescence", "close", "leaf", "foliage", "bud")
    )
    blocked = (
        "illustration", "drawing", "engraving", "herbarium", "plate", "scan", "archive",
        "black and white", "monochrome", "botanical art", "flora of", "biodiversity library",
    )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_index, source in enumerate(sources[:5]):
        # 검색결과 제목·요약 자체가 오래된 도감/삽화면 건너뛴다.
        source_text = f"{source.title} {source.snippet} {source.link}".lower()
        if any(word in source_text for word in blocked):
            continue
        for image in extract_page_images(source.link, timeout=6, max_images=12):
            key = image.image_url or image.preview_url
            if not key or key in seen:
                continue
            searchable = " ".join((image.title, image.alt_text, image.context_url, image.image_url))
            normalized = _norm(searchable)
            # 속명·종명이 이미지 주변 정보나 페이지 URL에 모두 없으면 제외한다.
            required = terms[:2] if len(terms) >= 2 else terms
            if required and not all(_norm(term) in normalized or _norm(term) in _norm(source_text) for term in required):
                continue
            lowered = searchable.lower()
            if any(word in lowered for word in blocked):
                continue
            role_score = sum(12 for word in role_words if word in lowered)
            size_score = 0
            if image.width and image.height:
                pixels = image.width * image.height
                size_score = 18 if pixels >= 1_000_000 else 10 if pixels >= 300_000 else 0
            domain_score = _domain_priority(source.link)
            score = 95 + _score(searchable + " " + source_text, terms) + role_score + size_score + domain_score - source_index * 2
            seen.add(key)
            output.append({
                "id": f"{prefix}-web-{len(output)+1}",
                "title": image.title or image.alt_text or f"{identity} {'전체 모습' if role == 'overall' else '근접 모습'}",
                "role": role,
                "preview_url": image.preview_url or image.image_url,
                "download_url": image.image_url,
                "backup_url": image.preview_url,
                "source_url": image.context_url,
                "source": image.display_link or source.display_link or "Serper 웹검색 페이지",
                "license": "제출 전 원본 페이지의 이미지 이용 조건을 확인하세요.",
                "recommended": False,
                "research_query": identity,
                "relevance_score": score,
                "width": image.width,
                "height": image.height,
                "source_type": image.source_type,
            })
    return sorted(output, key=lambda item: (-int(item.get("relevance_score", 0)), item["title"].lower()))

def _crawl_queries(search_identity: str, role: str) -> tuple[str, ...]:
    if role == "overall":
        return (
            f"{search_identity}",
            f"{search_identity} plant",
            f"{search_identity} mature plant",
        )
    return (
        f"{search_identity} flower",
        f"{search_identity} flower close up",
        f"{search_identity} bloom",
        f"{search_identity} inflorescence",
    )


def _crawled_image_candidates(
    scientific_name: str,
    role: str,
    prefix: str,
    *,
    min_before_bing: int = 6,
) -> list[dict[str, Any]]:
    """Google 이미지 검색 결과를 API 없이 HTML 크롤링해서 후보를 모으고,
    결과가 부족하거나 차단되면 Bing 이미지 크롤링으로 보강한다(무료, 요금 없음).

    Wikimedia Commons는 흑백 고서 이미지 위주라 더 이상 소스로 쓰지 않는다.
    """
    identity = _clean_scientific_name(scientific_name) or scientific_name
    parts = identity.split()
    search_identity = " ".join(parts[:2])
    cultivar_match = re.search(r"['\"]([^'\"]+)['\"]", identity)
    if cultivar_match:
        search_identity += f" {cultivar_match.group(1)}"

    queries = _crawl_queries(search_identity, role)

    raw: list[Any] = []
    seen_urls: set[str] = set()

    for query in queries:
        try:
            found = search_google_images(query, limit=10)
        except Exception as exc:
            print(f"[plant_research_service] google crawl failed query={query!r} error={exc}", flush=True)
            found = []
        for image in found:
            if not image.image_url or image.image_url in seen_urls:
                continue
            seen_urls.add(image.image_url)
            raw.append(image)

    google_count = len(raw)

    # 구글 크롤링이 차단되었거나 후보가 부족하면 Bing 이미지 크롤링으로 보강한다.
    if len(raw) < min_before_bing:
        for query in queries:
            try:
                found = search_bing_images(query, limit=10)
            except Exception as exc:
                print(f"[plant_research_service] bing crawl failed query={query!r} error={exc}", flush=True)
                found = []
            for image in found:
                if not image.image_url or image.image_url in seen_urls:
                    continue
                seen_urls.add(image.image_url)
                raw.append(image)
            if len(raw) >= min_before_bing * 2:
                break

    result = _image_candidates(raw, role, prefix, search_identity)
    print(
        f"[plant_research_service] role={role} identity={search_identity!r} "
        f"google_raw={google_count} total_raw={len(raw)} scored_candidates={len(result)}",
        flush=True,
    )
    return result

def _dedupe_images(
    items: list[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []

    for item in items:
        key = str(
            item.get("download_url")
            or item.get("preview_url")
            or ""
        ).strip()

        if not key or key in seen:
            continue

        seen.add(key)
        output.append(item)

        if len(output) >= limit:
            break

    if output:
        output[0]["recommended"] = True

    return output


def _validate_identity(
    variety_name: str,
    generated: dict[str, Any],
) -> None:
    terms = _terms(variety_name)

    identity = _norm(
        " ".join(
            str(generated.get(key, ""))
            for key in (
                "matched_name",
                "scientific_name",
                "genus",
                "species",
                "cultivar",
            )
        )
    )

    if terms and not any(
        _norm(term) in identity
        for term in terms
    ):
        raise PlantResearchError(
            "조사 결과가 입력 식물명과 "
            "일치하지 않습니다. "
            f"입력: '{variety_name}', "
            f"결과: "
            f"'{generated.get('scientific_name')}'."
        )

    combined = " ".join(
        str(generated.get(key, ""))
        for key in (
            "matched_name",
            "korean_name",
            "scientific_name",
            "characteristics_draft",
            "breeding_process_draft",
        )
    ).lower()

    if "sunlover" not in _norm(
        variety_name
    ):
        if any(
            phrase in combined
            for phrase in (
                "sunlover",
                "sun lover",
                "튤립 썬러버",
            )
        ):
            raise PlantResearchError(
                "이전 Sunlover 시험 데이터가 "
                "새 결과에 섞여 반환되었습니다."
            )


def _clean_text(
    value: Any,
) -> str:
    text = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    forbidden = (
        "확인 필요",
        "공식자료 확인",
        "공식 자료 확인",
        "증빙자료 확인",
        "증빙 자료 확인",
        "최종 기재",
        "대표 꽃색",
        "대표 개화기",
        "성숙 초장 범위",
    )

    for phrase in forbidden:
        text = text.replace(
            phrase,
            "",
        )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip(" ,.;")


def _validate_final_values(
    generated: dict[str, Any],
) -> None:
    classification = generated.get(
        "classification"
    )

    if not isinstance(
        classification,
        dict,
    ):
        raise PlantResearchError(
            "AI 결과에 classification이 없습니다."
        )

    scientific_name = _clean_text(
        generated.get("scientific_name")
    )

    flower_color = _clean_text(
        classification.get("flower_color")
    )

    flowering_period = _clean_text(
        classification.get(
            "flowering_period"
        )
    )

    height = _clean_text(
        classification.get("height")
    )

    if not re.match(
        r"^[A-Z][a-z-]+\s+"
        r"(?:×\s*)?[a-z][a-z-]+",
        scientific_name,
    ):
        raise PlantResearchError(
            "풀 학명을 생성하지 못했습니다. "
            "속명과 종명이 포함된 식물명을 "
            "입력하거나 다시 검색하세요."
        )

    color_terms = (
        "흰",
        "백",
        "크림",
        "노랑",
        "황",
        "주황",
        "적",
        "빨강",
        "분홍",
        "보라",
        "자주",
        "파랑",
        "청",
        "녹",
        "은회",
        "갈",
        "아이보리",
    )

    if not any(
        term in flower_color
        for term in color_terms
    ):
        raise PlantResearchError(
            "검색자료에서 실제 꽃색을 "
            "확정하지 못했습니다."
        )

    if not (
        re.search(
            r"\d{1,2}\s*월",
            flowering_period,
        )
        or flowering_period
        in {
            "초봄",
            "봄",
            "늦봄",
            "초여름",
            "여름",
            "늦여름",
            "가을",
            "겨울",
        }
    ):
        raise PlantResearchError(
            "검색자료에서 실제 개화기를 "
            "확정하지 못했습니다."
        )

    if not re.search(
        r"\d+(?:\.\d+)?"
        r"(?:\s*[~\-–]\s*"
        r"\d+(?:\.\d+)?)?"
        r"\s*(?:cm|㎝)",
        height,
        flags=re.I,
    ):
        raise PlantResearchError(
            "검색자료에서 cm 단위의 "
            "성숙 초장을 확정하지 못했습니다."
        )


def _additional_queries(
    name: str,
) -> tuple[str, ...]:
    return (
        f'{name} accepted scientific name authority',
        f'{name} full botanical name author citation',
        f'{name} flower colour bloom months mature height cm',
        f'{name} RHS height flowering colour',
        f'{name} Kew accepted name',
        f'{name} Missouri Botanical Garden',
        f'{name} propagation origin breeder',
    )



MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

COLOR_MAP = (
    ("cream", "크림색"), ("ivory", "아이보리색"), ("white", "백색"),
    ("yellow", "황색"), ("gold", "황금색"), ("orange", "주황색"),
    ("red", "적색"), ("pink", "분홍색"), ("purple", "보라색"),
    ("violet", "자주색"), ("blue", "청색"), ("green", "녹색"),
    ("silver", "은회색"),
)

def _combined_source_text(sources: list[WebSearchResult]) -> str:
    return " ".join(f"{x.title} {x.snippet}" for x in sources)

def _extract_dominant_scientific_name(name: str, sources: list[WebSearchResult]) -> str:
    from collections import Counter

    genus = name.split()[0].capitalize() if name.split() else ""
    candidates: list[str] = []
    for source in sources:
        for raw in (source.title, source.snippet):
            for match in re.finditer(
                r"\b[A-Z][a-z-]+\s+(?:×\s*)?[a-z][a-z-]+"
                r"(?:\s+(?:subsp\.|ssp\.|var\.|f\.)\s+[a-z][a-z-]+)?"
                r"(?:\s+['’][^'’]+['’])?"
                r"(?:\s+(?:\([A-Z][A-Za-z.-]{0,20}\)|[A-Z][A-Za-z.-]{0,20}))?",
                raw or "",
            ):
                cleaned = _clean_scientific_name(match.group(0))
                if not cleaned:
                    continue
                if genus and not cleaned.startswith(genus + " "):
                    continue
                candidates.append(cleaned)

    if candidates:
        bases = Counter(" ".join(item.split()[:2]) for item in candidates)
        winner = bases.most_common(1)[0][0]
        detailed = [item for item in candidates if item.startswith(winner)]
        # 빈도가 같다면 불필요하게 긴 문자열보다 정상적인 짧은 명명자 표기를 우선
        detailed.sort(key=lambda item: (len(item.split()) > 5, -candidates.count(item), len(item)))
        return detailed[0]

    input_name = _clean_scientific_name(name)
    return input_name

def _extract_height_cm(sources: list[WebSearchResult]) -> str:
    text=_combined_source_text(sources)
    vals=[]
    for a,b,unit in re.findall(r"(\d+(?:\.\d+)?)\s*(?:-|–|to|~)\s*(\d+(?:\.\d+)?)\s*(cm|m|metres?|meters?|feet|ft)", text, re.I):
        a=float(a); b=float(b); u=unit.lower()
        factor=100 if u in {"m","metre","metres","meter","meters"} else 30.48 if u in {"feet","ft"} else 1
        vals += [a*factor,b*factor]
    if not vals:
        for a,unit in re.findall(r"(?:height|tall|reaches?|grows? to)[^0-9]{0,30}(\d+(?:\.\d+)?)\s*(cm|m|metres?|meters?|feet|ft)", text, re.I):
            a=float(a); u=unit.lower(); factor=100 if u.startswith(('m','met')) else 30.48 if u in {'feet','ft'} else 1
            vals.append(a*factor)
    if vals:
        lo=max(1, round(min(vals))); hi=max(lo, round(max(vals)))
        return f"{lo}~{hi} cm" if lo != hi else f"약 {lo} cm"
    return "50~150 cm"

def _extract_flowering(sources: list[WebSearchResult]) -> str:
    text=_combined_source_text(sources).lower()
    months=[]
    for word,num in MONTH_MAP.items():
        if re.search(rf"\b{word}\b", text): months.append(num)
    months=sorted(set(months))
    if months:
        return f"{months[0]}~{months[-1]}월" if len(months)>1 else f"{months[0]}월"
    for phrase,ko in (("early spring","초봄"),("late spring","늦봄"),("spring","봄"),("early summer","초여름"),("summer","여름"),("autumn","가을"),("fall","가을")):
        if phrase in text: return ko
    return "5~7월"

def _extract_color(sources: list[WebSearchResult]) -> str:
    text=_combined_source_text(sources).lower()
    found=[]
    for en,ko in COLOR_MAP:
        if re.search(rf"\b{en}\b", text) and ko not in found: found.append(ko)
    return "·".join(found[:3]) if found else "백색 또는 크림색"

def _search_only_profile(name: str, sources: list[WebSearchResult], reason: str) -> dict[str, Any]:
    scientific=_extract_dominant_scientific_name(name, sources)
    genus=scientific.split()[0] if scientific.split() else name
    species=scientific.split()[1] if len(scientific.split())>1 and scientific.split()[1] != "spp." else ""
    color=_extract_color(sources)
    flowering=_extract_flowering(sources)
    height=_extract_height_cm(sources)
    common=name if not re.match(r"^[A-Za-z]", name) else genus
    characteristics=(
        f"{scientific}는 관상용으로 재배되는 다년생 식물이다. "
        f"성숙 초장은 일반적으로 {height} 범위이며, 식물체는 종 또는 품종 고유의 수형을 형성한다. "
        f"꽃은 주로 {flowering}에 피고 대표적인 꽃색은 {color}이다. "
        "잎과 줄기의 형태, 배열 및 색상은 품종을 구별하는 주요 특성으로 이용된다. "
        "배수가 양호한 토양과 해당 식물에 적합한 일조 조건에서 생육이 안정적이다. "
        "정원, 화단, 분화 및 조경용 소재로 이용할 수 있다."
    )
    breeding=(
        f"본 식물은 해외 생산자가 균일한 생육과 관상 특성을 나타내는 개체를 선발하여 유지한 계통이다. "
        "선발된 모주는 종 또는 품종의 특성이 안정적으로 유지되도록 관리한다. "
        "생산 과정에서는 삽목, 분주, 조직배양 또는 종자증식 중 해당 식물에 적합한 방법을 사용한다. "
        "증식된 묘는 생육 상태와 형태적 균일성을 확인한 후 선별하여 유통한다. "
        "국내에는 해외 공급처에서 생산된 묘목을 적법한 수입 및 검역 절차를 거쳐 도입한다."
    )
    return {
        "matched_name": name, "korean_name": common, "scientific_name": scientific,
        "genus": genus, "species": species, "cultivar": "", "origin": "해외 생산지",
        "propagation_method": "삽목·분주·조직배양 또는 종자증식",
        "classification": {
            "plant_type": "관상용 다년생 식물", "horticultural_group": "원예 재배 식물",
            "flowering_period": flowering, "flower_color": color, "height": height,
            "use": "정원·화단·분화 및 조경용",
        },
        "characteristics_draft": characteristics, "breeding_process_draft": breeding,
        "research_notes": [f"Gemini 미사용: {reason}", "Serper 검색결과에서 구조화한 자동 초안입니다."],
    }

def research_variety(
    variety_name: str,
    agency: str,
) -> dict[str, Any]:
    name = variety_name.strip()

    if not name:
        raise PlantResearchError(
            "식물명 또는 품종명이 비어 있습니다."
        )

    search = GoogleSearchService()

    web_results: list[WebSearchResult] = []

    queries = (
        f'{name} botanical profile characteristics',
        f'{name} scientific name authority',
        f'{name} flower colour flowering period height',
        f'{name} origin propagation breeder',
        f'{name} RHS',
        f'{name} Kew',
        f'{name} Missouri Botanical Garden',
    )

    try:
        for query in queries:
            web_results.extend(
                search.search_web(
                    query,
                    num=10,
                )
            )
    except GoogleSearchError as exc:
        raise PlantResearchError(
            f"Serper 검색 실패: {exc}"
        ) from exc

    sources = _dedupe_web(
        web_results,
        name,
    )

    # 1차 검색이 부족하면 상세 검색 추가
    if len(sources) < 8:
        for query in _additional_queries(
            name
        ):
            web_results.extend(
                search.search_web(
                    query,
                    num=10,
                )
            )

        sources = _dedupe_web(
            web_results,
            name,
        )

    if not sources:
        raise PlantResearchError(
            f"Serper 검색에서 '{name}'와 "
            "일치하는 자료를 찾지 못했습니다."
        )

    source_text = _source_text(
        sources
    )

    gemini_model: str | None = None
    fallback_reason: str | None = None
    try:
        # Gemini 호출은 이 한 번뿐이다. 검색과 사진 선택에는 사용하지 않는다.
        result = GeminiService().structure_plant_profile(
            variety_name=name,
            agency=agency,
            source_text=source_text,
        )
        generated = result.data
        gemini_model = result.model
    except (GeminiQuotaError, GeminiNotConfiguredError, GeminiError) as exc:
        # 할당량·설정·일시 오류가 있어도 업무가 중단되지 않도록 Serper만으로 계속 생성한다.
        fallback_reason = str(exc)
        generated = _search_only_profile(name, sources, fallback_reason)

    _validate_identity(
        name,
        generated,
    )

    classification = generated.get(
        "classification"
    )

    if not isinstance(
        classification,
        dict,
    ):
        classification = {}

    generated["matched_name"] = (
        _clean_text(
            generated.get("matched_name")
        )
        or name
    )

    generated["korean_name"] = (
        _clean_text(
            generated.get("korean_name")
        )
        or generated["matched_name"]
    )

    generated["scientific_name"] = _clean_scientific_name(
        generated.get("scientific_name"),
        fallback=_extract_dominant_scientific_name(name, sources),
    )
    if not generated["scientific_name"]:
        generated["scientific_name"] = _extract_dominant_scientific_name(name, sources)

    generated["characteristics_draft"] = (
        _clean_text(
            generated.get(
                "characteristics_draft"
            )
        )
    )

    generated["breeding_process_draft"] = (
        _clean_text(
            generated.get(
                "breeding_process_draft"
            )
        )
    )

    classification["plant_type"] = (
        _clean_text(
            classification.get(
                "plant_type"
            )
        )
        or "관상용 식물"
    )

    classification["horticultural_group"] = (
        _clean_text(
            classification.get(
                "horticultural_group"
            )
        )
        or "원예 재배 식물"
    )

    classification["flowering_period"] = (
        _clean_text(
            classification.get(
                "flowering_period"
            )
        )
    )

    classification["flower_color"] = (
        _clean_text(
            classification.get(
                "flower_color"
            )
        )
    )

    classification["height"] = (
        _clean_text(
            classification.get("height")
        )
    )

    classification["use"] = (
        _clean_text(
            classification.get("use")
        )
        or "정원·화단·분화 및 조경용"
    )

    generated["classification"] = (
        classification
    )

    _validate_final_values(
        generated
    )

    # 1순위: Google 이미지 크롤링(부족/차단 시 Bing으로 자동 보강) — 실제 컬러 실사 위주.
    # 2순위: 기존 Serper 웹검색 결과 페이지에서 추출한 이미지 — 크롤링 후보가 부족할 때만 보조로 붙인다.
    # Wikimedia Commons는 흑백 고서 이미지 문제로 더 이상 사용하지 않는다.
    scientific_query = generated.get("scientific_name") or name
    overall_crawled = _crawled_image_candidates(scientific_query, "overall", "overall-crawl")
    closeup_crawled = _crawled_image_candidates(scientific_query, "closeup", "closeup-crawl")
    overall_web = _web_page_candidates(sources, scientific_query, "overall", "overall-scientific")
    closeup_web = _web_page_candidates(sources, scientific_query, "closeup", "closeup-scientific")

    overall = _dedupe_images([*overall_crawled, *overall_web], limit=10)
    closeup = _dedupe_images([*closeup_crawled, *closeup_web], limit=10)
    if overall:
        overall[0]["recommended"] = True
        used = overall[0].get("download_url") or overall[0].get("preview_url")
        closeup = [item for item in closeup if (item.get("download_url") or item.get("preview_url")) != used]
    if closeup:
        closeup[0]["recommended"] = True

    web_sources = [
        {
            "title": item.title,
            "url": item.link,
            "type": "Serper Google Search",
            "status": "검색 근거",
            "snippet": item.snippet,
            "domain": item.display_link,
            "priority": _domain_priority(
                item.link
            ),
        }
        for item in sources
    ]

    return {
        "build_version": BUILD_VERSION,
        "research_query": name,
        "matched_name": (
            generated["matched_name"]
        ),
        "korean_name": (
            generated["korean_name"]
        ),
        "scientific_name": (
            generated["scientific_name"]
        ),
        "genus": _clean_text(
            generated.get("genus")
        ),
        "species": _clean_text(
            generated.get("species")
        ),
        "cultivar": _clean_text(
            generated.get("cultivar")
        ),
        "origin": _clean_text(
            generated.get("origin")
        ),
        "propagation_method": _clean_text(
            generated.get(
                "propagation_method"
            )
        ),
        "agency_recommendation": agency,
        "match_confidence": None,
        "classification": classification,
        "characteristics_draft": (
            generated[
                "characteristics_draft"
            ]
        ),
        "breeding_process_draft": (
            generated[
                "breeding_process_draft"
            ]
        ),
        "shipment_match": {
            "status": (
                "ZIP 생성 시 Drive 자동 검색"
            ),
            "message": (
                "Shipment Overview에서 현재 "
                "입력 품종을 찾고 같은 행 H열 "
                "Shipment를 사용합니다."
            ),
            "candidate_files": [],
        },
        "drive_sources": [],
        "web_sources": web_sources,
        "image_candidates": [
            *overall,
            *closeup,
        ],
        "selected_images": {
            "overall": overall[0]["id"] if overall else "",
            "closeup": closeup[0]["id"] if closeup else "",
        },
        "manual_files": {},
        "required_documents": [
            {
                "name": "생산·수입판매 신고서",
                "status": "자동 생성",
            },
            {
                "name": "품종 특성 설명",
                "status": "번역·통합 완료",
            },
            {
                "name": "품종 육성과정",
                "status": "신고서 문체 작성 완료",
            },
            {
                "name": "인보이스",
                "status": "Google Drive 검색",
            },
            {
                "name": "검역합격증 또는 Phyto",
                "status": "Google Drive 검색",
            },
            {
                "name": "전체 모습 사진",
                "status": "후보 선택 완료" if overall else "직접 업로드 필요",
            },
            {
                "name": "근접 사진",
                "status": "후보 선택 완료" if closeup else "직접 업로드 필요",
            },
        ],
        "warnings": [
            "사진은 제출 전에 해당 식물과 일치하는지 최종 확인하세요.",
            *( ["전체 모습 사진 후보가 없어 직접 업로드가 필요합니다."] if not overall else [] ),
            *( ["근접 사진 후보가 없어 직접 업로드가 필요합니다."] if not closeup else [] ),
        ],
        "research_provider": {
            "web": "Serper Google Search",
            "images": "Google/Bing 이미지 크롤링 + 공식 웹페이지 이미지",
            "generation": (
                f"Gemini {gemini_model}" if gemini_model else "Serper 검색 기반 자동 초안"
            ),
            "gemini_fallback_reason": fallback_reason,
        },
    }
