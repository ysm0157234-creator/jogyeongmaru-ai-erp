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
    ImageSearchResult,
    WebSearchResult,
)
from app.services.wikimedia_service import search_commons_images


class PlantResearchError(RuntimeError):
    pass


BUILD_VERSION = "v16.0-single-gemini-fallback"


def _norm(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9가-힣]+",
        "",
        str(value or "").lower(),
    )


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
    images: list[ImageSearchResult],
    role: str,
    prefix: str,
    variety_name: str,
) -> list[dict[str, Any]]:
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
            "id": f"{prefix}-serper-{index}",
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
                or "Serper 이미지 검색"
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


def _commons_candidates(
    variety_name: str,
    role: str,
    prefix: str,
) -> list[dict[str, Any]]:
    terms = _terms(variety_name)

    queries = (
        (
            f'"{variety_name}" whole plant',
            f'"{variety_name}" habit',
        )
        if role == "overall"
        else (
            f'"{variety_name}" close up',
            f'"{variety_name}" flower',
            f'"{variety_name}" foliage',
            f'"{variety_name}" catkin',
        )
    )

    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for query in queries:
        for image in search_commons_images(
            query,
            limit=12,
        ):
            key = (
                image.original_url
                or image.thumbnail_url
            )

            if not key or key in seen:
                continue

            searchable = " ".join(
                (
                    image.title,
                    image.description_url,
                    image.original_url,
                )
            )

            relevance = _score(
                searchable,
                terms,
            )

            if relevance <= 0:
                continue

            seen.add(key)

            output.append(
                {
                    "id": (
                        f"{prefix}-commons-"
                        f"{len(output) + 1}"
                    ),
                    "title": (
                        image.title
                        or (
                            f"{variety_name} 전체 모습"
                            if role == "overall"
                            else f"{variety_name} 근접 모습"
                        )
                    ),
                    "role": role,
                    "preview_url": (
                        image.thumbnail_url
                    ),
                    "download_url": (
                        image.original_url
                    ),
                    "backup_url": (
                        image.thumbnail_url
                    ),
                    "source_url": (
                        image.description_url
                    ),
                    "source": (
                        "Wikimedia Commons"
                    ),
                    "license": (
                        image.license_name
                        or (
                            "Commons 원본 페이지에서 "
                            "라이선스 확인"
                        )
                    ),
                    "recommended": False,
                    "research_query": (
                        variety_name
                    ),
                    "relevance_score": (
                        relevance + 55
                    ),
                }
            )

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
        f'"{name}" accepted scientific name authority',
        f'"{name}" full botanical name author citation',
        f'"{name}" flower colour bloom months mature height cm',
        f'"{name}" RHS height flowering colour',
        f'"{name}" Kew accepted name',
        f'"{name}" Missouri Botanical Garden',
        f'"{name}" propagation origin breeder',
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
    combined = _combined_source_text(sources)
    candidates = re.findall(
        r"\b([A-Z][a-z-]+\s+(?:×\s*)?[a-z][a-z-]+(?:\s+['’][^'’]+['’])?(?:\s+[A-Z][A-Za-z. -]{0,30})?)",
        combined,
    )
    cleaned=[]
    genus=(name.split()[0].capitalize() if name.split() else "")
    for c in candidates:
        c=re.sub(r"\s+", " ", c).strip(" ,.;:")
        if genus and not c.startswith(genus+" "):
            continue
        if len(c.split())>=2:
            cleaned.append(c)
    if cleaned:
        # 동일 학명의 명명자 유무를 하나로 보고 빈도 우선
        from collections import Counter
        base=Counter(" ".join(x.split()[:2]) for x in cleaned)
        winner=base.most_common(1)[0][0]
        detailed=[x for x in cleaned if x.startswith(winner)]
        return max(detailed, key=len)
    # 입력 자체가 이명법이면 그대로 사용
    if re.match(r"^[A-Z][a-z-]+\s+(?:×\s*)?[a-z][a-z-]+", name):
        return name
    # 속명만 들어온 경우 검색결과에서 못 찾았을 때 안전하게 spp. 사용
    return f"{genus} spp." if genus else name

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
        f'"{name}" botanical profile characteristics',
        f'"{name}" scientific name authority',
        f'"{name}" flower colour flowering period height',
        f'"{name}" origin propagation breeder',
        f'"{name}" RHS',
        f'"{name}" Kew',
        f'"{name}" Missouri Botanical Garden',
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

    generated["scientific_name"] = (
        _clean_text(
            generated.get("scientific_name")
        )
    )

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

    try:
        overall_search = (
            search.search_images(
                f'"{name}" whole plant habit botanical',
                num=14,
            )
        )

        closeup_search = (
            search.search_images(
                f'"{name}" close up flower foliage',
                num=14,
            )
        )
    except GoogleSearchError as exc:
        raise PlantResearchError(
            f"Serper 이미지 검색 실패: {exc}"
        ) from exc

    overall = _dedupe_images(
        _image_candidates(
            overall_search,
            "overall",
            "overall",
            name,
        )
        + _commons_candidates(
            name,
            "overall",
            "overall",
        )
    )

    closeup = _dedupe_images(
        _image_candidates(
            closeup_search,
            "closeup",
            "closeup",
            name,
        )
        + _commons_candidates(
            name,
            "closeup",
            "closeup",
        )
    )

    if not overall:
        raise PlantResearchError(
            f"'{name}'의 전체 모습 사진을 "
            "찾지 못했습니다."
        )

    if not closeup:
        raise PlantResearchError(
            f"'{name}'의 근접 사진을 "
            "찾지 못했습니다."
        )

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
            "overall": overall[0]["id"],
            "closeup": closeup[0]["id"],
        },
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
                "status": "후보 선택 완료",
            },
            {
                "name": "근접 사진",
                "status": "후보 선택 완료",
            },
        ],
        "warnings": [
            "사진은 제출 전에 해당 식물과 "
            "일치하는지 최종 확인하세요.",
        ],
        "research_provider": {
            "web": "Serper Google Search",
            "images": (
                "Serper Image Search + "
                "Wikimedia Commons"
            ),
            "generation": (
                f"Gemini {gemini_model}" if gemini_model else "Serper 검색 기반 자동 초안"
            ),
            "gemini_fallback_reason": fallback_reason,
        },
    }
