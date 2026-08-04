from __future__ import annotations

import json
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


def _google_image_candidates(
    images: list[ImageSearchResult], role: str, prefix: str
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, image in enumerate(images[:5], 1):
        output.append(
            {
                "id": f"{prefix}-google-{index}",
                "title": image.title or ("품종 전체 모습" if role == "overall" else "꽃 근접 모습"),
                "role": role,
                "preview_url": image.thumbnail_url or image.image_url,
                "download_url": image.image_url or image.thumbnail_url,
                "backup_url": image.thumbnail_url,
                "source_url": image.context_url,
                "source": image.display_link or "Google 이미지 검색",
                "license": "제출 전 원본 페이지에서 이용 조건과 품종 일치 여부를 확인하세요.",
                "recommended": index == 1,
            }
        )
    return output


def _commons_candidates(name: str, role: str, prefix: str) -> list[dict[str, Any]]:
    query = f'"{name}" plant' if role == "overall" else f'"{name}" flower'
    output: list[dict[str, Any]] = []
    for index, image in enumerate(search_commons_images(query, limit=6), 1):
        output.append(
            {
                "id": f"{prefix}-commons-{index}",
                "title": image.title or ("품종 전체 모습" if role == "overall" else "꽃 근접 모습"),
                "role": role,
                "preview_url": image.thumbnail_url,
                "download_url": image.original_url,
                "backup_url": image.thumbnail_url,
                "source_url": image.description_url,
                "source": "Wikimedia Commons",
                "license": image.license_name or "Commons 원본 페이지에서 라이선스 확인",
                "recommended": False,
            }
        )
    return output


def _dedupe_images(items: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("download_url") or item.get("preview_url") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break
    if output:
        output[0]["recommended"] = True
    return output


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
        queries = [
            f'"{name}" cultivar plant profile flowering height color',
            f'"{name}" breeder origin cultivar introduction',
        ]
        merged: dict[str, WebSearchResult] = {}
        for query in queries:
            for result in search.search_web(query, num=10):
                merged[result.link] = result
        google_sources = list(merged.values())[:14]
        overall_google = search.search_images(f'"{name}" whole plant habit garden', num=8)
        closeup_google = search.search_images(f'"{name}" flower close up bloom', num=8)
    except GoogleSearchError:
        google_sources = []
    except Exception:
        google_sources = []

    source_text = "\n".join(
        f"- {item.title}\n  {item.snippet}\n  {item.link}"
        for item in google_sources
    )
    grounded_prompt = f"""
입력 품종명은 '{name}'이다. 이 식물 품종의 정확한 학명, 품종명, 식물 유형,
꽃색, 개화기, 성숙 높이, 주요 용도, 품종 특성, 육성자·육성연도·육성과정을 조사하라.
동명이종과 다른 품종을 혼동하지 말고, 불확실한 사항은 불확실하다고 명시하라.
신고기관은 {agency}이다. 한국어로 객관적으로 정리하라.
"""
    grounded_text, grounded_sources = gemini.grounded_research(grounded_prompt)

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
    existing_urls = {item["url"] for item in combined_sources}
    for item in grounded_sources:
        if item["url"] not in existing_urls:
            combined_sources.append(item)
            existing_urls.add(item["url"])

    structure_prompt = f"""
아래 조사문을 식물 품종 생산·수입판매 신고용 JSON으로 구조화하라.
입력 품종명: {name}
신고 기관: {agency}

조사문:
{grounded_text}

추가 Google 검색 요약:
{source_text or '없음'}

추측하지 말고 확인되지 않은 값은 '공급사 또는 권리자 자료 확인 필요'로 적어라.
반드시 다음 JSON 키만 반환하라:
{{
  "matched_name": "정확한 품종명",
  "korean_name": "확인된 한글명 또는 빈 문자열",
  "scientific_name": "학명과 품종명",
  "genus": "속명",
  "cultivar": "품종명",
  "classification": {{
    "plant_type": "식물 유형",
    "horticultural_group": "원예 분류",
    "flowering_period": "개화기",
    "flower_color": "꽃색",
    "height": "성숙 높이",
    "use": "주요 용도"
  }},
  "characteristics_draft": "객관적인 품종 특성 3~6문장",
  "breeding_process_draft": "육성과정 2~4문장",
  "research_notes": ["사람이 확인할 사항"]
}}
"""
    generated = gemini.structure_json(structure_prompt)
    classification = generated.get("classification") if isinstance(generated.get("classification"), dict) else {}

    overall = _dedupe_images(
        _google_image_candidates(overall_google, "overall", "overall")
        + _commons_candidates(name, "overall", "overall")
    )
    closeup = _dedupe_images(
        _google_image_candidates(closeup_google, "closeup", "closeup")
        + _commons_candidates(name, "closeup", "closeup")
    )
    if not overall:
        raise PlantResearchError(f"'{name}' 전체 모습 사진 후보를 찾지 못했습니다.")
    if not closeup:
        raise PlantResearchError(f"'{name}' 꽃 근접 사진 후보를 찾지 못했습니다.")

    return {
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
        "characteristics_draft": generated.get("characteristics_draft") or "품종 특성 확인 필요",
        "breeding_process_draft": generated.get("breeding_process_draft") or "공급사 또는 권리자 자료 확인 필요",
        "shipment_match": {
            "status": "ZIP 생성 시 Drive 자동 검색",
            "message": "Shipment Overview에서 품종을 찾고 같은 행 H열 Shipment를 사용합니다.",
            "candidate_files": [],
        },
        "drive_sources": [],
        "web_sources": combined_sources[:16],
        "image_candidates": [*overall, *closeup],
        "selected_images": {"overall": overall[0]["id"], "closeup": closeup[0]["id"]},
        "required_documents": [
            {"name": "생산·수입판매 신고서", "status": "자동 생성"},
            {"name": "품종 특성 설명", "status": "Google+Gemini 조사"},
            {"name": "품종 육성과정", "status": "Google+Gemini 조사"},
            {"name": "인보이스", "status": "Google Drive 검색"},
            {"name": "검역합격증 또는 Phyto", "status": "Google Drive 검색"},
            {"name": "전체 모습 사진", "status": "후보 선택"},
            {"name": "꽃 근접 사진", "status": "후보 선택"},
        ],
        "warnings": [
            *[str(note) for note in generated.get("research_notes", []) if str(note).strip()],
            "사진은 제출 전에 품종 일치 여부와 이용 조건을 확인해야 합니다.",
            "AI 초안은 제출 전 담당자가 최종 검토해야 합니다.",
        ],
        "research_provider": {
            "web": "Google Custom Search + Gemini Search Grounding",
            "images": "Google Image Search + Wikimedia Commons fallback",
            "generation": "Gemini API",
        },
    }
