from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.services.google_search_service import (
    GoogleSearchService,
    ImageSearchResult,
    WebSearchResult,
)


class GeminiNotConfiguredError(RuntimeError):
    pass


class PlantResearchError(RuntimeError):
    pass


def _clean_json_text(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class GeminiService:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.gemini_api_key.strip()
        self.model = settings.gemini_model.strip() or "gemini-2.5-flash"

        if not self.api_key:
            raise GeminiNotConfiguredError(
                "Render 환경변수 GEMINI_API_KEY가 누락되었습니다."
            )

    def generate_json(self, prompt: str) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:generateContent?key={self.api_key}"
        )
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.15,
                "responseMimeType": "application/json",
            },
        }

        request = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Jogyeongmaru-AI-ERP/7.0",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PlantResearchError(
                f"Gemini API 오류({exc.code}): {detail[:700]}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise PlantResearchError(
                f"Gemini API 연결 실패: {exc}"
            ) from exc
        except Exception as exc:
            raise PlantResearchError(
                f"Gemini API 응답 처리 실패: {exc}"
            ) from exc

        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback")
            raise PlantResearchError(
                f"Gemini가 결과를 반환하지 않았습니다: {feedback}"
            )

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(
            str(part.get("text", ""))
            for part in parts
            if part.get("text")
        )
        if not text.strip():
            raise PlantResearchError(
                "Gemini 응답에 텍스트가 없습니다."
            )

        try:
            return json.loads(_clean_json_text(text))
        except json.JSONDecodeError as exc:
            raise PlantResearchError(
                f"Gemini JSON 해석 실패: {text[:800]}"
            ) from exc


def _source_payload(results: list[WebSearchResult]) -> list[dict[str, str]]:
    return [
        {
            "title": item.title,
            "url": item.link,
            "snippet": item.snippet,
            "domain": item.display_link,
        }
        for item in results
    ]


