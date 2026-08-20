from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone

from app.services.document_manager import COMPANY, DocumentBundle
from app.services.drive_manager import DriveAssets


_HANGUL = re.compile(r"[가-힣]")


def korean_only(value: str) -> str:
    """한글이 없으면 빈 값으로 돌려준다.

    국립종자원 작물 등록부는 한글 일반명으로 찾는다. AI가 'Hydrangea' 같은 영문을
    돌려주면 검색이 어긋나므로, 차라리 비워서 사람이 고르게 한다.
    """
    text = str(value or "").strip()
    return text if _HANGUL.search(text) else ""


def derive_cultivar(draft_data: dict, scientific_name: str, fallback: str) -> str:
    """품종명만 뽑는다.

    조사 결과에 품종명이 따로 없으면 신고명에서 학명 부분을 걷어낸 나머지를 쓴다.
    (예: 'Hydrangea macrophylla Endless Summer' - 'Hydrangea macrophylla'
      -> 'Endless Summer')
    """
    cultivar = str(draft_data.get("cultivar") or "").strip()
    if cultivar:
        return cultivar

    name = str(fallback or "").strip()
    words = str(scientific_name or "").split()[:2]
    rest = name
    for word in words:
        rest = re.sub(rf"\b{re.escape(word)}\b", " ", rest, flags=re.I)
    rest = re.sub(r"\s+", " ", rest).strip(" '\"")
    return rest or name


def safe(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(value or "")).strip() or "report"


def build_manifest(variety_name: str, draft_data: dict, assets: DriveAssets, documents: DocumentBundle, warnings: list[str]) -> dict:
    final_name = draft_data.get("matched_name") or variety_name
    return {
        "build_version": "v26-hwp-submission-document",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variety": variety_name,
        "matched_name": final_name,
        "scientific_name": str(draft_data.get("scientific_name") or variety_name),
        "shipment": assets.shipment,
        "shipment_sheet": assets.shipment_sheet,
        "shipment_row": assets.shipment_row,
        "import_year_folder": assets.import_year,
        "supplier_folder": assets.supplier_folder,
        "shipping_folder": assets.shipping_folder,
        "container_folder": assets.container_folder,
        "invoice": assets.invoice_name,
        "quarantine": assets.quarantine_name,
        "quarantine_number": assets.quarantine_number,
        "report_formats": ["HWP"] if documents.hwp else (["HWPX"] if documents.hwpx else ["DOCX"]),
        "warnings": warnings,
        # 국립종자원(seednet) 신고 자동입력이 그대로 쓰는 값. 서식 ①~⑨란과 1:1로 맞춘다.
        "report_fields": {
            "신고인_성명": COMPANY["representative"],
            "신고인_생년월일": COMPANY["birth_date"],
            "신고인_주소": COMPANY["address"],
            "신고인_법인명칭": COMPANY["company_name"],
            "신고인_전화번호": COMPANY["phone"],
            "작물_일반명": korean_only(draft_data.get("korean_name")),
            "작물_학명": str(draft_data.get("scientific_name") or ""),
            "품종_명칭": derive_cultivar(
                draft_data, draft_data.get("scientific_name", ""), final_name
            ),
            # 국립종자원은 품종명 한글 표기를 따로 받는다(예: PIIHQ-I → 피엘엘에이치큐-엘).
            # 규정상 사람이 정하는 이름이라 AI가 만들지 않고, 신고 화면에서 비면 직접 입력한다.
            "품종_한글명": str(draft_data.get("cultivar_ko") or ""),
            "원산지": str(draft_data.get("origin") or ""),
            "종자업_등록번호": COMPANY["seed_business_number"],
            "검역합격_발급번호": assets.quarantine_number or "",
            "품종_특성설명": str(draft_data.get("characteristics_draft") or ""),
            "육성과정_설명": str(draft_data.get("breeding_process_draft") or ""),
        },
    }


def build_package(
    *,
    variety_name: str,
    assets: DriveAssets,
    documents: DocumentBundle,
    overall_image: bytes,
    closeup_image: bytes,
    manifest: dict,
) -> bytes:
    output = io.BytesIO()
    base = safe(variety_name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        # 국립종자원 제출본은 한글 .hwp다. .hwp가 만들어졌으면 그것만 넣고,
        # 실패했을 때만 예비본 .hwpx를 대신 넣는다(워드는 제출 서식이 아니라 넣지 않는다).
        if documents.hwp:
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.hwp", documents.hwp)
        elif documents.hwpx:
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.hwpx", documents.hwpx)
        else:
            # 한글 형식이 둘 다 실패한 경우에만 최후 수단으로 워드를 넣는다.
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.docx", documents.docx)
        if assets.quarantine_data:
            archive.writestr(f"{base}/02_{safe(assets.quarantine_name or '검역서류')}", assets.quarantine_data)
        if assets.invoice_output:
            archive.writestr(f"{base}/{assets.invoice_zip_name or '03_신고용_invoice.bin'}", assets.invoice_output)
        archive.writestr(f"{base}/04_품종전체사진.jpg", overall_image)
        archive.writestr(f"{base}/05_꽃근접사진.jpg", closeup_image)
        archive.writestr(f"{base}/06_처리요약.pdf", documents.summary_pdf)
        archive.writestr(f"{base}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return output.getvalue()
