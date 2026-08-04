from __future__ import annotations

import re
from typing import Any

from app.services.gemini_service import GeminiService
from app.services.google_search_service import (
    GoogleSearchError,
    GoogleSearchService,
    ImageSearchResult,
    WebSearchResult,
)
from app.services.wikimedia_service import search_commons_images


class PlantResearchError(RuntimeError):
    pass


BUILD_VERSION = "v10.1-valid-model-name"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())


def _terms(name: str) -> list[str]:
    words = [
        re.sub(r"[^A-Za-z0-9가-힣]+", "", word).lower()
        for word in re.split(r"\s+", str(name or "").strip())
    ]
    return list(dict.fromkeys(
        word for word in words
        if len(word) >= 3 and word not in {"spp", "sp", "var", "cv"}
    ))


def _score(text: str, terms: list[str]) -> int:
    normalized = _norm(text)
    return sum(
        12 if index == 0 else 8
        for index, term in enumerate(terms)
        if _norm(term) and _norm(term) in normalized
    )


def _google_candidates(
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
            "title": image.title or f"{variety_name} {'전체 모습' if role == 'overall' else '근접 모습'}",
            "role": role,
            "preview_url": image.thumbnail_url or image.image_url,
            "download_url": image.image_url or image.thumbnail_url,
            "backup_url": image.thumbnail_url,
            "source_url": image.context_url,
            "source": image.display_link or "Google 이미지 검색",
            "license": "제출 전 원본 페이지에서 이용 조건과 품종 일치 여부를 확인하세요.",
            "recommended": False,
            "research_query": variety_name,
        }
        searchable = " ".join(
            str(item.get(key, ""))
            for key in ("title", "source", "source_url", "preview_url", "download_url")
        )
        score = _score(searchable, terms)
        if score <= 0:
            continue
        item["relevance_score"] = score
        output.append(item)

    return sorted(output, key=lambda item: -int(item["relevance_score"]))


