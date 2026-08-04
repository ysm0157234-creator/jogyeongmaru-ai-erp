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


BUILD_VERSION = "v12.0-serper"


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


def _search_fallback_draft(
    name: str,
    sources: list[WebSearchResult],
    reason: str,
) -> dict[str, Any]:
    snippets: list[str] = []
    seen: set[str] = set()

    for result in sources:
        snippet = re.sub(
            r"\s+",
            " ",
            result.snippet,
        ).strip()
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        snippets.append(snippet)
        if len(snippets) >= 4:
            break

    evidence = " ".join(snippets)
    if evidence:
        characteristics = (
            f"{name}에 관한 Serper 검색자료에서는 다음 내용이 "
            f"확인됩니다. {evidence} "
            "다만 이 내용은 검색결과 요약을 정리한 것으로, "
            "최종 신고 전 공급사 또는 공식 품종자료와 대조해야 합니다."
        )
    else:
        characteristics = (
            f"{name}의 형태·생육 특성은 현재 검색자료에서 "
            "충분히 확인되지 않았습니다. 공급사 또는 권리자의 "
            "공식 품종자료 확인 후 최종 작성해야 합니다."
        )

    return {
        "matched_name": name,
        "korean_name": "",
        "scientific_name": name,
        "genus": (
            name.split()[0]
            if name.split()
            else ""
        ),
        "cultivar": _extract_cultivar(name),
        "classification": {
            "plant_type": "공식 자료 확인 필요",
            "horticultural_group": "공식 자료 확인 필요",
            "flowering_period": "공식 자료 확인 필요",
            "flower_color": "공식 자료 확인 필요",
            "height": "공식 자료 확인 필요",
            "use": "공식 자료 확인 필요",
        },
        "characteristics_draft": characteristics,
        "breeding_process_draft": (
            f"{name}의 육성자, 육성연도, 선발 및 증식 과정은 "
            "공급사 또는 권리자 증빙자료 확인 후 최종 기재해야 합니다."
        ),
        "research_notes": [
            reason,
            "Gemini 대신 Serper 검색결과 기반 안전 초안을 생성했습니다.",
            "확인되지 않은 분류·규격은 임의로 작성하지 않았습니다.",
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
확인되지 않은 항목은 반드시 '공급사 또는 권리자 자료 확인 필요'라고 적어라.

검색 결과:
{source_text}

다음 JSON 객체만 반환하라:
{{
  "matched_name": "입력과 일치하는 정확한 이름",
  "korean_name": "확인된 한글명 또는 빈 문자열",
  "scientific_name": "정확한 학명과 품종 표기",
  "genus": "속명",
  "cultivar": "품종명 또는 빈 문자열",
  "classification": {{
    "plant_type": "식물 유형",
    "horticultural_group": "원예 분류",
    "flowering_period": "개화기 또는 관상 시기",
    "flower_color": "꽃 또는 관상 부위 색상",
    "height": "성숙 높이",
    "use": "주요 용도"
  }},
  "characteristics_draft": "검색 근거만 사용한 객관적인 특성 3~6문장",
  "breeding_process_draft": "확인된 육성과정 2~4문장. 미확인 정보는 확인 필요 명시",
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
            generated.get("korean_name")
            or ""
        ),
        "scientific_name": (
            generated.get("scientific_name")
            or name
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
                or "확인 필요"
            ),
            "horticultural_group": (
                classification.get(
                    "horticultural_group"
                )
                or "확인 필요"
            ),
            "flowering_period": (
                classification.get(
                    "flowering_period"
                )
                or "확인 필요"
            ),
            "flower_color": (
                classification.get(
                    "flower_color"
                )
                or "확인 필요"
            ),
            "height": (
                classification.get(
                    "height"
                )
                or "확인 필요"
            ),
            "use": (
                classification.get("use")
                or "확인 필요"
            ),
        },
        "characteristics_draft": (
            generated.get(
                "characteristics_draft"
            )
            or (
                f"{name} 특성은 공급사 또는 "
                "권리자 자료 확인이 필요합니다."
            )
        ),
        "breeding_process_draft": (
            generated.get(
                "breeding_process_draft"
            )
            or (
                f"{name} 육성과정은 공급사 또는 "
                "권리자 자료 확인이 필요합니다."
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
                    else "Google 검색 기반 안전 초안"
                ),
            },
            {
                "name": "품종 육성과정",
                "status": (
                    "Gemini 1회 구조화"
                    if gemini_model
                    else "공식 증빙 확인 필요"
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