def _image_candidates(
    results: list[ImageSearchResult],
    role: str,
    prefix: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for index, image in enumerate(results[:5], start=1):
        candidate_id = f"{prefix}-{index}"
        candidates.append(
            {
                "id": candidate_id,
                "title": image.title or (
                    "품종 전체 모습" if role == "overall" else "꽃 근접 모습"
                ),
                "role": role,
                "preview_url": image.thumbnail_url or image.image_url,
                "download_url": image.image_url or image.thumbnail_url,
                "backup_url": image.thumbnail_url,
                "source_url": image.context_url,
                "source": image.display_link or "Google 이미지 검색",
                "license": "제출 전 원본 페이지의 이용 조건과 품종 일치 여부를 확인하세요.",
                "width": image.width,
                "height": image.height,
                "recommended": index == 1,
            }
        )

    return candidates


def research_variety(
    variety_name: str,
    agency: str,
) -> dict[str, Any]:
    name = variety_name.strip()
    if not name:
        raise PlantResearchError("품종명이 비어 있습니다.")

    search = GoogleSearchService()

    profile_results = search.search_web(
        f'"{name}" plant profile cultivar characteristics height flowering color',
        num=8,
    )
    origin_results = search.search_web(
        f'"{name}" cultivar breeder origin introduction year nursery',
        num=6,
    )

    merged: dict[str, WebSearchResult] = {}
    for item in [*profile_results, *origin_results]:
        merged[item.link] = item
    sources = list(merged.values())[:12]

    if not sources:
        raise PlantResearchError(
            f"Google 검색에서 '{name}' 품종 자료를 찾지 못했습니다."
        )

    overall_images = search.search_images(
        f'"{name}" whole plant habit garden',
        num=6,
    )
    closeup_images = search.search_images(
        f'"{name}" flower close up bloom',
        num=6,
    )

    overall_candidates = _image_candidates(
        overall_images,
        "overall",
        "overall",
    )
    closeup_candidates = _image_candidates(
        closeup_images,
        "closeup",
        "closeup",
    )

    if not overall_candidates:
        raise PlantResearchError(
            f"Google 이미지 검색에서 '{name}' 전체 모습 사진을 찾지 못했습니다."
        )
    if not closeup_candidates:
        raise PlantResearchError(
            f"Google 이미지 검색에서 '{name}' 꽃 근접 사진을 찾지 못했습니다."
        )

    source_json = json.dumps(
        _source_payload(sources),
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
너는 식물 품종 생산·수입판매 신고자료를 작성하는 조사 담당자다.

입력 품종명: {name}
신고 기관: {agency}

아래 Google 검색 결과의 제목·요약·URL만 근거로 사용하라.
검색 결과에 없는 사실을 추측하거나 만들어내지 마라.
정보가 확인되지 않으면 반드시 "공급사 또는 권리자 자료 확인 필요"라고 적어라.
품종명과 종(species)을 혼동하지 말고, 입력한 품종과 직접 관련된 정보만 선택하라.
한국어로 작성하되 학명과 품종명은 원문 표기를 유지하라.

검색 결과:
{source_json}

반드시 아래 키를 가진 JSON 객체 하나만 반환하라.

{{
  "matched_name": "검색 자료에서 확인된 최적 품종명",
  "korean_name": "통용 한글명. 확인되지 않으면 입력 품종명을 한글로 억지 번역하지 말고 빈 문자열",
  "scientific_name": "확인된 학명 또는 품종명",
  "genus": "속명",
  "cultivar": "품종명",
  "classification": {{
    "plant_type": "식물 유형",
    "horticultural_group": "원예 분류 또는 확인 필요",
    "flowering_period": "개화기 또는 확인 필요",
    "flower_color": "꽃색 또는 확인 필요",
    "height": "성숙 높이 또는 확인 필요",
    "use": "주요 용도 또는 확인 필요"
  }},
  "characteristics_draft": "신고서에 사용할 객관적인 품종 특성 설명. 검색 근거만 사용해 3~6문장",
  "breeding_process_draft": "육성자·육성연도·선발과정이 근거에서 확인되면 작성하고, 확인되지 않으면 그 사실을 명확히 밝히는 2~4문장",
  "research_notes": ["불확실하거나 사람이 확인해야 할 사항"]
}}
"""

    generated = GeminiService().generate_json(prompt)

    classification = generated.get("classification")
    if not isinstance(classification, dict):
        classification = {}

    web_sources = [
        {
            "title": item.title,
            "url": item.link,
            "type": "Google 검색 자료",
            "status": "검토 필요",
            "snippet": item.snippet,
            "domain": item.display_link,
        }
        for item in sources
    ]

    image_candidates = [
        *overall_candidates,
        *closeup_candidates,
    ]

    return {
        "matched_name": generated.get("matched_name") or name,
        "korean_name": generated.get("korean_name") or "",
        "scientific_name": generated.get("scientific_name") or name,
        "genus": generated.get("genus") or name.split()[0],
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
        "characteristics_draft": (
            generated.get("characteristics_draft")
            or "검색 자료에서 품종 특성을 충분히 확인하지 못했습니다."
        ),
        "breeding_process_draft": (
            generated.get("breeding_process_draft")
            or "육성자 및 육성과정은 공급사 또는 권리자 자료 확인이 필요합니다."
        ),
        "shipment_match": {
            "status": "ZIP 생성 시 Google Drive 자동 검색",
            "message": (
                "Shipment Overview에서 품종을 찾고 같은 행 H열 Shipment를 사용합니다."
            ),
            "candidate_files": [],
        },
        "drive_sources": [],
        "web_sources": web_sources,
        "image_candidates": image_candidates,
        "selected_images": {
            "overall": overall_candidates[0]["id"],
            "closeup": closeup_candidates[0]["id"],
        },
        "required_documents": [
            {"name": "생산·수입판매 신고서", "status": "자동 생성"},
            {"name": "품종 특성 설명", "status": "Google 검색+Gemini 초안"},
            {"name": "품종 육성과정", "status": "Google 검색+Gemini 초안"},
            {"name": "인보이스", "status": "Google Drive 검색"},
            {"name": "검역합격증 또는 Phyto", "status": "Google Drive 검색"},
            {"name": "전체 모습 사진", "status": "Google 이미지 후보 선택"},
            {"name": "꽃 근접 사진", "status": "Google 이미지 후보 선택"},
        ],
        "warnings": [
            *[
                str(note)
                for note in generated.get("research_notes", [])
                if str(note).strip()
            ],
            "Google 이미지 검색 결과는 제출 전에 품종 일치 여부와 이용 조건을 사람이 확인해야 합니다.",
            "AI 초안은 검색 결과를 요약한 것이므로 제출 전 담당자 최종 검토가 필요합니다.",
        ],
        "research_provider": {
            "search": "Google Programmable Search JSON API",
            "generation": "Gemini API",
        },
    }