def _commons_candidates(
    variety_name: str,
    role: str,
    prefix: str,
) -> list[dict[str, Any]]:
    terms = _terms(variety_name)
    queries = (
        [f'"{variety_name}" whole plant', f'"{variety_name}" habit']
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
        for image in search_commons_images(query, limit=10):
            key = image.original_url or image.thumbnail_url
            if not key or key in seen:
                continue

            item = {
                "id": f"{prefix}-commons-{len(output) + 1}",
                "title": image.title or f"{variety_name} {'전체 모습' if role == 'overall' else '근접 모습'}",
                "role": role,
                "preview_url": image.thumbnail_url,
                "download_url": image.original_url,
                "backup_url": image.thumbnail_url,
                "source_url": image.description_url,
                "source": "Wikimedia Commons",
                "license": image.license_name or "Commons 원본 페이지에서 라이선스 확인",
                "recommended": False,
                "research_query": variety_name,
            }
            searchable = " ".join(
                str(item.get(key_name, ""))
                for key_name in ("title", "source_url", "preview_url", "download_url")
            )
            score = _score(searchable, terms)
            if score <= 0:
                continue

            item["relevance_score"] = score
            seen.add(key)
            output.append(item)

    return sorted(output, key=lambda item: -int(item["relevance_score"]))


def _dedupe(items: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("download_url") or item.get("preview_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break
    if output:
        output[0]["recommended"] = True
    return output


def _validate_identity(variety_name: str, generated: dict[str, Any]) -> None:
    terms = _terms(variety_name)
    identity = _norm(" ".join(
        str(generated.get(key, ""))
        for key in ("matched_name", "scientific_name", "genus", "cultivar")
    ))

    if terms and not any(_norm(term) in identity for term in terms):
        raise PlantResearchError(
            "Gemini 조사 결과가 입력 품종과 일치하지 않습니다. "
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

    input_normalized = _norm(variety_name)
    if "sunlover" not in input_normalized and "sun lover" not in variety_name.lower():
        if any(value in combined for value in ("sunlover", "sun lover", "튤립 썬러버")):
            raise PlantResearchError(
                "이전 Sunlover 시험 데이터가 새 품종 결과에 섞여 반환되었습니다."
            )


def research_variety(variety_name: str, agency: str) -> dict[str, Any]:
    name = variety_name.strip()
    if not name:
        raise PlantResearchError("품종명이 비어 있습니다.")

    gemini = GeminiService()
    google_sources: list[WebSearchResult] = []
    overall_google: list[ImageSearchResult] = []
    closeup_google: list[ImageSearchResult] = []

    try:
        search = GoogleSearchService()
        merged: dict[str, WebSearchResult] = {}
        for query in (
            f'"{name}" botanical plant profile',
            f'"{name}" horticulture characteristics height',
            f'"{name}" breeder origin cultivar',
        ):
            for result in search.search_web(query, num=10):
                searchable = f"{result.title} {result.snippet} {result.link}"
                if _score(searchable, _terms(name)) > 0:
                    merged[result.link] = result

        google_sources = list(merged.values())[:16]
        overall_google = search.search_images(
            f'"{name}" whole plant habit botanical',
            num=10,
        )
        closeup_google = search.search_images(
            f'"{name}" close up flower foliage catkin',
            num=10,
        )
    except GoogleSearchError:
        pass
    except Exception:
        pass

    source_text = "\n".join(
        f"- {item.title}\n  {item.snippet}\n  {item.link}"
        for item in google_sources
    )

    marker = f"REQUEST_VARIETY::{name}"
    grounded_text, grounded_sources = gemini.grounded_research(f"""
{marker}

정확한 입력 식물명은 '{name}'이다.
반드시 이 식물 또는 품종만 조사하고 이전 요청, 예시 품종, Sunlover 자료를 재사용하지 마라.
동명이종과 유사 품종을 구분하라.

정확한 학명, 식물 유형, 꽃 또는 관상 부위 색상, 개화기 또는 관상 시기,
성숙 높이, 주요 용도, 형태·생육 특성, 육성자·육성연도·선발·증식 과정을 조사하라.
확인할 수 없는 내용은 '공급사 또는 권리자 자료 확인 필요'라고 명시하라.
신고기관은 {agency}이며 한국어로 객관적으로 작성하라.
""")

    combined_sources = [
        {
            "title": item.title,
            "url": item.link,
            "type": "Google Custom Search",
            "status": "검색 근거",
            "snippet": item.snippet,
        }
        for item in google_sources
    ]
    existing = {item["url"] for item in combined_sources}
    for item in grounded_sources:
        if item["url"] not in existing:
            combined_sources.append(item)
            existing.add(item["url"])

    generated = gemini.structure_json(f"""
요청 식별자: {marker}

아래 조사문을 오직 '{name}' 식물의 생산·수입판매 신고용 JSON으로 구조화하라.
다른 품종 또는 이전 예시의 내용을 절대 섞지 마라.
직접적인 근거가 없는 값은 '공급사 또는 권리자 자료 확인 필요'라고 적어라.

조사문:
{grounded_text}

Google 검색 요약:
{source_text or '직접 검색 결과 없음'}

다음 JSON 키만 반환하라:
{{
  "matched_name": "입력 식물과 일치하는 정확한 이름",
  "korean_name": "확인된 한글명 또는 빈 문자열",
  "scientific_name": "정확한 학명과 품종명",
  "genus": "속명",
  "cultivar": "품종명 또는 빈 문자열",
  "classification": {{
    "plant_type": "식물 유형",
    "horticultural_group": "원예 분류",
    "flowering_period": "개화기 또는 관상 시기",
    "flower_color": "꽃 또는 주요 관상 부위 색상",
    "height": "성숙 높이",
    "use": "주요 용도"
  }},
  "characteristics_draft": "'{name}'에 관한 객관적인 특성 3~6문장",
  "breeding_process_draft": "'{name}'의 확인된 육성과정 2~4문장",
  "research_notes": ["사람이 확인할 사항"]
}}
""")

    if not isinstance(generated, dict):
        raise PlantResearchError("Gemini 조사 결과 형식이 올바르지 않습니다.")
    _validate_identity(name, generated)

    classification = generated.get("classification")
    if not isinstance(classification, dict):
        classification = {}

    overall = _dedupe(
        _google_candidates(overall_google, "overall", "overall", name)
        + _commons_candidates(name, "overall", "overall")
    )
    closeup = _dedupe(
        _google_candidates(closeup_google, "closeup", "closeup", name)
        + _commons_candidates(name, "closeup", "closeup")
    )

    if not overall:
        raise PlantResearchError(
            f"'{name}'와 일치하는 전체 모습 사진 후보를 찾지 못했습니다."
        )
    if not closeup:
        raise PlantResearchError(
            f"'{name}'와 일치하는 근접 사진 후보를 찾지 못했습니다."
        )

    return {
        "build_version": BUILD_VERSION,
        "research_query": name,
        "matched_name": generated.get("matched_name") or name,
        "korean_name": generated.get("korean_name") or "",
        "scientific_name": generated.get("scientific_name") or name,
        "genus": generated.get("genus") or (name.split()[0] if name.split() else ""),
        "cultivar": generated.get("cultivar") or "",
        "agency_recommendation": agency,
        "match_confidence": None,
        "classification": {
            "plant_type": classification.get("plant_type") or "확인 필요",
            "horticultural_group": classification.get("horticultural_group") or "확인 필요",
            "flowering_period": classification.get("flowering_period") or "확인 필요",
            "flower_color": classification.get("flower_color") or "확인 필요",
            "height": classification.get("height") or "확인 필요",
            "use": classification.get("use") or "확인 필요",
        },
        "characteristics_draft": generated.get("characteristics_draft") or (
            f"{name} 특성은 공급사 또는 권리자 자료 확인이 필요합니다."
        ),
        "breeding_process_draft": generated.get("breeding_process_draft") or (
            f"{name} 육성과정은 공급사 또는 권리자 자료 확인이 필요합니다."
        ),
        "shipment_match": {
            "status": "ZIP 생성 시 Drive 자동 검색",
            "message": "Shipment Overview에서 현재 입력 품종을 찾고 같은 행 H열 Shipment를 사용합니다.",
            "candidate_files": [],
        },
        "drive_sources": [],
        "web_sources": combined_sources[:18],
        "image_candidates": [*overall, *closeup],
        "selected_images": {
            "overall": overall[0]["id"],
            "closeup": closeup[0]["id"],
        },
        "required_documents": [
            {"name": "생산·수입판매 신고서", "status": "자동 생성"},
            {"name": "품종 특성 설명", "status": "현재 입력 품종 조사"},
            {"name": "품종 육성과정", "status": "현재 입력 품종 조사"},
            {"name": "인보이스", "status": "Google Drive 검색"},
            {"name": "검역합격증 또는 Phyto", "status": "Google Drive 검색"},
            {"name": "전체 모습 사진", "status": "현재 입력 품종 후보"},
            {"name": "근접 사진", "status": "현재 입력 품종 후보"},
        ],
        "warnings": [
            *[
                str(note)
                for note in generated.get("research_notes", [])
                if str(note).strip()
            ],
            "사진은 제출 전에 품종 일치 여부와 이용 조건을 확인해야 합니다.",
            "AI 초안은 제출 전 담당자가 최종 검토해야 합니다.",
        ],
        "research_provider": {
            "web": "Google Custom Search + Gemini Search Grounding",
            "images": "Google Image Search + Wikimedia Commons strict fallback",
            "generation": "Gemini API",
        },
    }
