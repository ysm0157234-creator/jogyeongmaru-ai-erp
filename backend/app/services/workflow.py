
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.services.drive_service import GoogleDriveService, DriveNotConfiguredError, DriveFile
from app.services.shipment_parser import find_variety_in_workbook
from app.services.invoice_processor import (
    workbook_contains,
    filter_invoice_xlsx,
    extract_invoice_pdf_pages,
    create_invoice_extract_xlsx,
)
from app.services.report_generator import build_docx, build_pdf_summary

SUNLOVER = {
    "matched_name": "Tulipa spp. Sunlover",
    "korean_name": "튤립 썬러버",
    "scientific_name": "Tulipa 'Sun Lover'",
    "characteristics": (
        "겹꽃형 튤립 품종으로 개화 초기에는 황금빛 노란색을 띠고 "
        "적황색 줄무늬가 나타난다. 개화가 진행되면서 주황색에서 "
        "주황빛 적색으로 변화하며, 꽃은 크고 풍성한 겹꽃 형태이다. "
        "늦봄에 개화하며 화단, 컨테이너 및 절화용으로 이용할 수 있다."
    ),
    "breeding_process": (
        "상기 품종을 국내에 수입·유통하기 위하여 네덜란드 수출업체를 통해 "
        "적법하게 구근을 수입하였다. 해외에서 육성 및 증식된 영양번식성 "
        "품종이며, 세부 육성자와 최초 선발연도는 공급사의 증빙자료를 "
        "확인하여 최종 기재한다."
    ),
}

def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip()

def find_invoice_candidates(
    drive: GoogleDriveService,
    folder_id: str,
    shipment: str,
) -> list[DriveFile]:
    all_files = drive.walk(folder_id, max_depth=6)
    shipment_norm = re.sub(r"\s+", "", shipment).lower()

    name_matches = [
        f for f in all_files
        if shipment_norm and shipment_norm in re.sub(r"\s+", "", f.name).lower()
    ]
    searchable = name_matches or all_files

    invoice_like = [
        f for f in searchable
        if any(token in f.name.lower() for token in ["invoice", "인보이스"])
        and f.mime_type != "application/vnd.google-apps.folder"
    ]
    return invoice_like

def run_workflow(variety_name: str) -> tuple[bytes, dict]:
    settings = get_settings()
    drive = GoogleDriveService()

    shipment_bytes = drive.download(settings.shipment_overview_file_id)
    shipment_match = find_variety_in_workbook(shipment_bytes, variety_name)

    invoice_candidates = find_invoice_candidates(
        drive,
        settings.import_2026_folder_id,
        shipment_match.shipment,
    )

    selected_invoice = None
    selected_invoice_data = None
    invoice_output_name = None
    invoice_output_data = None
    invoice_mode = "발췌본 생성"

    # Prefer xlsx because it can be filtered by row.
    ordered = sorted(
        invoice_candidates,
        key=lambda f: (
            0 if f.name.lower().endswith(".xlsx") else 1,
            f.name.lower(),
        )
    )
    for candidate in ordered:
        try:
            data = drive.download(candidate.id)
            if candidate.name.lower().endswith(".xlsx"):
                if workbook_contains(data, [variety_name, variety_name.split()[-1]]):
                    selected_invoice = candidate
                    selected_invoice_data = data
                    invoice_output_data = filter_invoice_xlsx(
                        data,
                        variety_name,
                        shipment_match.shipment,
                    )
                    invoice_output_name = f"{safe_name(variety_name)}_신고용_invoice.xlsx"
                    invoice_mode = "원본 XLSX에서 해당 품종 행만 남김"
                    break
            elif candidate.name.lower().endswith(".pdf"):
                try:
                    pdf_data, page_count = extract_invoice_pdf_pages(data, variety_name)
                    selected_invoice = candidate
                    selected_invoice_data = data
                    invoice_output_data = pdf_data
                    invoice_output_name = f"{safe_name(variety_name)}_신고용_invoice.pdf"
                    invoice_mode = f"원본 PDF에서 품종 포함 페이지 {page_count}장 추출"
                    break
                except LookupError:
                    continue
        except Exception:
            continue

    if invoice_output_data is None:
        invoice_output_data = create_invoice_extract_xlsx(
            variety_name,
            shipment_match.shipment,
            shipment_match.values,
            selected_invoice.name if selected_invoice else None,
        )
        invoice_output_name = f"{safe_name(variety_name)}_신고용_invoice_발췌.xlsx"

    docx = build_docx(
        variety_name=SUNLOVER["matched_name"],
        korean_name=SUNLOVER["korean_name"],
        scientific_name=SUNLOVER["scientific_name"],
        shipment_number=shipment_match.shipment,
        characteristics=SUNLOVER["characteristics"],
        breeding_process=SUNLOVER["breeding_process"],
    )
    pdf = build_pdf_summary(
        variety_name=SUNLOVER["matched_name"],
        korean_name=SUNLOVER["korean_name"],
        scientific_name=SUNLOVER["scientific_name"],
        shipment_number=shipment_match.shipment,
        characteristics=SUNLOVER["characteristics"],
        breeding_process=SUNLOVER["breeding_process"],
    )

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "variety": variety_name,
        "shipment_overview": {
            "file_id": settings.shipment_overview_file_id,
            "sheet": shipment_match.sheet_name,
            "row": shipment_match.row_number,
            "description": shipment_match.description,
            "shipment": shipment_match.shipment,
            "values": shipment_match.values,
        },
        "import_2026_folder_id": settings.import_2026_folder_id,
        "invoice_candidates": [
            {"id": f.id, "name": f.name, "mime_type": f.mime_type}
            for f in invoice_candidates
        ],
        "selected_invoice": (
            {"id": selected_invoice.id, "name": selected_invoice.name}
            if selected_invoice else None
        ),
        "invoice_processing": invoice_mode,
        "generated_files": [
            "신고서_검토안.docx",
            "처리요약.pdf",
            invoice_output_name,
            "manifest.json",
        ],
        "important_note": (
            "HWP 직접 생성은 Render/Linux에서 안정적으로 지원되지 않아 "
            "같은 검토 항목의 DOCX와 PDF를 생성합니다. HWP가 반드시 필요하면 "
            "Windows 한컴오피스 자동화 모듈을 별도 연결해야 합니다."
        ),
    }

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        base = safe_name(variety_name)
        zf.writestr(f"{base}/신고서_검토안.docx", docx)
        zf.writestr(f"{base}/처리요약.pdf", pdf)
        zf.writestr(f"{base}/{invoice_output_name}", invoice_output_data)
        zf.writestr(
            f"{base}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        )
    return output.getvalue(), manifest
