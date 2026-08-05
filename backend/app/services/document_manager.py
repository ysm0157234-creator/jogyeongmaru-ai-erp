from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.hwp_template_service import HwpTemplateError, build_hwpx_report
from app.services.report_generator import build_compatible_docx, build_pdf_summary


@dataclass
class DocumentBundle:
    hwpx: bytes | None
    docx: bytes
    summary_pdf: bytes


COMPANY = {
    "representative": "황수영",
    "birth_date": "1985. 5. 15.",
    "address": "경기도 평택시 진위면 서촌로 38-9",
    "short_address": "경기 평택시 진위면 서촌로 38-9",
    "company_name": "농업회사법인 주식회사 조경마루",
    "phone": "010-9377-3058",
    "seed_business_number": "제10-평택-2023-30-01호",
}


def validate_and_prepare_text(draft_data: dict, warnings: list[str]) -> None:
    characteristics = str(draft_data.get("characteristics_draft") or "").strip()
    breeding = str(draft_data.get("breeding_process_draft") or "").strip()
    if not characteristics:
        characteristics = "품종 특성 설명을 직접 입력해야 합니다."
        warnings.append("품종 특성 설명이 비어 있어 직접 입력 안내문을 사용했습니다.")
    if not breeding:
        breeding = "품종 육성과정을 직접 입력해야 합니다."
        warnings.append("품종 육성과정이 비어 있어 직접 입력 안내문을 사용했습니다.")
    draft_data["characteristics_draft"] = characteristics
    draft_data["breeding_process_draft"] = breeding


def build_documents(
    *,
    draft_data: dict,
    shipment: str,
    quarantine_number: str,
    overall_image: bytes,
    closeup_image: bytes,
    warnings: list[str],
    invoice_name: str,
    quarantine_name: str,
) -> DocumentBundle:
    validate_and_prepare_text(draft_data, warnings)
    template_path = Path(__file__).resolve().parent.parent / "templates" / "plant_import_report_template.hwpx"
    now = datetime.now()
    report_date_spaced = f"{now.year}년     {now.month}월     {now.day}일"
    hwpx: bytes | None = None
    try:
        hwpx = build_hwpx_report(
            template_path=template_path,
            result_data=draft_data,
            quarantine_number=quarantine_number,
            report_date_spaced=report_date_spaced,
            overall_image=overall_image,
            closeup_image=closeup_image,
            company=COMPANY,
        )
        with zipfile.ZipFile(io.BytesIO(hwpx)) as check:
            required = {"mimetype", "Contents/section0.xml"}
            if not required.issubset(set(check.namelist())):
                raise HwpTemplateError("생성된 HWPX 필수 항목이 누락되었습니다.")
    except Exception as exc:
        warnings.append(f"HWPX 생성 실패: {exc}. 호환용 DOCX는 계속 생성했습니다.")
        hwpx = None

    docx = build_compatible_docx(
        result_data=draft_data,
        shipment=shipment,
        quarantine_number=quarantine_number,
        overall_image=overall_image,
        closeup_image=closeup_image,
        warnings=warnings,
    )
    final_name = draft_data.get("matched_name") or draft_data.get("query") or "품종"
    scientific_name = str(draft_data.get("scientific_name") or final_name)
    summary = build_pdf_summary(str(final_name), scientific_name, shipment, invoice_name, quarantine_name)
    return DocumentBundle(hwpx=hwpx, docx=docx, summary_pdf=summary)
