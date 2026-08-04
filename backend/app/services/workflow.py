from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.services.drive_service import DriveFile, FOLDER_MIME, GoogleDriveService
from app.services.invoice_processor import (
    create_invoice_extract_xlsx,
    extract_invoice_pdf_pages,
    filter_invoice_xlsx,
)
from app.services.report_generator import (
    build_breeding_document,
    build_characteristics_document,
    build_main_report,
    build_pdf_summary,
    build_sample_pledge_document,
)
from app.services.shipment_parser import ShipmentMatch, find_variety_in_workbook


class RequiredFileMissingError(RuntimeError):
    pass


def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip()


def is_invoice(file: DriveFile) -> bool:
    name = file.name.lower()
    return (
        file.mime_type != FOLDER_MIME
        and ("invoice" in name or "인보이스" in name)
        and name.endswith((".xlsx", ".xlsm", ".pdf"))
    )


def is_quarantine(file: DriveFile) -> bool:
    name = file.name.lower()
    return (
        file.mime_type != FOLDER_MIME
        and ("검역" in name or "quarantine" in name or "phytosanitary" in name)
        and name.endswith((".pdf", ".jpg", ".jpeg", ".png"))
    )


def choose_first(files: list[DriveFile], predicate) -> DriveFile | None:
    matches = [file for file in files if predicate(file)]
    return sorted(matches, key=lambda file: file.name.lower())[0] if matches else None


def find_folder_containing_file(
    drive: GoogleDriveService,
    root_folder_id: str,
    wanted_file_id: str,
) -> DriveFile | None:
    all_items = drive.walk(root_folder_id, max_depth=5, max_items=2000)
    file_map = {item.id: item for item in all_items}
    wanted = file_map.get(wanted_file_id)
    if not wanted:
        return None
    parent_ids = wanted.parents or []
    for parent_id in parent_ids:
        parent = file_map.get(parent_id)
        if parent and parent.mime_type == FOLDER_MIME:
            return parent
        try:
            metadata = drive.get_metadata(parent_id)
            if metadata.mime_type == FOLDER_MIME:
                return metadata
        except Exception:
            continue
    return None


def find_tulipa_invoice(
    drive: GoogleDriveService,
    root_folder_id: str,
) -> tuple[DriveFile, DriveFile]:
    files = drive.walk(root_folder_id, max_depth=5, max_items=2000)
    invoices = [file for file in files if is_invoice(file)]
    for invoice in sorted(invoices, key=lambda file: file.name.lower()):
        try:
            data = drive.download(invoice.id)
            from app.services.invoice_processor import workbook_contains, pdf_contains
            if invoice.name.lower().endswith((".xlsx", ".xlsm")):
                found = workbook_contains(data, ["Tulipa"])
            else:
                found = pdf_contains(data, ["Tulipa"])
            if found:
                folder = find_folder_containing_file(
                    drive,
                    root_folder_id,
                    invoice.id,
                )
                if folder:
                    return folder, invoice
        except Exception:
            continue
    raise RequiredFileMissingError(
        "Shipment Overview에서 품종을 찾지 못했고, 2026수입에서도 "
        "Tulipa가 포함된 인보이스를 찾지 못했습니다."
    )


def download_image(url: str) -> bytes:
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 Jogyeongmaru-AI-ERP/4.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urlopen(request, timeout=40) as response:
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise RequiredFileMissingError(
                    f"사진 URL이 이미지가 아닙니다: {url}"
                )
            data = response.read(15 * 1024 * 1024)
            if len(data) < 1000:
                raise RequiredFileMissingError(
                    f"사진 데이터가 너무 작습니다: {url}"
                )
            return data
    except RequiredFileMissingError:
        raise
    except Exception as exc:
        raise RequiredFileMissingError(
            f"사진을 내려받지 못했습니다: {url} / {exc}"
        ) from exc


def selected_image_url(draft_data: dict, role: str) -> str:
    selected_id = draft_data.get("selected_images", {}).get(role)
    for image in draft_data.get("image_candidates", []):
        if image.get("id") == selected_id:
            return image.get("download_url") or image.get("preview_url") or ""
    raise RequiredFileMissingError(
        f"{'전체 모습' if role == 'overall' else '꽃 근접'} 사진이 선택되지 않았습니다."
    )


def process_invoice(
    invoice_file: DriveFile,
    invoice_data: bytes,
    variety_name: str,
    shipment: str,
    overview_values: dict,
) -> tuple[bytes, str]:
    lower = invoice_file.name.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm")):
            return (
                filter_invoice_xlsx(invoice_data, variety_name, shipment),
                f"06_{safe_name(variety_name)}_신고용_invoice.xlsx",
            )
        if lower.endswith(".pdf"):
            output, _ = extract_invoice_pdf_pages(invoice_data, variety_name)
            return output, f"06_{safe_name(variety_name)}_신고용_invoice.pdf"
    except Exception:
        pass

    return (
        create_invoice_extract_xlsx(
            variety_name,
            shipment,
            overview_values,
            invoice_file.name,
        ),
        f"06_{safe_name(variety_name)}_신고용_invoice_발췌.xlsx",
    )


