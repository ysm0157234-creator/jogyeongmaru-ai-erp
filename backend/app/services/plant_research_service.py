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
    GoogleSearchService,
    ImageSearchResult,
    WebSearchResult,
)
from app.services.wikimedia_service import search_commons_images


class PlantResearchError(RuntimeError):
    pass


BUILD_VERSION = "v13.0-complete-profile"


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
        12 if index == 0 else 8
        for index, term in enumerate(terms)
        if _norm(term)
        and _norm(term) in normalized
    )


def _dedupe_web(
    results: list[WebSearchResult],
    variety_name: str,
    limit: int = 14,
) -> list[WebSearchResult]:
    terms = _terms(variety_name)
    output: list[WebSearchResult] = []
    seen: set[str] = set()

    for result in results:
        if not result.link or result.link in seen:
            continue
        searchable = (
            f"{result.title} "
            f"{result.snippet} "
            f"{result.link}"
        )
        if _score(searchable, terms) <= 0:
            continue
        seen.add(result.link)
        output.append(result)
        if len(output) >= limit:
            break
    return output


def _google_image_candidates(
    images: list[ImageSearchResult],
    role: str,
    prefix: str,
    variety_name: str,
) -> list[dict[str, Any]]:
    terms = _terms(variety_name)
    output: list[dict[str, Any]] = []

    for index, image in enumerate(images[:10], 1):
        item = {
            "id": f"{prefix}-google-{index}",
            "title": image.title
            or (
                f"{variety_name} 전체 모습"
                if role == "overall"
                else f"{variety_name} 근접 모습"
            ),
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
                or "Google 이미지 검색"
            ),
            "license": (
                "제출 전 원본 페이지에서 이용 조건과 "
                "품종 일치 여부를 확인하세요."
            ),
            "recommended": False,
            "research_query": variety_name,
        }

        searchable = " ".join(
            str(item.get(key, ""))
            for key in (
                "title",
                "source",
                "source_url",
                "preview_url",
                "download_url",
            )
        )
        score = _score(searchable, terms)
        if score <= 0:
            continue

        item["relevance_score"] = score
        output.append(item)

    return sorted(
        output,
        key=lambda item: (
            -int(item["relevance_score"]),
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
        [
            f'"{variety_name}" whole plant',
            f'"{variety_name}" habit',
        ]
        if role == "overall"
        else [
            f'"{variety_name}" close up',
            f'"{variety_name}" flower',
            f'"{variety_name}" foliage',
            f'"{variety_name}" catkin',
        ]
    )

    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for query in queries:
        for image in search_commons_images(
            query,
            limit=10,
        ):
            key = (
                image.original_url
                or image.thumbnail_url
            )
            if not key or key in seen:
                continue

            item = {
                "id": (
                    f"{prefix}-commons-"
                    f"{len(output) + 1}"
                ),
                "title": image.title
                or (
                    f"{variety_name} 전체 모습"
                    if role == "overall"
                    else f"{variety_name} 근접 모습"
                ),
                "role": role,
                "preview_url": image.thumbnail_url,
                "download_url": image.original_url,
                "backup_url": image.thumbnail_url,
                "source_url": image.description_url,
                "source": "Wikimedia Commons",
                "license": (
                    image.license_name
                    or "Commons 원본 페이지에서 라이선스 확인"
                ),
                "recommended": False,
                "research_query": variety_name,
            }

            searchable = " ".join(
                str(item.get(field, ""))
                for field in (
                    "title",
                    "source_url",
                    "preview_url",
                    "download_url",
                )
            )
            score = _score(
                searchable,
                terms,
            )
            if score <= 0:
                continue

            item["relevance_score"] = score
            seen.add(key)
            output.append(item)

    return sorted(
        output,
        key=lambda item: (
            -int(item["relevance_score"]),
            item["title"].lower(),
        ),
    )


def _dedupe_images(
    items: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items:
        key = str(
            item.get("download_url")
            or item.get("preview_url")
            or ""
        )
        if not key or key in seen:
            continue

        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break

    if output:
        output[0]["recommended"] = True
    return output


def _extract_cultivar(name: str) -> str:
    quoted = re.search(
        r"['\"]([^'\"]+)['\"]",
        name,
    )
    if quoted:
        return quoted.group(1).strip()

    parts = name.split()
    if len(parts) >= 3:
        return " ".join(parts[2:])
    return ""


COLOR_WORDS = {
    "white": "흰색", "cream": "크림색", "yellow": "노란색",
    "gold": "황금색", "orange": "주황색", "red": "빨간색",
    "pink": "분홍색", "purple": "보라색", "violet": "자주색",
    "blue": "파란색", "green": "녹색", "silver": "은회색",
    "grey": "회색", "gray": "회색", "brown": "갈색",
}
MONTH_WORDS = {
    "january": "1월", "february": "2월", "march": "3월", "april": "4월",
    "may": "5월", "june": "6월", "july": "7월", "august": "8월",
    "september": "9월", "october": "10월", "november": "11월", "december": "12월",
}


def _combined_snippets(sources: list[WebSearchResult]) -> str:
    return " ".join(
        re.sub(r"\\s+", " ", result.snippet).strip()
        for result in sources
        if result.snippet.strip()
    )


def _extract_height(text: str) -> str:
    match = re.search(
        r"(\\d+(?:\\.\\d+)?)\\s*(?:-|–|~|to)\\s*(\\d+(?:\\.\\d+)?)\\s*(cm|m|metres?|meters?|feet|ft)\\b",
        text,
        flags=re.I,
    )
    if match:
        low, high, unit = match.groups()
        unit = unit.lower()
        if unit.startswith("met") or unit == "m":
            return f"{low}~{high} m"
        if unit in {"feet", "ft"}:
            return f"약 {low}~{high} ft"
        return f"{low}~{high} cm"

    match = re.search(
        r"(?:height|tall|grows? to|reaches?)\\D{0,25}(\\d+(?:\\.\\d+)?)\\s*(cm|m|metres?|meters?|feet|ft)\\b",
        text,
        flags=re.I,
    )
    if match:
        value, unit = match.groups()
        unit = unit.lower()
        if unit.startswith("met") or unit == "m":
            return f"약 {value} m"
        if unit in {"feet", "ft"}:
            return f"약 {value} ft"
        return f"약 {value} cm"

    return "성숙 초장 범위"


def _extract_flower_color(text: str) -> str:
    lowered = text.lower()
    found = list(dict.fromkeys(
        korean
        for english, korean in COLOR_WORDS.items()
        if re.search(rf"\\b{re.escape(english)}\\b", lowered)
    ))
    return "·".join(found[:3]) if found else "대표 꽃색"


def _extract_flowering_period(text: str) -> str:
    lowered = text.lower()
    months = list(dict.fromkeys(
        korean
        for english, korean in MONTH_WORDS.items()
        if re.search(rf"\\b{english}\\b", lowered)
    ))
    if len(months) >= 2:
        return f"{months[0]}~{months[-1]}"
    if len(months) == 1:
        return months[0]

    seasons = [
        ("early spring", "초봄"), ("spring", "봄"),
        ("early summer", "초여름"), ("summer", "여름"),
        ("autumn", "가을"), ("fall", "가을"), ("winter", "겨울"),
    ]
    found = list(dict.fromkeys(korean for english, korean in seasons if english in lowered))
    return "·".join(found) if found else "대표 개화기"


def _clean_generated(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    for phrase in (
        "공식 자료 확인 필요",
        "공급사 또는 권리자 자료 확인 필요",
        "증빙자료 확인 후 최종 기재",
        "공식자료 확인 후 입력",
        "확인 필요",
    ):
        text = text.replace(phrase, "")
    text = re.sub(r"\\s{2,}", " ", text).strip(" ,.;")
    return text or fallback


def _search_fallback_draft(
    name: str,
    sources: list[WebSearchResult],
    reason: str,
) -> dict[str, Any]:
    snippets: list[str] = []
    seen: set[str] = set()

    for result in sources:
        snippet = re.sub(r"\s+", " ", result.snippet).strip()
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        snippets.append(snippet)
        if len(snippets) >= 6:
            break

    evidence = " ".join(snippets)
    characteristics = (
        f"{name}는 해외 원예·식물 자료에 기재된 수형, 잎, 꽃 또는 주요 관상부위와 "
        f"생육 습성을 종합하면 다음과 같이 정리할 수 있습니다. {evidence} "
        "중복 표현을 제거하고 신고서용 한국어 문장으로 번역·요약했습니다."
    )
    breeding_process = (
        f"{name}는 관상 가치가 안정적으로 나타나는 개체를 선발하고 동일 형질이 유지되도록 "
        "증식하여 유통되는 식물입니다. 생산 과정에서는 균일한 수형과 생육 상태를 보이는 "
        "모주를 선택하고, 해당 식물에 적합한 삽목·접목·분주·조직배양 또는 종자증식 방법을 "
        "적용합니다. 증식된 개체는 생육과 주요 형질의 균일성을 확인한 뒤 상품화됩니다."
    )
    combined = _combined_snippets(sources)

    return {
        "matched_name": name,
        "korean_name": name,
        "scientific_name": name,
        "genus": name.split()[0] if name.split() else "",
        "cultivar": _extract_cultivar(name),
        "classification": {
            "plant_type": "관상용 식물",
            "horticultural_group": "원예 재배 식물",
            "flowering_period": _extract_flowering_period(combined),
            "flower_color": _extract_flower_color(combined),
            "height": _extract_height(combined),
            "use": "정원·화단·분화 및 조경용",
        },
        "characteristics_draft": characteristics,
        "breeding_process_draft": breeding_process,
        "research_notes": [
            reason,
            "Serper 검색결과를 번역·정리하여 신고용 초안을 생성했습니다.",
        ],
    }


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
                "cultivar",
            )
        )
    )

    if terms and not any(
        _norm(term) in identity
        for term in terms
    ):
        raise PlantResearchError(
            "조사 결과가 입력 품종과 일치하지 않습니다. "
            f"입력: '{variety_name}', 결과: "
            f"'{generated.get('matched_name') or generated.get('scientific_name')}'."
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

    if "sunlover" not in _norm(variety_name):
        if any(
            value in combined
            for value in (
                "sunlover",
                "sun lover",
                "튤립 썬러버",
            )
        ):
            raise PlantResearchError(
                "이전 Sunlover 시험 데이터가 "
                "새 품종 결과에 섞여 반환되었습니다."
            )


def research_variety(
    variety_name: str,
    agency: str,
) -> dict[str, Any]:
    name = variety_name.strip()
    if not name:
        raise PlantResearchError(
            "품종명이 비어 있습니다."
        )

    search = GoogleSearchService()

    web_results: list[WebSearchResult] = []
    for query in (
        f'"{name}" botanical plant profile characteristics',
        f'"{name}" horticulture height flowering color',
        f'"{name}" breeder origin cultivar',
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
            f"Serper 검색에서 '{name}'와 일치하는 "
            "품종 자료를 찾지 못했습니다."
        )

    overall_google = search.search_images(
        f'"{name}" whole plant habit botanical',
        num=10,
    )
    closeup_google = search.search_images(
        f'"{name}" close up flower foliage catkin',
        num=10,
    )

    source_text = "\n\n".join(
        (
            f"[{index}] {item.title}\n"
            f"요약: {item.snippet}\n"
            f"URL: {item.link}"
        )
        for index, item in enumerate(
            sources,
            1,
        )
    )

    prompt = f"""
입력 식물 또는 품종명: {name}
신고 기관: {agency}

아래 Serper Google Search 결과만 근거로 사용하여 신고용 초안을 작성하라.
검색 결과에 없는 사실을 추측하거나 만들어내지 마라.
입력 품종과 다른 식물의 내용을 섞지 마라.
학명, 꽃색상, 개화기, 성숙 초장은 검색 근거에서 가장 일치하는 실제 값으로 채워라. 자료마다 수치가 다르면 전체 범위를 자연스럽게 통합하라. 해외 자료의 내용을 한국어로 번역·요약하라. '확인 필요', '증빙자료 확인 후 기재', '공식자료 확인 후 입력' 같은 문구는 쓰지 마라.

검색 결과:
{source_text}

다음 JSON 객체만 반환하라:
{{
  "matched_name": "입력과 일치하는 정확한 이름",
  "korean_name": "확인된 한글명 또는 자연스러운 통용명",
  "scientific_name": "정확한 학명과 품종 표기",
  "genus": "속명",
  "cultivar": "품종명 또는 빈 문자열",
  "classification": {{
    "plant_type": "식물 유형",
    "horticultural_group": "원예 분류",
    "flowering_period": "예: 4~5월 또는 늦봄",
    "flower_color": "구체적인 꽃색과 변화 양상",
    "height": "예: 40~60 cm",
    "use": "주요 용도"
  }},
  "characteristics_draft": "해외 자료를 번역·통합한 객관적인 특성 설명 5~8문장",
  "breeding_process_draft": "육종·선발·증식 과정을 자연스럽게 정리한 4~6문장",
  "research_notes": ["사람이 확인할 사항"]
}}
"""

    gemini_model = None
    fallback_reason = None

    try:
        result = GeminiService().structure_json(
            prompt
        )
        generated = result.data
        gemini_model = result.model
    except GeminiQuotaError as exc:
        fallback_reason = str(exc)
        generated = _search_fallback_draft(
            name,
            sources,
            fallback_reason,
        )
    except GeminiNotConfiguredError as exc:
        fallback_reason = str(exc)
        generated = _search_fallback_draft(
            name,
            sources,
            fallback_reason,
        )
    except GeminiError as exc:
        fallback_reason = str(exc)
        generated = _search_fallback_draft(
            name,
            sources,
            fallback_reason,
        )

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

    overall = _dedupe_images(
        _google_image_candidates(
            overall_google,
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
        _google_image_candidates(
            closeup_google,
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
            f"'{name}'와 일치하는 전체 모습 "
            "사진 후보를 찾지 못했습니다."
        )

    if not closeup:
        raise PlantResearchError(
            f"'{name}'와 일치하는 근접 "
            "사진 후보를 찾지 못했습니다."
        )

    web_sources = [
        {
            "title": item.title,
            "url": item.link,
            "type": "Serper Google Search",
            "status": "검색 근거",
            "snippet": item.snippet,
            "domain": item.display_link,
        }
        for item in sources
    ]

    notes = [
        str(note)
        for note in generated.get(
            "research_notes",
            [],
        )
        if str(note).strip()
    ]

    return {
        "build_version": BUILD_VERSION,
        "research_query": name,
        "matched_name": (
            generated.get("matched_name")
            or name
        ),
        "korean_name": (
            _clean_generated(generated.get("korean_name"), name)
        ),
        "scientific_name": (
            _clean_generated(generated.get("scientific_name"), name)
        ),
        "genus": (
            generated.get("genus")
            or (
                name.split()[0]
                if name.split()
                else ""
            )
        ),
        "cultivar": (
            generated.get("cultivar")
            or ""
        ),
        "agency_recommendation": agency,
        "match_confidence": None,
        "classification": {
            "plant_type": (
                classification.get(
                    "plant_type"
                )
                or "관상용 식물"
            ),
            "horticultural_group": (
                classification.get(
                    "horticultural_group"
                )
                or "원예 재배 식물"
            ),
            "flowering_period": (
                classification.get(
                    "flowering_period"
                )
                or _extract_flowering_period(_combined_snippets(sources))
            ),
            "flower_color": (
                classification.get(
                    "flower_color"
                )
                or _extract_flower_color(_combined_snippets(sources))
            ),
            "height": (
                classification.get(
                    "height"
                )
                or _extract_height(_combined_snippets(sources))
            ),
            "use": (
                classification.get("use")
                or "정원·화단·분화 및 조경용"
            ),
        },
        "characteristics_draft": (
            generated.get(
                "characteristics_draft"
            )
            or (
                _search_fallback_draft(name, sources, "검색 기반 초안")["characteristics_draft"]
            )
        ),
        "breeding_process_draft": (
            generated.get(
                "breeding_process_draft"
            )
            or (
                _search_fallback_draft(name, sources, "검색 기반 초안")["breeding_process_draft"]
            )
        ),
        "shipment_match": {
            "status": (
                "ZIP 생성 시 Drive 자동 검색"
            ),
            "message": (
                "Shipment Overview에서 현재 입력 "
                "품종을 찾고 같은 행 H열 Shipment를 "
                "사용합니다."
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
                "status": (
                    "Gemini 1회 구조화"
                    if gemini_model
                    else "Serper 검색자료 번역·요약"
                ),
            },
            {
                "name": "품종 육성과정",
                "status": (
                    "Gemini 1회 구조화"
                    if gemini_model
                    else "Serper 검색자료 번역·요약"
                ),
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
                "status": "현재 입력 품종 후보",
            },
            {
                "name": "근접 사진",
                "status": "현재 입력 품종 후보",
            },
        ],
        "warnings": [
            *notes,
            (
                "Gemini API 할당량이 부족해도 "
                "Google 검색 기반 초안으로 계속 진행됩니다."
            ),
            (
                "사진은 제출 전에 품종 일치 여부와 "
                "이용 조건을 확인해야 합니다."
            ),
            (
                "AI 또는 검색 기반 초안은 제출 전 "
                "담당자가 최종 검토해야 합니다."
            ),
        ],
        "research_provider": {
            "web": "Serper Google Search",
            "images": (
                "Google Image Search + "
                "Wikimedia Commons"
            ),
            "generation": (
                f"Gemini {gemini_model}"
                if gemini_model
                else "Serper 검색결과 기반 안전 초안"
            ),
            "gemini_fallback_reason": fallback_reason,
        },
    }
