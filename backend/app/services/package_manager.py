from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone

from app.services.document_manager import DocumentBundle
from app.services.drive_manager import DriveAssets


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