def run_workflow(
    variety_name: str,
    draft_data: dict,
) -> tuple[bytes, dict]:
    settings = get_settings()
    drive = GoogleDriveService()
    log: list[str] = []

    shipment_bytes = drive.download(settings.shipment_overview_file_id)
    matched_folder: DriveFile | None = None

    try:
        match = find_variety_in_workbook(shipment_bytes, variety_name)
        log.append(
            f"Shipment Overview {match.sheet_name} 시트 {match.row_number}행에서 품종 발견"
        )
        log.append(f"H열 Shipment: {match.shipment}")
        matched_folder = drive.find_child_folder(
            settings.import_2026_folder_id,
            match.shipment,
        )
        if not matched_folder:
            raise RequiredFileMissingError(
                f"2026수입에서 H열 Shipment와 같은 폴더를 찾지 못했습니다: {match.shipment}"
            )
    except LookupError:
        matched_folder, fallback_invoice = find_tulipa_invoice(
            drive,
            settings.import_2026_folder_id,
        )
        match = ShipmentMatch(
            sheet_name="2026수입 Tulipa 보조검색",
            row_number=0,
            description=variety_name,
            shipment=matched_folder.name,
            values={
                "품종명": variety_name,
                "검색 방식": "Tulipa 포함 인보이스의 폴더 사용",
            },
            source="tulipa_fallback",
        )
        log.append(
            f"Shipment Overview 미발견 → Tulipa 인보이스 폴더 사용: {matched_folder.name}"
        )

    folder_files = drive.walk(
        matched_folder.id,
        max_depth=3,
        max_items=700,
    )
    invoice_file = choose_first(folder_files, is_invoice)
    quarantine_file = choose_first(folder_files, is_quarantine)

    if not invoice_file:
        raise RequiredFileMissingError(
            f"'{matched_folder.name}' 폴더 안에 인보이스가 없습니다."
        )
    if not quarantine_file:
        raise RequiredFileMissingError(
            f"'{matched_folder.name}' 폴더 안에 검역합격증이 없습니다."
        )

    invoice_source_data = drive.download(invoice_file.id)
    quarantine_data = drive.download(quarantine_file.id)

    overall_url = selected_image_url(draft_data, "overall")
    closeup_url = selected_image_url(draft_data, "closeup")
    overall_image = download_image(overall_url)
    closeup_image = download_image(closeup_url)

    if overall_url == closeup_url:
        raise RequiredFileMissingError(
            "전체 모습과 꽃 근접 사진은 서로 다른 사진이어야 합니다."
        )

    final_name = draft_data.get("matched_name", variety_name)
    korean_name = draft_data.get("korean_name", "튤립 썬러버")
    scientific_name = draft_data.get(
        "scientific_name",
        "Tulipa 'Sun Lover'",
    )
    characteristics = draft_data.get(
        "characteristics_draft",
        "",
    )
    breeding_process = draft_data.get(
        "breeding_process_draft",
        "",
    )
    if not characteristics.strip():
        raise RequiredFileMissingError("품종 특성 설명이 비어 있습니다.")
    if not breeding_process.strip():
        raise RequiredFileMissingError("품종 육성과정이 비어 있습니다.")

    invoice_output, invoice_name = process_invoice(
        invoice_file,
        invoice_source_data,
        variety_name,
        match.shipment,
        match.values,
    )

    main_report = build_main_report(
        final_name,
        korean_name,
        scientific_name,
        match.shipment,
        characteristics,
        breeding_process,
        overall_image,
        closeup_image,
    )
    characteristics_doc = build_characteristics_document(
        final_name,
        korean_name,
        scientific_name,
        characteristics,
        overall_image,
        closeup_image,
    )
    breeding_doc = build_breeding_document(
        final_name,
        korean_name,
        breeding_process,
    )
    pledge_doc = build_sample_pledge_document(
        final_name,
        korean_name,
    )
    summary_pdf = build_pdf_summary(
        final_name,
        scientific_name,
        match.shipment,
        invoice_file.name,
        quarantine_file.name,
    )

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "variety": variety_name,
        "shipment": match.shipment,
        "shipment_source": match.source,
        "matched_folder": {
            "id": matched_folder.id,
            "name": matched_folder.name,
        },
        "invoice_source": {
            "id": invoice_file.id,
            "name": invoice_file.name,
        },
        "quarantine_source": {
            "id": quarantine_file.id,
            "name": quarantine_file.name,
        },
        "photos": {
            "overall": overall_url,
            "closeup": closeup_url,
        },
        "search_log": log,
        "generated_files": [
            "01_생산수입판매신고서_검토안.docx",
            "02_품종특성설명.docx",
            "03_품종육성과정.docx",
            "04_시료제출확약서.docx",
            f"05_{quarantine_file.name}",
            invoice_name,
            "07_품종전체사진.jpg",
            "08_꽃근접사진.jpg",
            "09_처리요약.pdf",
            "manifest.json",
        ],
    }

    folder = safe_name(variety_name)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{folder}/01_생산수입판매신고서_검토안.docx",
            main_report,
        )
        archive.writestr(
            f"{folder}/02_품종특성설명.docx",
            characteristics_doc,
        )
        archive.writestr(
            f"{folder}/03_품종육성과정.docx",
            breeding_doc,
        )
        archive.writestr(
            f"{folder}/04_시료제출확약서.docx",
            pledge_doc,
        )
        archive.writestr(
            f"{folder}/05_{safe_name(quarantine_file.name)}",
            quarantine_data,
        )
        archive.writestr(
            f"{folder}/{invoice_name}",
            invoice_output,
        )
        archive.writestr(
            f"{folder}/07_품종전체사진.jpg",
            overall_image,
        )
        archive.writestr(
            f"{folder}/08_꽃근접사진.jpg",
            closeup_image,
        )
        archive.writestr(
            f"{folder}/09_처리요약.pdf",
            summary_pdf,
        )
        archive.writestr(
            f"{folder}/manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    return output.getvalue(), manifest
